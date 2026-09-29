import os
import requests
import time
from urllib.parse import urlencode

from shared.utils.constants import constants

class LinkedInClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "Linkedin-Version": "202510",
        }

    def get_profile(self):
        r = requests.get(f"{constants.LINKEDIN_API}/userinfo", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def get_me(self):
        r = requests.get(f"{constants.LINKEDIN_API}/me", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def get_organizations(self):
        url = (
            f"{constants.LINKEDIN_API}/organizationalEntityAcls"
            "?q=roleAssignee&role=ADMINISTRATOR"
        )
        r = requests.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("elements", [])

    def get_organization(self, org_urn: str):
        org_id = org_urn.split(":")[-1]
        projection = "(localizedName,vanityName,name,logoV2(original~:playableStreams))"
        url = f"{constants.LINKEDIN_API}/organizations/{org_id}?projection={projection}"
        r = requests.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def upload_media_from_url(self, owner_urn: str, image_url: str) -> str:
        """
        Download an image from a public URL and upload it to LinkedIn.
        Returns the media URN (e.g. "urn:li:digitalmediaAsset:xxx").
        Used for UGC API (/v2/ugcPosts).
        """
        # Step 1: Register upload with LinkedIn
        register_payload = {
            "registerUploadRequest": {
                "owner": owner_urn,
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }
                ]
            }
        }
        resp = requests.post(
            f"{constants.LINKEDIN_API}/assets?action=registerUpload",
            json=register_payload,
            headers=self._headers()
        )
        if not resp.ok:
            print(f"❌ LinkedIn register upload failed: {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn = data["value"]["asset"]

        # Step 2: Download image from public URL
        img_resp = requests.get(image_url, timeout=30)
        img_resp.raise_for_status()
        image_bytes = img_resp.content

        # Step 3: Upload image bytes to LinkedIn
        upload_resp = requests.put(
            upload_url,
            data=image_bytes,
            headers={"Content-Type": img_resp.headers.get("Content-Type", "image/jpeg")}
        )
        if not upload_resp.ok:
            print(f"❌ LinkedIn image upload failed: {upload_resp.status_code}")
        upload_resp.raise_for_status()

        return asset_urn

    def upload_image_for_rest_posts(self, owner_urn: str, image_url: str, max_retries: int = 3) -> str:
        """
        Upload an image using LinkedIn REST Images API for use with /rest/posts.
        Returns an image URN (e.g. "urn:li:image:xxx") that can be used with REST Posts API.
        
        Args:
            owner_urn: The organization or person URN
            image_url: Public URL of the image to upload
            max_retries: Maximum number of retry attempts (default: 3)
        """
        # Step 1: Download image from public URL (no retry needed - external URL)
        img_resp = requests.get(image_url, timeout=30)
        img_resp.raise_for_status()
        image_bytes = img_resp.content
        content_type = img_resp.headers.get("Content-Type", "image/jpeg")

        # Step 2: Initialize upload with REST Images API (with retry)
        init_payload = {
            "initializeUploadRequest": {
                "owner": owner_urn
            }
        }
        headers = self._headers()
        
        init_data = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                init_resp = requests.post(
                    "https://api.linkedin.com/rest/images?action=initializeUpload",
                    json=init_payload,
                    headers=headers,
                    timeout=30
                )
                if init_resp.ok:
                    init_data = init_resp.json()
                    break
                else:
                    last_error = f"Status {init_resp.status_code}: {init_resp.text}"
                    print(f"⚠️ Initialize upload attempt {attempt + 1}/{max_retries} failed: {last_error}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        print(f"⏳ Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
            except Exception as e:
                last_error = str(e)
                print(f"⚠️ Initialize upload attempt {attempt + 1}/{max_retries} exception: {last_error}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⏳ Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
        
        if init_data is None:
            raise Exception(f"Failed to initialize image upload after {max_retries} attempts. Last error: {last_error}")
        
        upload_url = init_data["value"]["uploadUrl"]
        image_urn = init_data["value"]["image"]

        # Step 3: Upload image bytes to the upload URL (with retry)
        upload_headers = {"Content-Type": content_type}
        last_upload_error = None
        
        for attempt in range(max_retries):
            try:
                upload_resp = requests.put(
                    upload_url, 
                    data=image_bytes, 
                    headers=upload_headers,
                    timeout=60  # Longer timeout for file upload
                )
                if upload_resp.ok:
                    return image_urn
                else:
                    last_upload_error = f"Status {upload_resp.status_code}: {upload_resp.text}"
                    print(f"⚠️ Image upload attempt {attempt + 1}/{max_retries} failed: {last_upload_error}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"⏳ Retrying upload in {wait_time} seconds...")
                        time.sleep(wait_time)
            except Exception as e:
                last_upload_error = str(e)
                print(f"⚠️ Image upload attempt {attempt + 1}/{max_retries} exception: {last_upload_error}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⏳ Retrying upload in {wait_time} seconds...")
                    time.sleep(wait_time)
        
        raise Exception(f"Failed to upload image after {max_retries} attempts. Last error: {last_upload_error}")

    def create_post(self, author_urn: str, text: str, media: list[str] = []):
        """
        Create a LinkedIn post for a Page or Member using the UGC API.

        Flow:
        1. If media items are public URLs (http/https), download and upload them
           to LinkedIn to get media URNs like "urn:li:digitalmediaAsset:xxxx".
        2. If media items are already URNs, use them directly.
        3. Call /ugcPosts with the URNs in the "media" array.

        - If `media` is empty, creates a plain text post.
        - If `media` has URNs/URLs, they are attached as IMAGE media.
        """
        media_urns = []
        for item in media:
            if item.startswith("http://") or item.startswith("https://"):
                print(f"📤 Uploading media from URL: {item}")
                urn = self.upload_media_from_url(author_urn, item)
                print(f"✅ Got media URN: {urn}")
                media_urns.append(urn)
            else:
                media_urns.append(item)

        has_media = bool(media_urns)

        data = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE" if has_media else "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
            },
        }

        if has_media:
            data["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                {"status": "READY", "media": urn} for urn in media_urns
            ]
        r = requests.post(f"{constants.LINKEDIN_API}/ugcPosts", headers=self._headers(), json=data)
        if not r.ok:
            print(f"❌ LinkedIn API Error: {r.status_code}")
        r.raise_for_status()
        return r.json()

    def create_member_post(self, author_urn: str, text: str):
        url = "https://api.linkedin.com/rest/posts"
        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = self._headers()
        r = requests.post(url, headers=headers, json=payload)
        if not r.ok:
            print(f"❌ LinkedIn member post error: {r.status_code}")
        r.raise_for_status()
        if r.content:
            try:
                return r.json()
            except ValueError:
                return {"status_code": r.status_code, "raw": r.text}
        return {"status_code": r.status_code}

    def create_org_post(self, author_urn: str, text: str, media: list[str] = []):
        """
        Create a LinkedIn organization post using the new /rest/posts endpoint.
        This is the correct endpoint for organization posts with w_organization_social scope.
        
        Flow:
        1. If media items are public URLs (http/https), upload them using REST Images API
           to get image URNs like "urn:li:image:xxxx".
        2. If media items are already image URNs (urn:li:image:...), use them directly.
        3. Call /rest/posts with the image URN in the "content" field.
        
        - If `media` is empty, creates a plain text post.
        - If `media` has URLs/URNs, they are attached as IMAGE media.
        """
        image_urn = None
        
        if media:
            item = media[0]  # REST Posts API supports single image per post
            if item.startswith("http://") or item.startswith("https://"):
                print(f"📤 Uploading image from URL for REST Posts API: {item}")
                image_urn = self.upload_image_for_rest_posts(author_urn, item)
                print(f"✅ Got image URN: {image_urn}")
            elif item.startswith("urn:li:image:"):
                # Already an image URN, use it directly
                image_urn = item
                print(f"✅ Using provided image URN: {image_urn}")
            else:
                # Might be a digitalmediaAsset or other URN - not compatible with REST Posts
                raise ValueError(
                    f"Media URN '{item}' is not compatible with REST Posts API. "
                    "Please provide an image URL or an 'urn:li:image:...' URN."
                )

        url = "https://api.linkedin.com/rest/posts"
        payload = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        if image_urn:
            # For LinkedIn REST Posts API, attach image to content
            payload["content"] = {
                "media": {
                    "id": image_urn
                }
            }

        headers = self._headers()
        r = requests.post(url, headers=headers, json=payload)
        if not r.ok:
            print(f"❌ LinkedIn organization post error: {r.status_code}")
        r.raise_for_status()
        
        # Handle response - LinkedIn REST Posts API returns post ID in response body or Location header
        try:
            if r.content:
                return r.json()
        except ValueError:
            pass
        
        # If no JSON body, check Location header for post ID
        location = r.headers.get("Location", "")
        if location:
            # Location format: /posts/{post_urn} or similar
            post_urn = location.split("/")[-1]
            return {"id": post_urn}
        
        # Fallback: return empty response with status
        return {"id": None}
 

def exchange_code_for_token(code: str):
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": constants.LINKEDIN_REDIRECT_URI,
        "client_id": constants.LINKEDIN_CLIENT_ID,
        "client_secret": constants.LINKEDIN_CLIENT_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(constants.LINKEDIN_TOKEN_URL, data=urlencode(payload), headers=headers)
    if not r.ok:
        print("❌ Token exchange failed:", r.status_code)
        r.raise_for_status()
    data = r.json()
    return data.get("access_token"), data.get("expires_in", 0)


