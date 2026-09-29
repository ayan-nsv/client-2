# Placeholder file - Copy your holdflight/src/core/website_analyzer.py content here
# Website analysis logic

import sys
import os
import logging
import re
import json
from typing import Dict, Any, Optional, Tuple, List
import time
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from holdflight.src.scraping.scan import scrape_website_data
from holdflight.src.ai.summarize import summarize_data_with_gpt3, format_company_info, extract_products_with_gpt
from holdflight.src.scraping.logo_scarping import scrape_logo
from holdflight.src.scraping.favicon import scrape_favicon
from holdflight.src.color.brand_color_analyzer import analyze_brand_colors, combine_colors
from holdflight.src.utils.fonts_matching import match_scraped_fonts_regular_only
from holdflight.src.utils.chrome_options import validate_public_url

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Google Fonts API Key - Load from environment variable only
GOOGLE_FONTS_API_KEY = os.environ.get('GOOGLE_FONTS_API_KEY')
if not GOOGLE_FONTS_API_KEY:
    logger.warning("GOOGLE_FONTS_API_KEY environment variable is not set. Font matching will be disabled. Please set it in your .env file.")

class WebsiteAnalyzer:
        """Complete website analysis tool combining scraping and AI summarization."""
        
        def __init__(self):
            logger.info("Initializing WebsiteAnalyzer")
            self.results = {}
            self.headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        
        def extract_company_name_from_url(self, url: str) -> str:
            """
            Extract company name from URL domain.
            
            Args:
                url: Website URL
                
            Returns:
                Extracted company name
            """
            logger.info(f"Extracting company name from URL: {url}")
            try:
                # Parse the URL to get the domain
                if not url.startswith(('http://', 'https://')):
                    logger.debug("Adding https:// prefix to URL")
                    url = 'https://' + url
                
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                logger.debug(f"Extracted domain: {domain}")
                
                # Remove common prefixes
                domain = domain.replace('www.', '')
                logger.debug(f"Domain after removing www: {domain}")
                
                # Split by dots and take the main part (before TLD)
                domain_parts = domain.split('.')
                if len(domain_parts) >= 2:
                    company_name = domain_parts[0]
                    logger.debug(f"Extracted company name part: {company_name}")
                else:
                    company_name = domain
                    logger.debug(f"Using full domain as company name: {company_name}")
                
                # Clean up the company name
                company_name = company_name.replace('-', ' ').replace('_', ' ')
                logger.debug(f"Cleaned company name: {company_name}")
                
                # Capitalize first letter of each word
                company_name = ' '.join(word.capitalize() for word in company_name.split())
                logger.info(f"Final company name: {company_name}")
                
                return company_name
                
            except Exception as e:
                logger.error(f"Error extracting company name: {e}", exc_info=True)
                return "Unknown Company"
        
        def search_company_website(self, company_name: str) -> Tuple[str, str]:
            """
            Website discovery from free-form company names is disabled.

            Open search-engine scraping allowed attacker-controlled company names
            to choose arbitrary SERP result URLs. Callers must provide a canonical
            website URL instead.
            """
            logger.warning("Website search disabled; explicit URL required for company=%s", company_name)
            return None, f"{company_name} official website"
        
        def analyze_company(self, company_name: str, url: Optional[str] = None) -> Dict[str, Any]:
            """
            Complete company analysis workflow - can search for URL or use provided URL.
            
            Args:
                company_name: Name of the company
                url: Optional website URL. If not provided, will search for it.
                
            Returns:
                Dictionary containing complete analysis results
            """
            print(f"🚀 Starting Company Analysis")
            print("=" * 50)
            print(f"🏢 Company: {company_name}")
            
            if url:
                print(f"🌐 Using provided URL: {url}")
                website_url = url
            else:
                return self._create_error_response(
                    company_name,
                    f"Website URL is required for '{company_name}'. Search-engine discovery is disabled.",
                )
            
            print(f"🌐 Target URL: {website_url}")
            print("=" * 50)
            
            return self.analyze_website(website_url, company_name)
        
        def _get_clean_domain(self, url: str) -> str:
            """Extract clean domain from URL."""
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain.split(':')[0]  # Remove port if present

        def _find_logo_in_html(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
            """Search for logo in HTML using multiple strategies."""
            possible_logos = []

            # 1. Meta tags (og:image, but only if it's logo-like)
            meta_logo = soup.find('meta', property='og:image')
            if meta_logo and meta_logo.get('content'):
                if re.search(r'logo|brand', meta_logo['content'], re.I):
                    possible_logos.append(meta_logo['content'])

            # 2. Favicons (not ideal as logos, but fallback)
            for rel in ['icon', 'shortcut icon', 'apple-touch-icon']:
                favicon = soup.find('link', rel=re.compile(rel, re.I))
                if favicon and favicon.get('href'):
                    possible_logos.append(favicon['href'])

            # 3. Img tags with strong logo indicators
            logo_indicators = ['logo', 'brand', 'site-logo', 'header-logo']
            for indicator in logo_indicators:
                # By class
                imgs = soup.find_all('img', class_=re.compile(indicator, re.I))
                possible_logos.extend(img['src'] for img in imgs if img.get('src'))

                # By ID
                img = soup.find('img', id=re.compile(indicator, re.I))
                if img and img.get('src'):
                    possible_logos.append(img['src'])

                # By alt text
                img = soup.find('img', alt=re.compile(indicator, re.I))
                if img and img.get('src'):
                    possible_logos.append(img['src'])

            # 4. Background styles
            for selector in ['header', '.header', '.logo-container', '.navbar-brand']:
                element = soup.select_one(selector)
                if element and element.get('style'):
                    match = re.search(r'url\([\'\"]?(.*?)[\'\"]?\)', element['style'])
                    if match:
                        possible_logos.append(match.group(1))

            # Filtering: allow only SVG, PNG, JPG/JPEG
            valid_logos = []
            for logo in set(possible_logos):
                if not logo.startswith(('http://', 'https://')):
                    logo = urljoin(base_url, logo)

                if logo.lower().endswith(('.svg', '.png', '.jpg', '.jpeg')):
                    valid_logos.append(logo)

            # Return first valid logo if found
            return valid_logos[0] if valid_logos else None

        def get_website_logo(self, url: str) -> Optional[str]:
            """Get website logo URL using the logo_scarping module."""
            try:
                logger.info(f"Fetching logo using logo_scarping module for: {url}")
                logo_result = scrape_logo(url)

                if isinstance(logo_result, list):
                    primary_logo = logo_result[0] if logo_result else ''
                else:
                    primary_logo = logo_result

                if primary_logo:
                    logger.info(f"Logo found: {primary_logo}")
                    return primary_logo

                logger.warning("No logo found, attempting to fetch favicon")
                favicon_url = scrape_favicon(url)
                if favicon_url:
                    logger.info(f"Using favicon as logo fallback: {favicon_url}")
                    return favicon_url

                # Fallback to Google favicon as last resort
                domain = self._get_clean_domain(url)
                fallback_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
                logger.info(f"Using fallback favicon: {fallback_url}")
                return fallback_url

            except Exception as e:
                logger.error(f"Error getting logo for {url}: {str(e)}")
                # Fallback to Google favicon on error
                try:
                    domain = self._get_clean_domain(url)
                    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
                except Exception:
                    return None

        def analyze_website(self, url: str, company_name: str = None) -> Dict[str, Any]:
            """
            Perform complete website analysis including scraping and AI summarization.
            
            Args:
                url: Website URL to analyze
                company_name: Optional company name (will be extracted from URL if not provided)
                
            Returns:
                Dictionary containing analysis results including logo URL
            """
            logger.info(f"=== Starting website analysis for {url} ===")
            try:
                validate_public_url(url)
                # Get all possible logo URLs using logo_scraping.py (will be passed to GPT with products)
                logger.info("Fetching website logos using logo_scarping.py")
                print(f"\n🎨 Scraping website logos...")
                logo_urls = scrape_logo(url, return_all=True)
                
                if logo_urls and len(logo_urls) > 0:
                    logger.info(f"Found {len(logo_urls)} logo URLs for GPT selection")
                    print(f"✅ Found {len(logo_urls)} potential logos (will be selected by AI)")
                else:
                    logger.warning("No logos found")
                    logo_urls = []
                
                # Get favicon separately using favicon.py
                logger.info("Fetching website favicon using favicon.py")
                print(f"\n🌟 Scraping website favicon...")
                favicon_url = scrape_favicon(url)
                if favicon_url:
                    logger.debug(f"Found favicon URL: {favicon_url}")
                else:
                    logger.warning("No favicon found")
                    favicon_url = ''
                
                # Step 1: Scrape website data (moved before color extraction)
                logger.info("Starting website scraping")
                print(f"\n🔍 Scraping website: {url}")
                
                scraped_data = scrape_website_data(url)
                logger.debug(f"Scraped data keys: {list(scraped_data.keys()) if isinstance(scraped_data, dict) else 'Not a dict'}")
                
                if not scraped_data or 'error' in scraped_data:
                    error_msg = scraped_data.get('error', 'Unknown error') if isinstance(scraped_data, dict) else 'No data returned'
                    logger.error(f"Scraping failed: {error_msg}")
                    print(f"❌ Scraping failed: {error_msg}")
                    return {'error': f'Scraping failed: {error_msg}'}
                
                # If scraping succeeded but returned minimal data, still try to process it
                if isinstance(scraped_data, dict) and len(scraped_data) < 3:
                    logger.warning("Scraping returned minimal data, but proceeding with analysis")
                    print("⚠️ Minimal data scraped, but proceeding with analysis")
                    
                logger.info("Website scraping completed successfully")
                
                # Handle case where scraped_data is a list instead of a dict
                if isinstance(scraped_data, list):
                    if scraped_data and isinstance(scraped_data[0], dict):
                        # Use the first item if it's a list of dicts
                        scraped_data = scraped_data[0]
                    else:
                        return self._create_error_response(company_name, "Unexpected data format from website scraper")
                
                if not isinstance(scraped_data, dict):
                    return self._create_error_response(company_name, f"Unexpected data type from website scraper: {type(scraped_data).__name__}")
                
                # Ensure required fields exist
                if 'theme_colors' not in scraped_data:
                    scraped_data['theme_colors'] = {}
                if 'fonts' not in scraped_data:
                    scraped_data['fonts'] = []  # Fonts should be a list, not a dict
                
                # Step 2: Generate AI summary (first API call)
                logger.info("Starting AI summary generation")
                print("📝 Generating AI summary with address and keywords...")
                
                company_info = summarize_data_with_gpt3(scraped_data, company_name)
                logger.debug(f"AI summary generated: {bool(company_info)}")
                
                if not company_info:
                    logger.error("AI summary generation returned empty result")
                    print("❌ AI summary generation failed")
                    return {'error': 'AI summary generation failed'}
                
                # Check if the AI summary contains an error message
                if isinstance(company_info, dict) and company_info.get('company_info', '').startswith('❌'):
                    logger.error(f"AI summary generation failed: {company_info.get('company_info', '')}")
                    print(f"❌ AI summary generation failed: {company_info.get('company_info', '')}")
                    return {'error': f'AI summary generation failed: {company_info.get("company_info", "")}'}
                    
                logger.info("AI summary generation completed successfully")
                
                # Step 2.5: Extract products and select best logo (second API call - combined)
                logger.info("Starting product extraction and logo selection")
                print("📦 Extracting products, categories and selecting best logo...")
                
                product_info = extract_products_with_gpt(scraped_data, company_name, logo_urls, url)
                logger.debug(f"Product extraction completed: {bool(product_info)}")
                
                # Get the selected logo from product extraction (this is the ORIGINAL URL, not Firebase URL)
                logo_url_original = product_info.get('selected_logo', '')
                if logo_url_original:
                    logger.info(f"AI selected logo (original URL): {logo_url_original}")
                    print(f"✅ Logo selected by AI: {logo_url_original}")
                else:
                    logger.warning("No logo selected by AI")
                    logo_url_original = ''
                
                # Store original logo URL for later use (before Firebase upload)
                # We'll use this for color extraction since Firebase URLs might not work for extraction
                logo_url = logo_url_original  # This will be updated to Firebase URL later in app.py
                
                # Step 5: Extract brand colors using AI-selected logo (or favicon as fallback)
                # This happens AFTER AI selects the best logo, ensuring we use the correct logo
                logger.info("Starting color analysis using brand_color_analyzer (after AI logo selection)")
                
                # Determine which image to use for color extraction:
                # Priority: 1) AI-selected logo (original URL), 2) Favicon (original URL), 3) First logo from list, 4) None
                # NOTE: We use original URLs here because they're more reliable for color extraction
                image_url_for_colors = ''
                original_image_url = ''  # Store original URL for reference
                if logo_url_original and logo_url_original.strip():
                    image_url_for_colors = logo_url_original
                    original_image_url = logo_url_original
                    logger.info(f"Using AI-selected logo (original URL) for color extraction: {image_url_for_colors}")
                    print(f"\n🎨 Analyzing website and AI-selected logo colors...")
                elif favicon_url and favicon_url.strip():
                    image_url_for_colors = favicon_url
                    original_image_url = favicon_url
                    logger.info(f"Using favicon (original URL) for color extraction (no AI-selected logo): {image_url_for_colors}")
                    print(f"\n🎨 Analyzing website and favicon colors...")
                elif logo_urls and len(logo_urls) > 0:
                    image_url_for_colors = logo_urls[0]
                    original_image_url = logo_urls[0]
                    logger.info(f"Using first logo from list for color extraction (no AI-selected logo or favicon): {image_url_for_colors}")
                    print(f"\n🎨 Analyzing website and logo colors (using first logo as fallback)...")
                else:
                    image_url_for_colors = ''
                    original_image_url = ''
                    logger.info("No logo or favicon available for color extraction")
                    print(f"\n🎨 Analyzing website colors only (no favicon or logo found)...")
                
                try:
                    logger.info(f"🔍 Calling analyze_brand_colors with:")
                    logger.info(f"   website_url: {url}")
                    logger.info(f"   image_url_for_colors: {image_url_for_colors}")
                    print(f"🔍 Starting brand color analysis...")
                    
                    brand_color_result = analyze_brand_colors(url, image_url_for_colors)
                    logger.debug(f"Brand color analysis completed: {bool(brand_color_result)}")
                    
                    # Check if logo color extraction failed - if so, try direct extraction
                    logo_error = brand_color_result.get('logo_error') if brand_color_result else None
                    logo_colors = brand_color_result.get('logo_colors') if brand_color_result else None
                    
                    logger.info(f"🔍 After analyze_brand_colors:")
                    logger.info(f"   logo_colors: {logo_colors} (type: {type(logo_colors)}, length: {len(logo_colors) if logo_colors else 0})")
                    logger.info(f"   logo_error: {logo_error}")
                    if logo_colors:
                        logger.info(f"   logo_colors details: {logo_colors}")
                    
                    # If extraction failed or returned empty, try direct extraction with the same URL
                    if (not logo_colors or logo_error) and image_url_for_colors:
                        logger.info(f"🔄 Logo color extraction failed or returned empty, trying direct extraction with: {image_url_for_colors}")
                        print(f"🔄 Retrying logo color extraction directly...")
                        try:
                            # Try importing from brand_color_analyzer
                            from brand_color_analyzer import extract_logo_colors
                            
                            logger.info(f"🔍 Attempting direct color extraction from: {image_url_for_colors[:80]}...")
                            print(f"🔍 Attempting direct color extraction from: {image_url_for_colors[:60]}...")
                            retry_colors = extract_logo_colors(image_url_for_colors, num_colors=5)
                            if retry_colors and len(retry_colors) > 0:
                                logger.info(f"✅ Successfully extracted {len(retry_colors)} colors via direct extraction")
                                logger.info(f"✅ Extracted colors: {retry_colors}")
                                print(f"✅ Successfully extracted {len(retry_colors)} colors via direct extraction")
                                if brand_color_result:
                                    brand_color_result["logo_colors"] = retry_colors
                                    brand_color_result["logo_error"] = None
                                    logo_colors = retry_colors  # Update local variable too
                            else:
                                logger.warning(f"⚠️ Direct extraction returned empty list for {image_url_for_colors}")
                                logger.warning(f"   This usually means the image has too few pixels after filtering transparent/white/black pixels")
                                print(f"⚠️ Direct extraction returned empty - image might be too small or have insufficient pixels")
                        except Exception as retry_e:
                            logger.error(f"⚠️ Direct extraction failed: {retry_e}", exc_info=True)
                            print(f"⚠️ Direct extraction failed: {retry_e}")
                    
                    if not brand_color_result:
                        logger.warning("⚠️ analyze_brand_colors returned None or empty result")
                        brand_color_result = {}  # Set to empty dict to avoid None errors
                except Exception as e:
                    logger.error(f"❌ Error in analyze_brand_colors: {str(e)}", exc_info=True)
                    print(f"❌ Error extracting colors: {str(e)}")
                    brand_color_result = {}  # Set to empty dict to continue processing
                
                # Step 3: Store and format results
                self.results = {
                    'raw_scraped_data': scraped_data,
                    'analysis_result': company_info,
                    'url': url,
                    'company_name': company_name
                }
                
                # Format results
                logger.info("Formatting analysis results")
                print("✅ Analysis complete!")
                
                # Get element fonts from scraped data if available
                element_fonts = scraped_data.get('element_fonts', {})
                scraped_address_details = scraped_data.get('address_details') or {}
                
                # Match fonts with Google Fonts API
                logger.info("Starting font matching with Google Fonts API")
                print("\n🔤 Matching fonts with Google Fonts...")
                
                matched_fonts = {}
                all_scraped_fonts = []
                
                # Collect all fonts from scraped data
                if 'fonts' in scraped_data and scraped_data['fonts']:
                    # Handle both list and dict formats (for backward compatibility)
                    if isinstance(scraped_data['fonts'], list):
                        all_scraped_fonts.extend(scraped_data['fonts'])
                    elif isinstance(scraped_data['fonts'], dict):
                        # If it's a dict, extract values or keys
                        logger.warning("scraped_data['fonts'] is a dict, expected list. Attempting to extract fonts.")
                        all_scraped_fonts.extend(scraped_data['fonts'].values() if scraped_data['fonts'] else [])
                
                # Add element-specific fonts
                if element_fonts:
                    for element, fonts in element_fonts.items():
                        if isinstance(fonts, list):
                            all_scraped_fonts.extend(fonts)
                
                # Remove duplicates while preserving order
                seen = set()
                all_scraped_fonts = [font for font in all_scraped_fonts if not (font in seen or seen.add(font))]
                
                if all_scraped_fonts:
                    logger.info(f"Found {len(all_scraped_fonts)} unique fonts to match: {all_scraped_fonts[:5]}")  # Log first 5 fonts
                    if GOOGLE_FONTS_API_KEY:
                        try:
                            logger.info(f"Attempting to match fonts with Google Fonts API (API key present)")
                            matched_fonts = match_scraped_fonts_regular_only(all_scraped_fonts, GOOGLE_FONTS_API_KEY)
                            if matched_fonts:
                                logger.info(f"Successfully matched {len(matched_fonts)} fonts with Google Fonts: {list(matched_fonts.keys())}")
                                print(f"Matched {len(matched_fonts)} font(s) with Google Fonts")
                            else:
                                logger.warning(f"No fonts matched with Google Fonts. Scraped fonts: {all_scraped_fonts[:10]}")
                                print(f"No fonts matched with Google Fonts (tried {len(all_scraped_fonts)} fonts)")
                        except ValueError as e:
                            logger.error(f"ValueError in font matching (likely API key issue): {e}")
                            print(f"Font matching failed: {e}")
                            matched_fonts = {}  # Ensure it's an empty dict on error
                        except Exception as e:
                            logger.error(f"Error matching fonts: {type(e).__name__}: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
                            print(f"Font matching failed: {e}")
                            matched_fonts = {}  # Ensure it's an empty dict on error
                    else:
                        logger.warning("GOOGLE_FONTS_API_KEY is not set. Skipping font matching.")
                        print("Warning: GOOGLE_FONTS_API_KEY is not set. Font matching is disabled.")
                        matched_fonts = {}  # Return empty dict when API key is missing
                else:
                    logger.info("No fonts found to match")
                    matched_fonts = {}  # Ensure it's initialized even when no fonts found
                
                # Step 7: Extract colors from brand_color_result (includes logo colors from AI-selected logo)
                extracted_colors = []
                # Store brand color data for response
                website_colors_data = None
                logo_colors_data = None
                brand_color_errors = {}
                
                # Extract colors from brand_color_result
                # IMPORTANT: brand_color_result was created AFTER AI selected the best logo,
                # so logo_colors_data contains colors from the AI-selected logo (or favicon/fallback)
                if brand_color_result and isinstance(brand_color_result, dict):
                    website_colors_data = brand_color_result.get("website_colors")
                    # Get logo_colors - may have been updated by retry extraction above
                    logo_colors_data = brand_color_result.get("logo_colors")  # May include retry results
                    # Also check if logo_colors was set by retry
                    if 'logo_colors' in locals() and logo_colors and not logo_colors_data:
                        logo_colors_data = logo_colors
                    # Store errors if any (may have been cleared by retry)
                    if brand_color_result.get('website_error'):
                        brand_color_errors['website_error'] = brand_color_result.get('website_error')
                    if brand_color_result.get('logo_error'):
                        brand_color_errors['logo_error'] = brand_color_result.get('logo_error')
                    
                    # Log if logo colors were updated by retry
                    if logo_colors_data:
                        logger.info(f"✅ Using logo_colors_data: {len(logo_colors_data)} colors (may include retry results)")
                        print(f"✅ Logo colors available: {len(logo_colors_data)} colors")
                    
                    logger.info(f"Brand color result - website_colors: {bool(website_colors_data)}, logo_colors: {bool(logo_colors_data)}")
                    logger.info(f"Brand color result - logo_colors type: {type(logo_colors_data)}, logo_colors value: {logo_colors_data}")
                    logger.info(f"Brand color result - logo_colors length: {len(logo_colors_data) if logo_colors_data else 0}")
                    
                    if brand_color_result.get('logo_error'):
                        logger.warning(f"⚠️ Logo color extraction error in brand_color_result: {brand_color_result.get('logo_error')}")
                        print(f"⚠️ Logo color extraction error: {brand_color_result.get('logo_error')}")
                    
                    # Check if we have logo_colors_data - it should be a non-empty list
                    if not logo_colors_data or (isinstance(logo_colors_data, list) and len(logo_colors_data) == 0):
                        logger.warning(f"⚠️ logo_colors_data is None or empty!")
                        logger.warning(f"   logo_colors_data value: {logo_colors_data}")
                        logger.warning(f"   image_url_for_colors used: {image_url_for_colors}")
                        logger.warning(f"   This means logo/favicon color extraction failed or returned no colors")
                        logger.warning(f"   Only website colors will be included in the final result")
                        print(f"⚠️ WARNING: No logo colors extracted - only website colors will be used")
                        print(f"   Logo URL used: {image_url_for_colors[:80] if image_url_for_colors else 'None'}...")
                    
                    # DEBUG: Log raw website colors data structure
                    if website_colors_data:
                        logger.info(f"🔍 DEBUG: website_colors type: {type(website_colors_data)}")
                        if isinstance(website_colors_data, dict):
                            logger.info(f"🔍 DEBUG: website_colors keys: {list(website_colors_data.keys())}")
                            if website_colors_data.get('all_colors'):
                                logger.info(f"🔍 DEBUG: all_colors count: {len(website_colors_data.get('all_colors', []))}")
                                logger.info(f"🔍 DEBUG: all_colors first 5: {website_colors_data.get('all_colors', [])[:5]}")
                            if website_colors_data.get('top_colors'):
                                logger.info(f"🔍 DEBUG: top_colors count: {len(website_colors_data.get('top_colors', []))}")
                    
                    # Step 8: Combine colors (includes logo colors from AI-selected logo)
                    # IMPORTANT: Always call combine_colors even if logo_colors_data is None/empty
                    # This ensures we get website colors at minimum
                    # logo_colors_data contains colors from AI-selected logo (or favicon/fallback)
                    if website_colors_data or logo_colors_data:
                        try:
                            # Log what we're passing to combine_colors
                            logger.info(f"🔍 DEBUG: Calling combine_colors with:")
                            logger.info(f"   logo_colors_data: {logo_colors_data} (type: {type(logo_colors_data)}, length: {len(logo_colors_data) if logo_colors_data else 0})")
                            logger.info(f"   website_colors_data: {bool(website_colors_data)} (type: {type(website_colors_data)})")
                            
                            combined_colors = combine_colors(logo_colors_data, website_colors_data)
                            
                            logger.info(f"🔍 DEBUG: combine_colors returned {len(combined_colors) if combined_colors else 0} colors")
                            
                            if combined_colors:
                                # Format colors for API response (extract hex codes as strings, matching old format)
                                logo_color_count = 0
                                website_color_count = 0
                                
                                for color in combined_colors:
                                    if color.get('hex'):
                                        extracted_colors.append(color['hex'].upper())
                                        # Count by source
                                        if color.get('source') == 'favicon':
                                            logo_color_count += 1
                                        elif color.get('source') == 'website':
                                            website_color_count += 1
                                
                                # Determine source for logging
                                has_image_colors = logo_colors_data is not None and len(logo_colors_data) > 0
                                color_source = "favicon" if (favicon_url and favicon_url.strip()) else ("logo (fallback)" if has_image_colors else "none")
                                logger.info(f"✅ Extracted {len(extracted_colors)} colors from brand_color_analyzer")
                                logger.info(f"   └─ Logo/Favicon colors: {logo_color_count}")
                                logger.info(f"   └─ Website colors: {website_color_count}")
                                logger.info(f"   └─ Source: {color_source}")
                                logger.info(f"🔍 DEBUG: Extracted colors list: {extracted_colors}")
                                print(f"✅ Colors extracted: {len(extracted_colors)} colors ({logo_color_count} logo + {website_color_count} website)")
                                
                                if logo_color_count == 0:
                                    logger.warning(f"⚠️ WARNING: No logo colors in combined result! Only website colors included.")
                                    logger.warning(f"⚠️ This means logo color extraction failed or logo_colors_data was empty")
                                    print(f"⚠️ WARNING: No logo colors extracted - only {website_color_count} website colors included")
                                    print(f"⚠️ Expected logo colors like: #EABE06, #79AC85, #6B6B64, #FECC00, #C5A621")
                                
                                if logo_color_count == 0:
                                    logger.warning(f"⚠️ WARNING: No logo colors in combined result! Only website colors included.")
                                    print(f"⚠️ WARNING: No logo colors extracted - only {website_color_count} website colors included")
                            else:
                                logger.warning("⚠️ combine_colors returned empty list")
                        except Exception as e:
                            logger.error(f"Error in combine_colors: {e}", exc_info=True)
                    else:
                        logger.warning("⚠️ Both website_colors_data and logo_colors_data are None/empty - cannot combine colors")
                    
                    # If combine_colors didn't work or returned empty, try direct extraction
                    if not extracted_colors and website_colors_data:
                        logger.info("Trying direct extraction from website_colors")
                        try:
                            if isinstance(website_colors_data, dict):
                                # Check for all_colors first (most complete)
                                if website_colors_data.get('all_colors'):
                                    all_colors_list = website_colors_data.get('all_colors', [])
                                    extracted_colors = [str(c).upper().strip() for c in all_colors_list if c]
                                    logger.info(f"✅ Extracted {len(extracted_colors)} colors directly from website_colors (all_colors)")
                                # Check for top_colors as fallback
                                elif website_colors_data.get('top_colors'):
                                    top_colors_list = website_colors_data.get('top_colors', [])
                                    extracted_colors = [c.get('color', '').upper().strip() for c in top_colors_list if c.get('color')]
                                    logger.info(f"✅ Extracted {len(extracted_colors)} colors directly from website_colors (top_colors)")
                        except Exception as e:
                            logger.error(f"Error extracting from website_colors: {e}", exc_info=True)
                    
                    # Log any errors
                    if brand_color_result.get('website_error'):
                        logger.warning(f"Website color extraction error: {brand_color_result['website_error']}")
                        print(f"⚠️ Website color error: {brand_color_result['website_error']}")
                    if brand_color_result.get('logo_error'):
                        logger.warning(f"Favicon color extraction error: {brand_color_result['logo_error']}")
                        print(f"⚠️ Favicon color error: {brand_color_result['logo_error']}")
                else:
                    logger.warning("⚠️ brand_color_result is None or not a dict")
                    print("⚠️ No color data from brand_color_analyzer")
                
                # If still no colors extracted, try direct website color extraction as last resort
                if not extracted_colors:
                    logger.warning("⚠️ No colors from brand_color_analyzer, trying direct website color extraction")
                    try:
                        # Import and use colors.py directly as last resort
                        from colors import analyze_website_theme
                        logger.info("Attempting direct website color extraction using colors.py")
                        direct_color_data = analyze_website_theme(url, timeout=20, max_colors=15)
                        if direct_color_data and direct_color_data.get('all_colors'):
                            extracted_colors = [str(c).upper().strip() for c in direct_color_data.get('all_colors', []) if c]
                            logger.info(f"✅ Extracted {len(extracted_colors)} colors directly from website using colors.py")
                            print(f"✅ Extracted {len(extracted_colors)} colors directly from website")
                        elif direct_color_data and direct_color_data.get('top_colors'):
                            extracted_colors = [c.get('color', '').upper().strip() for c in direct_color_data.get('top_colors', []) if c.get('color')]
                            logger.info(f"✅ Extracted {len(extracted_colors)} colors from top_colors using colors.py")
                            print(f"✅ Extracted {len(extracted_colors)} colors from top_colors")
                    except Exception as e:
                        logger.error(f"Error in direct color extraction: {e}", exc_info=True)
                        print(f"❌ Direct color extraction failed: {e}")
                
                # Log final extracted colors count
                if extracted_colors:
                    logger.info(f"✅ Final extracted colors count: {len(extracted_colors)}")
                    logger.info(f"✅ Final extracted colors: {extracted_colors}")  # Log all colors for debugging
                    print(f"✅ Final: {len(extracted_colors)} colors extracted: {extracted_colors}")
                else:
                    fallback_colors = company_info.get('theme_colors', [])
                    logger.warning(f"⚠️ No colors extracted after all attempts - will use fallback from company_info: {len(fallback_colors)} colors")
                    logger.info(f"⚠️ Fallback colors: {fallback_colors}")
                    print(f"⚠️ WARNING: Using AI-generated fallback colors: {len(fallback_colors)} colors")
                    print(f"⚠️ This should not happen - brand_color_analyzer should have extracted colors!")
                
                # Extract products information from product_info
                product = product_info.get('product', '')
                products = product_info.get('products', [])
                product_categories = product_info.get('product_categories', {})
                
                if products:
                    logger.info(f"📦 Extracted {len(products)} products across {len(product_categories)} categories")
                    print(f"📦 Extracted {len(products)} products in {len(product_categories)} categories")
                else:
                    logger.warning("⚠️ No products found in analysis")
                    print("⚠️ No products found")
                
                # Use only the validated address from company_info (already validated in summarize.py)
                # Do NOT fall back to raw scraped_address as it may be invalid
                validated_address = company_info.get('address', '')
                if validated_address:
                    logger.info(f"Using validated address from AI summary")
                else:
                    logger.info("No validated address available (may have been filtered out as invalid)")
                
                # Final check: ALWAYS prefer extracted_colors over fallback
                # Only use fallback if extracted_colors is completely empty
                if extracted_colors:
                    final_theme_colors = extracted_colors
                    logger.info(f"🎨 Using EXTRACTED colors: {len(final_theme_colors)} colors")
                    logger.info(f"🎨 Extracted colors list: {final_theme_colors}")
                    print(f"🎨 Using EXTRACTED colors: {len(final_theme_colors)} colors - {final_theme_colors[:10]}")
                else:
                    # Only use fallback if we truly have no extracted colors
                    fallback_colors = company_info.get('theme_colors', [])
                    final_theme_colors = fallback_colors
                    logger.warning(f"⚠️ No extracted colors - using FALLBACK: {len(fallback_colors)} colors from company_info")
                    logger.warning(f"⚠️ Fallback colors: {fallback_colors}")
                    print(f"⚠️ WARNING: Using FALLBACK colors: {len(fallback_colors)} colors")
                
                logger.info(f"🎨 Final theme_colors being set: {len(final_theme_colors)} colors")
                
                # Extract logo/favicon colors as hex strings for colors_from_logo field
                # This includes colors from AI-selected logo (or favicon/fallback)
                colors_from_logo = []
                if logo_colors_data and isinstance(logo_colors_data, list) and len(logo_colors_data) > 0:
                    for color in logo_colors_data:
                        if isinstance(color, dict) and color.get('hex'):
                            hex_color = color.get('hex', '').upper().strip()
                            if hex_color and hex_color not in colors_from_logo:
                                colors_from_logo.append(hex_color)
                    
                    logger.info(f"✅ Extracted {len(colors_from_logo)} colors for colors_from_logo field: {colors_from_logo}")
                    print(f"✅ Logo colors extracted: {len(colors_from_logo)} colors - {colors_from_logo}")
                else:
                    logger.warning(f"⚠️ No logo_colors_data available for colors_from_logo field")
                    logger.warning(f"   logo_colors_data: {logo_colors_data} (type: {type(logo_colors_data)})")
                    logger.warning(f"   logo_url_original: {logo_url_original}")
                    logger.warning(f"   favicon_url: {favicon_url}")
                    print(f"⚠️ WARNING: No logo colors available for colors_from_logo field")
                    
                    # Last resort: Try direct extraction with original URLs if available
                    # Only try if we haven't extracted any colors yet
                    if not colors_from_logo and (logo_url_original or favicon_url):
                        logger.info("🔄 Attempting direct logo color extraction as last resort...")
                        print(f"🔄 Attempting direct logo color extraction as last resort...")
                        try:
                            from brand_color_analyzer import extract_logo_colors
                            
                            # Try original logo URL first, then favicon
                            urls_to_try = []
                            if logo_url_original and logo_url_original.strip():
                                urls_to_try.append(logo_url_original)
                                logger.info(f"   Will try original logo URL: {logo_url_original}")
                            if favicon_url and favicon_url.strip():
                                urls_to_try.append(favicon_url)
                                logger.info(f"   Will try favicon URL: {favicon_url}")
                            
                            for url_to_try in urls_to_try:
                                try:
                                    logger.info(f"🔄 Trying direct extraction from: {url_to_try[:80]}...")
                                    print(f"🔄 Trying direct extraction from: {url_to_try[:60]}...")
                                    direct_colors = extract_logo_colors(url_to_try, num_colors=5)
                                    if direct_colors and len(direct_colors) > 0:
                                        logger.info(f"✅ Successfully extracted {len(direct_colors)} colors directly")
                                        print(f"✅ Successfully extracted {len(direct_colors)} colors directly from {url_to_try[:60]}...")
                                        
                                        # Extract hex colors
                                        for color in direct_colors:
                                            if isinstance(color, dict) and color.get('hex'):
                                                hex_color = color.get('hex', '').upper().strip()
                                                if hex_color and hex_color not in colors_from_logo:
                                                    colors_from_logo.append(hex_color)
                                        
                                        # Update logo_colors_data for consistency
                                        logo_colors_data = direct_colors
                                        break  # Success, stop trying other URLs
                                    else:
                                        logger.warning(f"⚠️ Direct extraction returned empty list for {url_to_try[:80]}...")
                                        logger.warning(f"   This usually means the image has too few pixels after filtering (transparent/white/black pixels removed)")
                                        print(f"⚠️ Direct extraction returned empty - image might be too small")
                                except Exception as direct_e:
                                    logger.error(f"⚠️ Direct extraction failed for {url_to_try[:80]}...: {direct_e}", exc_info=True)
                                    print(f"⚠️ Direct extraction failed: {str(direct_e)[:100]}")
                                    continue
                            
                            if colors_from_logo:
                                logger.info(f"✅ Final colors_from_logo after direct extraction: {len(colors_from_logo)} colors - {colors_from_logo}")
                                print(f"✅ Final logo colors: {len(colors_from_logo)} colors - {colors_from_logo}")
                            else:
                                logger.warning("⚠️ All direct extraction attempts failed - no logo colors extracted")
                                logger.warning("   Possible reasons:")
                                logger.warning("   1. Image URLs are not accessible (403, 404, timeout)")
                                logger.warning("   2. Image has too few pixels after filtering transparent/white/black pixels")
                                logger.warning("   3. Image format is not supported")
                                print(f"⚠️ WARNING: All direct extraction attempts failed - no logo colors extracted")
                        except Exception as e:
                            logger.error(f"❌ Error in direct logo color extraction fallback: {e}", exc_info=True)
                            print(f"❌ Error in direct logo color extraction fallback: {e}")
                
                result = {
                    'company_name': company_name,
                    'industry': company_info.get('industry', 'Unknown'),
                    'theme_colors': final_theme_colors,  # Combined colors from brand color extraction
                    'colors_from_logo': colors_from_logo,  # Colors extracted from logo/favicon (hex strings only)
                    'brand_colors': {
                        'logo_colors': logo_colors_data if logo_colors_data else [],
                        'website_colors': website_colors_data if website_colors_data else {},
                        'errors': brand_color_errors if brand_color_errors else {}
                    },
                    'fonts_typography': company_info.get('fonts_typography', []),
                    'company_info': company_info.get('company_info', 'No information available'),
                    'tone_analysis': company_info.get('tone_analysis', 'No tone analysis available'),
                    'keywords': company_info.get('keywords', []),
                    'target_group': company_info.get('target_group', 'Unknown'),
                    'element_fonts': element_fonts,
                    'matched_fonts': matched_fonts,  # Add matched Google Fonts with import URLs
                    'address': validated_address,  # Use only validated address (no fallback to raw scraped)
                    'address_details': scraped_address_details,
                    'logo_url': logo_url,  # Logo selected by AI
                    'favicon_url': favicon_url,
                    'products': products,
                    'product_categories': product_categories  # Add product categories
                }
                
                logger.debug(f"Formatted result keys: {list(result.keys())}")
                logger.info("Website analysis completed successfully")
                return result
            
            except ImportError as e:
                return self._create_error_response(company_name, f"Missing required module: {str(e)}")
            except Exception as e:
                return self._create_error_response(company_name, f"Analysis failed: {str(e)}")
        
        def _create_error_response(self, company_name: str, error_message: str) -> Dict[str, Any]:
            """Create standardized error response."""
            return {
                'company_name': company_name,
                'theme_colors': [],
                'fonts_typography': [],
                'company_info': f"❌ {error_message}",
                'product': '',
                'products': [],
                'product_categories': {}
            }
        
        def display_results(self, analysis_result: Dict[str, Any]) -> None:
            """Display formatted analysis results."""
            if not analysis_result:
                return
                
            print("=" * 60)
            
            # Company Name
            if 'company_name' in analysis_result:
                print(f"Company Name: {analysis_result['company_name']}")
            
            # Industry
            industry = analysis_result.get("industry", "" )
            if industry:
               print(f"\nIndustry: {industry}")

            # Colors - check multiple possible keys
            colors = []
            if 'theme_colors' in analysis_result:
                colors = analysis_result['theme_colors']
            elif 'design_analysis' in analysis_result:
                design_data = analysis_result.get('design_analysis', {})
                colors = design_data.get('colors', [])
            
            if colors:
                color_str = ', '.join(colors[:8])  # Limit to first 8 colors
                print(f"\nTheme/Colors Used: {color_str}")
            
            # Keywords
            if 'keywords' in analysis_result and analysis_result['keywords']:
                keywords_str = ', '.join(analysis_result['keywords'])
                print(f"\nKeywords: {keywords_str}")
                
            # Fonts - check multiple possible keys
            fonts = []
            if 'fonts_typography' in analysis_result:
                fonts = analysis_result['fonts_typography']
            elif 'design_analysis' in analysis_result:
                design_data = analysis_result.get('design_analysis', {})
                fonts = design_data.get('fonts', [])
            
            # Display general fonts if available
            if fonts:
                print("\nFonts/Typography:")
                print(f"General Fonts: {', '.join(fonts[:6])}")  # Limit to first 6 fonts
            
            # Display element-specific fonts if available
            element_fonts = analysis_result.get('element_fonts', {})
            if element_fonts:
                print("\nElement-Specific Fonts:")
                for element, fonts in element_fonts.items():
                    if fonts:  # Only show if there are fonts for this element
                        print(f"{element.upper()} tags: {', '.join(fonts[:3])}")  # Limit to first 3 fonts per element
            
            # Display matched Google Fonts with complete details
            matched_fonts = analysis_result.get('matched_fonts', {})
            if matched_fonts:
                print("\nMatched Google Fonts (Complete Details):")
                for font_name, font_info in matched_fonts.items():
                    family = font_info.get('family', font_name)
                    category = font_info.get('category', '')
                    variant = font_info.get('variant', '')
                    file_url = font_info.get('file', '')
                    import_url = font_info.get('import_url', '')
                    
                    print(f"\n  • {family}")
                    if category:
                        print(f"    Category: {category}")
                    if variant:
                        print(f"    Variant: {variant}")
                    if file_url:
                        print(f"    File: {file_url}")
                    if import_url:
                        print(f"    Import URL: {import_url}")
            
            # Company Info (AI Summary) - check multiple possible keys with safe access
            company_info = ''
            if isinstance(analysis_result, dict):
                company_info = analysis_result.get('company_info', '')
                if not company_info:
                    company_info = analysis_result.get('ai_summary', '')
            
            if company_info and not str(company_info).startswith('❌'):
                print(f"\nOur company information is: {company_info}")
            else:
                print("\nCompany information: Not available")
            
            target_group = analysis_result.get('target_group', '')
            if target_group:
                print(f"\nOur company's target group is: {target_group}")
            
            # Display Products
            product = analysis_result.get('product', '')
            products = analysis_result.get('products', [])
            product_categories = analysis_result.get('product_categories', {})
            
            if product:
                print(f"\nMain Product/Service: {product}")
            
            # Display product categories if available
            if product_categories and isinstance(product_categories, dict):
                print(f"\nProduct Categories:")
                for category, items in product_categories.items():
                    print(f"\n  {category}:")
                    for idx, item in enumerate(items, 1):
                        print(f"    {idx}. {item}")
            elif products and isinstance(products, list):
                # Fallback to flat list if no categories
                print(f"\nAll Products/Services:")
                for idx, prod in enumerate(products, 1):
                    print(f"  {idx}. {prod}")
            
            # Display Address - only if not already displayed
            if 'address_printed' not in locals():
                print("\nAddress:")
                address = analysis_result.get('address', '')
                if address and address.strip():
                    print(address)
                else:
                    print("Not able to scrape or data is not present")
                address_printed = True
            
            # Display Logo URL - only if not already displayed
            if 'logo_printed' not in locals():
                print("\nLogo URL:")
                logo_url = analysis_result.get('logo_url', '')
                if logo_url and logo_url.strip():
                    print(logo_url)
                else:
                    print("Not able to scrape or data is not present")
                logo_printed = True
            
            # Display Favicon URL - only if not already displayed
            if 'favicon_printed' not in locals():
                print("\nFavicon URL:")
                favicon_url = analysis_result.get('favicon_url', '')
                if favicon_url and favicon_url.strip():
                    print(favicon_url)
                else:
                    print("Not able to scrape or data is not present")
                favicon_printed = True
            
            print("=" * 60)
        


def get_user_input() -> str:
        """Get URL from user input."""
        # Get URL only
        while True:
            url = input("Enter website URL: ").strip()
            if url:
                return url
            print("Please enter a valid URL")


def main():
        """Main function for command-line usage."""
        try:
            # Create analyzer
            analyzer = WebsiteAnalyzer()
            
            # Check if arguments provided via command line
            if len(sys.argv) >= 2:
                # URL provided via command line
                url = sys.argv[1]
            else:
                # Interactive mode - ask for URL only
                url = get_user_input()
            
            # If input looks like a URL (contains a dot), treat as URL
            if "." not in url:
                print("❌ Please provide a website URL. Company-name search is disabled.")
                return

            company_name = analyzer.extract_company_name_from_url(url)
            analysis_result = analyzer.analyze_website(url, company_name)
            
            
            # Display results
            analyzer.display_results(analysis_result)
            
        except KeyboardInterrupt:
            print(f"\n⏹️ Analysis cancelled by user")
        except Exception as e:
            print(f"\n❌ Unexpected error: {str(e)}")


if __name__ == "__main__":
        logger.info("=== Starting website_analyzer.py as main script ===")
        start_time = time.time()
        try:
            main()
            logger.info(f"Script completed in {time.time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Script failed with error: {e}", exc_info=True)
            raise





