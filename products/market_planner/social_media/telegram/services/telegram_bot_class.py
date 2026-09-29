import os
# Disable gRPC fork support to prevent crashes with uvicorn --reload
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")
os.environ.setdefault("GRPC_POLL_STRATEGY", "poll")

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict



# Postgres imports
from sqlalchemy.orm import Session
from sqlalchemy import func
from products.market_planner.social_media.telegram.tables.telegram_tables import TelegramChat, TelegramPendingApproval, TelegramThemeSelection
from core.tables.company_tables import Company
from shared.database.postgres.database_config import get_session_local

BASE_DIR = os.path.dirname(os.path.abspath(__file__))



 
 
class TelegramMarketingBot:
    def __init__(self, bot_token, max_workers=50, cache_max_size=10000):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        # Thread pool for background operations (scalable, limits concurrent threads)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="telegram_bot")
        
        # In-memory cache with size limit (LRU cache for memory efficiency)
        # Using OrderedDict for LRU behavior
        self._approval_cache = OrderedDict()
        self._cache_max_size = cache_max_size
        self._cache_lock = threading.Lock()
        
        # Cache for chat list (to avoid loading all chats on every request)
        self._chats_cache = None
        self._chats_cache_timestamp = 0
        self._chats_cache_ttl = 300  # 5 minutes TTL
        self._chats_cache_lock = threading.Lock()
        
        # Shared HTTP session with connection pooling and retries (scalable)
        self._session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=100,  # Connection pool size
            pool_maxsize=100
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        
        pass

        # Start background collector thread
        threading.Thread(target=self._background_collect, daemon=True).start()
    
    def shutdown(self):
        """Cleanup resources (call when shutting down)"""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=True, timeout=30)
        if hasattr(self, '_session'):
            self._session.close()

    def _load_all_chats(self, db: Session = None):
        """Load all chats from Postgres.
        
        Args:
            db: SQLAlchemy session. If None, creates a temporary one.
        
        Returns:
            dict: chat_id -> chat_info mapping
        """
        close_db = False
        if db is None:
            try:
                
                db = get_session_local()()
                close_db = True
            except Exception as e:
                print(f"⚠️ Could not fallback to Postgres for chat load: {e}")
                return {}

        chats = {}
        try:
            tg_chats = db.query(TelegramChat).all()
            for chat in tg_chats:
                chats[chat.telegram_chat_id] = {
                    "company_id": chat.company.uuid if chat.company else None,
                    "company_name": chat.company.company_name if chat.company else None,
                    "first_name": chat.first_name,
                    "username": chat.username,
                    "connected_at": chat.connected_at.isoformat() if chat.connected_at else None
                }
        except Exception as e:
            print(f"⚠️ Failed to read Telegram chats from Postgres: {e}")
        finally:
            if close_db: db.close()
        return chats
    
    def _invalidate_chats_cache(self):
        """Invalidate the chats cache (call after updating chat data)"""
        with self._chats_cache_lock:
            self._chats_cache = None
            self._chats_cache_timestamp = 0

    def _upsert_chat_in_postgres(self, chat_id, company_id, chat_info, db: Session):
        """Helper to upsert a Telegram chat in Postgres."""
        try:
            # 1. Resolve Company ID (int) from UUID string
            company_obj = db.query(Company).filter(Company.uuid == company_id).first()
            if not company_obj:
                print(f"⚠️ Company {company_id} not found in Postgres, skipping PG sync")
                return

            # 2. Upsert TelegramChat
            tg_chat = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if not tg_chat:
                tg_chat = TelegramChat(
                    telegram_chat_id=chat_id,
                    company_id=company_obj.id,
                    first_name=chat_info.get("first_name"),
                    username=chat_info.get("username"),
                    connected_at=func.now()
                )
                db.add(tg_chat)
            else:
                # Update fields
                tg_chat.first_name = chat_info.get("first_name")
                tg_chat.username = chat_info.get("username")
                tg_chat.company_id = company_obj.id
            
            db.commit()
            print(f"✅ Synced chat {chat_id} to Postgres for company {company_id}")
        except Exception as e:
            print(f"⚠️ Postgres chat upsert failed: {e}")
            db.rollback()



    def _get_company_id_for_chat(self, chat_id, db: Session = None):
        """Get company UUID for a given chat ID."""
        close_db = False
        if db is None:
            try:
            
                db = get_session_local()()
                close_db = True
            except: return None

        try:
            chat = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if chat and chat.company:
                return chat.company.uuid
        except Exception as e:
            print(f"⚠️ Postgres company lookup failed for {chat_id}: {e}")
        finally:
            if close_db: db.close()
        return None
    
    def _get_chat_info(self, chat_id, db: Session = None):
        """Get chat info from Postgres.
        
        Args:
            chat_id: Telegram chat ID
            db: Optional SQL session
        """
        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return None, None

        try:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if chat_obj:
                info = {
                    "company_id": chat_obj.company.uuid if chat_obj.company else None,
                    "company_name": chat_obj.company.company_name if chat_obj.company else None,
                    "first_name": chat_obj.first_name,
                    "username": chat_obj.username,
                    "connected_at": chat_obj.connected_at.isoformat() if chat_obj.connected_at else None,
                }
                return info, info["company_id"]
        except Exception as e:
            print(f"⚠️ Postgres chat lookup failed: {e}")
        finally:
            if close_db: db.close()
            
        return None, None


    
    def register_chat_from_webhook(self, chat_id, chat_info, company_id=None, db: Session = None):
        """Register a chat from webhook update and save to Postgres.
        
        Args:
            chat_id: Telegram chat ID (string)
            chat_info: Dict with chat information (first_name, username, etc.)
            company_id: Optional company_id from /start command parameter
            db: Optional SQLAlchemy session
        
        Returns:
            tuple: (status, company_name)
        """
        try:
            if not company_id:
                print(f"⚠️ Skipping chat {chat_id} - no company_id provided")
                return "no_company_id", None
            
            close_db = False
            if db is None:
                try:
               
                    db = get_session_local()()
                    close_db = True
                except: return "error", None

            try:
                company_obj = db.query(Company).filter(Company.uuid == company_id).first()
                if not company_obj:
                    print(f"⚠️ Company {company_id} not found in Postgres")
                    return "error", None
                
                company_name = company_obj.company_name
                
                existing_info, found_company_id = self._get_chat_info(chat_id, db=db)
                is_new = existing_info is None
                
                # Update Postgres
                self._upsert_chat_in_postgres(chat_id, company_id, chat_info, db)
                
                display_name = company_name or company_id
                if is_new:
                    self._send_text_sync(chat_id, f"✅ Welcome! You've been registered with company: {display_name}")
                    return "new", display_name
                elif found_company_id != company_id:
                    self._send_text_sync(chat_id, f"✅ Your registration has been updated to company: {display_name}")
                    return "updated", display_name
                else:
                    self._send_text_sync(chat_id, f"✅ You are already registered with company: {display_name}")
                    return "already_registered", display_name
            finally:
                if close_db: db.close()
                
        except Exception as e:
            print(f"⚠️ Error registering chat: {e}")
            return "error", None
    
    def get_post_status(self, company_id, post_id, db: Session = None):
        """Get the approval status for a specific post_id and company_id."""
        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return None

        try:
            # 1. Resolve Company ID (int) from UUID string
            company_obj = db.query(Company).filter(Company.uuid == company_id).first()
            if not company_obj:
                return None

            # 2. Query Postgres
            approval = db.query(TelegramPendingApproval).filter(
                TelegramPendingApproval.post_id == post_id,
                TelegramPendingApproval.company_id == company_obj.id
            ).first()
            
            if approval:
                # Find the telegram_chat_id for the response
                chat = db.query(TelegramChat).filter(TelegramChat.id == approval.chat_id).first()
                tg_chat_id = chat.telegram_chat_id if chat else None
                
                return {
                    "status": approval.status,
                    "company_id": company_id,
                    "post_id": approval.post_id,
                    "chat_id": tg_chat_id,
                    "image_url": approval.image_url,
                    "caption": approval.caption,
                    "created_at": approval.created_at.isoformat() if approval.created_at else None,
                    "responded_at": approval.responded_at.isoformat() if approval.responded_at else None,
                    "message_id": approval.message_id,
                    "source": "postgres"
                }
        except Exception as e:
            print(f"⚠️ Postgres post status lookup failed: {e}")
        finally:
            if close_db: db.close()
        return None

    # ========= BACKGROUND CHAT ID COLLECTOR =========
    def _background_collect(self):
        print("🚀 Background chat collector running every 60s...")
        while True:
            self.collect_pilot_chat_ids()
            time.sleep(60)

    def collect_pilot_chat_ids(self):
        """Background task to collect chat IDs and register them in Postgres if /start is used."""
        try:
            resp = self._session.get(f"{self.base_url}/getUpdates", timeout=20)
            data = resp.json()

            for update in data.get("result", []):
                # Handle callback queries (button clicks)
                if "callback_query" in update:
                    # In background collector, we don't have a db session easily available,
                    # but _handle_callback_query will attempt to create one if needed.
                    try:
                        self._handle_callback_query(update["callback_query"])
                    except Exception as e:
                        print(f"⚠️ Error in _handle_callback_query: {e}")
                        continue

                if "message" not in update:
                    continue
                msg = update["message"]
                chat = msg["chat"]
                chat_id = str(chat["id"])
                text = msg.get("text", "").strip()

                if text.startswith("/start"):
                    parts = text.split(maxsplit=1)
                    company_id = parts[1].strip() if len(parts) == 2 and parts[1] else None
                    
                    if company_id:
                        chat_info = {
                            "first_name": chat.get("first_name", ""),
                            "username": chat.get("username", ""),
                        }
                        self.register_chat_from_webhook(chat_id, chat_info, company_id)

        except Exception as e:
            print(f"⚠️ Error in background collector: {e}")

    # ========= SEND IMAGE AND WAIT FOR APPROVAL =========
    def send_post_and_wait(self, chat_id, image_url, caption, wait_time=7200, post_id=None, company_id=None):
        """Send image and approval buttons. (Called by API background tasks)"""
        self._send_photo(chat_id, image_url, caption)
        approval_msg_id = self._send_approval_buttons(chat_id, post_id)
        
        # Track this as pending approval
        self._add_pending_approval(chat_id, image_url, caption, post_id, approval_msg_id)
        return "pending"

    # ========= PENDING APPROVALS TRACKING =========
    def add_pending_approval_immediately(self, chat_id, image_url, caption, post_id, company_id, db: Session = None):
        """Add a new pending approval immediately to Postgres."""
        if not company_id:
            return None

        key = f"{chat_id}_{post_id}" if post_id else chat_id
        self._update_cache(key, "pending")

        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return None

        try:
            # Find company int id
            company_obj = db.query(Company).filter(Company.uuid == company_id).first()
            if company_obj:
                # Find chat int id
                chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
                if chat_obj:
                    # Existing or new?
                    approval = db.query(TelegramPendingApproval).filter(
                        TelegramPendingApproval.post_id == post_id,
                        TelegramPendingApproval.company_id == company_obj.id,
                        TelegramPendingApproval.chat_id == chat_obj.id
                    ).first()
                    
                    if not approval:
                        approval = TelegramPendingApproval(
                            chat_id=chat_obj.id,
                            company_id=company_obj.id,
                            post_id=post_id,
                            image_url=image_url,
                            caption=caption,
                            status="pending",
                            created_at=func.now()
                        )
                        db.add(approval)
                    else:
                        # Update existing
                        approval.image_url = image_url
                        approval.caption = caption
                        approval.status = "pending"
                        approval.updated_at = func.now()
                    
                    db.commit()
                    print(f"✅ Saved pending approval to Postgres for {company_id}")
                    return f"{chat_id}_{post_id}"
        except Exception as e:
            print(f"⚠️ Postgres pending approval save failed: {e}")
            db.rollback()
        finally:
            if close_db: db.close()
        return None

    def _add_pending_approval(self, chat_id, image_url, caption, post_id, message_id, db: Session = None):
        """Add or update a pending approval with message_id in Postgres."""
        key = f"{chat_id}_{post_id}" if post_id else chat_id
        
        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return

        try:
            # Resolve company and chat
            chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if chat_obj and chat_obj.company:
                approval = db.query(TelegramPendingApproval).filter(
                    TelegramPendingApproval.post_id == post_id,
                    TelegramPendingApproval.company_id == chat_obj.company_id,
                    TelegramPendingApproval.chat_id == chat_obj.id
                ).first()
                
                if approval:
                    approval.message_id = message_id
                    db.commit()
                    print(f"✅ Updated pending approval with message_id in Postgres")
        except Exception as e:
            print(f"⚠️ Failed to update pending approval with message_id: {e}")
            db.rollback()
        finally:
            if close_db: db.close()

    def _update_cache(self, key, status):
        """Update cache with LRU eviction for memory efficiency"""
        with self._cache_lock:
            # Remove if exists (to move to end for LRU)
            if key in self._approval_cache:
                del self._approval_cache[key]
            # Add to end (most recently used)
            self._approval_cache[key] = status
            # Evict oldest if over limit
            if len(self._approval_cache) > self._cache_max_size:
                self._approval_cache.popitem(last=False)  # Remove oldest (first item)
    
    def _get_cache(self, key):
        """Get from cache with LRU update"""
        with self._cache_lock:
            if key in self._approval_cache:
                # Move to end (most recently used)
                status = self._approval_cache.pop(key)
                self._approval_cache[key] = status
                return status
            return None
    
    def _get_pending_approval(self, chat_id, theme_id, db: Session = None):
        """Get pending approval for a specific chat and theme from Postgres."""
        key = f"{chat_id}_{theme_id}" if theme_id else chat_id
        
        # 1. Check in-memory cache first (instant)
        cached_status = self._get_cache(key)
        if cached_status and cached_status != "pending":
            return {"status": cached_status, "chat_id": chat_id, "theme_id": theme_id}
        
        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return None

        try:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if chat_obj and chat_obj.company:
                approval = db.query(TelegramPendingApproval).filter(
                    TelegramPendingApproval.post_id == theme_id,
                    TelegramPendingApproval.company_id == chat_obj.company_id,
                    TelegramPendingApproval.chat_id == chat_obj.id
                ).first()
                
                if approval:
                    # Convert to dict format
                    result = {
                        "status": approval.status,
                        "chat_id": chat_id,
                        "post_id": approval.post_id,
                        "theme_id": approval.post_id,
                        "company_id": chat_obj.company.uuid,
                        "image_url": approval.image_url,
                        "caption": approval.caption,
                        "message_id": approval.message_id
                    }
                    self._update_cache(key, approval.status)
                    return result
        except Exception as e:
            print(f"⚠️ Postgres pending approval lookup failed: {e}")
        finally:
            if close_db: db.close()
            
        return None



    # ========= CALLBACK QUERY HANDLER =========
    def _handle_callback_query(self, callback_query, db: Session = None):
        """Handle button clicks (callback queries) - ULTRA FAST response using best practices"""
        query_id = None
        try:
            query_id = callback_query["id"]
            chat_id = str(callback_query["message"]["chat"]["id"])
            message_id = callback_query["message"]["message_id"]
            data = callback_query["data"]  # Format: "approve_theme123" or "reject_theme123"
            
            # Check if this is a theme selection callback first (before answering)
            if data.startswith("theme_select_"):
                # Handle theme selection (1 or 2) - it will answer callback internally
                self._handle_theme_selection(callback_query, data, db=db)
                return
            
            # CRITICAL: Answer callback query IMMEDIATELY with empty response (best practice)
            # This stops the loading spinner instantly, before any processing
            self._answer_callback_query_instant(query_id, "")
            
            # Parse the callback data for approval/rejection
            parts = data.split("_", 1)
            if len(parts) != 2:
                # Already answered, just return
                return
            
            action, theme_id = parts
            theme_id = theme_id if theme_id != "none" else None
            key = f"{chat_id}_{theme_id}" if theme_id else chat_id
            
            # STEP 1: Check cache FIRST (instant, no network) - prevents double processing
            cached_status = self._get_cache(key)
            if cached_status and cached_status != "pending":
                # Already processed - show alert (callback already answered)
                alert_msg = "✅ You already approved this post!" if cached_status == "approved" else \
                           "❌ You already rejected this post!" if cached_status == "rejected" else \
                           "⚠️ This approval request is no longer valid"
                self._answer_callback_query(query_id, alert_msg, show_alert=True)
                return
            
            # STEP 2: Get approval data (only if cache check passed)
            approval = self._get_pending_approval(chat_id, theme_id)
            
            # Check if approval doesn't exist
            if not approval:
                self._answer_callback_query(query_id, "⚠️ This approval request is no longer valid", show_alert=True)
                return
            
            current_status = approval.get("status")
            
            # Double-check status (in case it changed between cache check and Firestore read)
            if current_status != "pending":
                alert_msg = "✅ You already approved this post!" if current_status == "approved" else \
                           "❌ You already rejected this post!" if current_status == "rejected" else \
                           "⚠️ This approval request is no longer valid"
                self._answer_callback_query(query_id, alert_msg, show_alert=True)
                return
            
            # STEP 3: Determine status based on action
            if action == "approve":
                status = "approved"
                message = "🎉 Thank you! Your post will be published."
                if theme_id:
                    message += f" (Post ID: {theme_id})"
                button_text = "✅ Approved"
            elif action == "reject":
                status = "rejected"
                message = "🚫 Post rejected. It won't be published."
                if theme_id:
                    message += f" (Post ID: {theme_id})"
                button_text = "❌ Rejected"
            else:
                # Invalid action - already answered callback
                return
            
            # Get company_id from approval to avoid extra lookup
            company_id = approval.get("company_id") or self._get_company_id_for_chat(chat_id)
            
            # STEP 4: Update in-memory cache INSTANTLY (prevents double-clicks, no network call)
            self._update_cache(key, status)
            
            # STEP 5: Update button message SYNCHRONOUSLY (instant visual feedback)
            self._edit_message_after_click_sync(chat_id, message_id, button_text, theme_id)
            
            # STEP 6: Send confirmation message SYNCHRONOUSLY (user sees it immediately)
            self._send_text_sync(chat_id, message)
            
            # STEP 7: Persist to Postgres
            try:
                self._persist_approval_status(chat_id, theme_id, status, company_id, approval, key, db=db)
            except Exception as e:
                print(f"⚠️ Error persisting approval status: {e}")
                import traceback
                traceback.print_exc()
            
            print(f"✅ {status.capitalize()} by {chat_id} for theme_id {theme_id}")
            
        except Exception as e:
            print(f"⚠️ Error handling callback query: {e}")
            # Make sure to answer even on error
            if query_id:
                try:
                    self._answer_callback_query(query_id, "⚠️ An error occurred", show_alert=True)
                except:
                    pass
    
    def _handle_theme_selection(self, callback_query, data, db: Session = None):
        """Handle theme selection (1 or 2) callback."""
        query_id = callback_query.get("id")
        chat_id = str(callback_query["message"]["chat"]["id"])
        message_id = callback_query["message"]["message_id"]
        
        # Format: "theme_select_1_{post_id}_{company_id}" 
        # Example: "theme_select_1_tp_00037_1234567"
        # Note: post_id and company_id may contain underscores, so we need to parse carefully
        
        # Remove "theme_select_" prefix
        if not data.startswith("theme_select_"):
            self._answer_callback_query_instant(query_id, "")
            self._answer_callback_query(query_id, "❌ Invalid theme selection format", show_alert=True)
            return
        
        # Extract: "1_tp_00037_1234567" or "2_tp_00037_1234567"
        rest = data[len("theme_select_"):]  # "1_tp_00037_1234567"
        parts = rest.split("_")
        
        if len(parts) < 3:
            self._answer_callback_query_instant(query_id, "")
            self._answer_callback_query(query_id, "❌ Invalid theme selection data", show_alert=True)
            return
        
        # First part is selection (1 or 2)
        selection = parts[0]
        
        # Last part is company_id
        company_id = parts[-1]
        
        # Everything in between is post_id (may contain underscores)
        post_id = "_".join(parts[1:-1]) if len(parts) > 2 else parts[1]
        
        key = f"theme_select_{post_id}"  # Cache key for theme selection
        
        # STEP 1: Answer callback instantly (stops spinner immediately)
        self._answer_callback_query_instant(query_id, "")
        
        try:
            selection_data = None
            source = "postgres"

            if db:
                try:
                    company_obj = db.query(Company).filter(Company.uuid == company_id).first()
                    if company_obj:
                        selection_pg = db.query(TelegramThemeSelection).filter(
                            TelegramThemeSelection.post_id == post_id,
                            TelegramThemeSelection.company_id == company_obj.id
                        ).first()
                        if selection_pg:
                            # Convert Postgres object to a dict like Firestore returns
                            selection_data = {
                                "status": selection_pg.status,
                                "themes": (selection_pg.data or {}).get("themes", []),
                                "message_id": selection_pg.message_id,
                                "chat_id": chat_id, # Use current chat_id
                                "company_id": company_id,
                                "selected_theme": selection_pg.selected_theme,
                                "selected_theme_title": selection_pg.selected_theme_title
                            }
                            source = "postgres"
                except Exception as e:
                    print(f"⚠️ Postgres theme selection lookup failed: {e}")

            if not selection_data:
                self._answer_callback_query(query_id, "⚠️ This theme selection is no longer valid", show_alert=True)
                return
            
            # Use data from Postgres/Firestore
            if selection_data.get("status") != "pending":
                selected_num = selection_data.get("selected_theme")
                selected_title = selection_data.get("selected_theme_title", "Unknown")
                alert_msg = f"✅ You already selected Theme {selected_num}: {selected_title}"
                self._answer_callback_query(query_id, alert_msg, show_alert=True)
                return
            
            themes = selection_data.get("themes", [])
            
            # Check cache first - if we just processed this, don't process again
            cached_status = self._get_cache(key)
            if cached_status and cached_status.startswith("selected_"):
                # Already processed - just acknowledge and return (don't send duplicate message)
                self._answer_callback_query(query_id, "✅ You already selected a theme!", show_alert=True)
                return
            
            # Check if already selected in Firestore (but not in cache - means it was selected earlier)
            if selection_data.get("status") == "selected":
                # Update cache to prevent future duplicate processing
                cache_value = f"selected_{selection_data.get('selected_theme', selection)}"
                self._update_cache(key, cache_value)
                self._answer_callback_query(query_id, "✅ You already selected a theme!", show_alert=True)
                # Don't send message for old selections (only for fresh ones)
                return
            
            # Get theme title from themes list if available, otherwise use default
            theme_title = f"Theme {selection}"
            
            if themes and len(themes) >= int(selection):
                # Get selected theme (1-indexed, so subtract 1)
                selected_theme_obj = themes[int(selection) - 1]
                theme_title = selected_theme_obj.get("title", f"Theme {selection}")
            
            # STEP 2: Update cache instantly (prevents double-clicks) - store selected theme number
            cache_value = f"selected_{selection}"
            self._update_cache(key, cache_value)
            
            # STEP 3: Update message synchronously (instant visual feedback)
            message_text = callback_query["message"].get("text", "")
            updated_text = message_text + f"\n\n✅ Selected: Theme {selection} - {theme_title}"
            
            self._session.post(
                f"{self.base_url}/editMessageText",
                data={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": updated_text,
                    "reply_markup": json.dumps({"inline_keyboard": []})  # Remove buttons
                },
                timeout=1.5
            )
            
            # STEP 4: Update Postgres/Firestore
            # Synchronous persist
            result = self._persist_theme_selection(
                company_id,
                post_id,
                int(selection),
                theme_title,
                selection_data,
                db=db
            )
            
            if not result:
                self._answer_callback_query(query_id, "⚠️ Failed to save selection. Please try again.", show_alert=True)
                return
            
            pass
            
            # STEP 5: Send confirmation message synchronously (only after successful save AND verification)
            try:
                self._send_text_sync(chat_id, f"✅ Thank you for selecting Theme {selection}: {theme_title}")
                print(f"✅ Sent thank you message to {chat_id}")
            except Exception as msg_error:
                print(f"⚠️ Error sending thank you message: {msg_error}")
                # Don't fail the whole operation if message send fails
            
        except Exception as e:
            print(f"⚠️ Error handling theme selection: {e}")
            import traceback
            traceback.print_exc()
            try:
                self._answer_callback_query(query_id, "⚠️ An error occurred", show_alert=True)
            except:
                pass
    
    def _persist_theme_selection(self, company_id, post_id, selected_theme, theme_title, selection_data, db: Session = None):
        """Persist theme selection to Postgres synchronously."""
        # 1. Update POSTGRES
        close_db = False
        if db is None:
            try:
                
                db = get_session_local()()
                close_db = True
            except Exception as e:
                print(f"⚠️ Could not create Postgres session for theme persistence: {e}")
                db = None

        if db:
            try:
                company_obj = db.query(Company).filter(Company.uuid == company_id).first()
                if company_obj:
                    selection = db.query(TelegramThemeSelection).filter(
                        TelegramThemeSelection.post_id == post_id,
                        TelegramThemeSelection.company_id == company_obj.id
                    ).first()
                    if selection:
                        selection.status = "selected"
                        selection.selected_theme = int(selected_theme)
                        selection.selected_theme_title = theme_title
                        selection.responded_at = func.now()
                        db.commit()
                        print(f"✅ Theme selection persisted to Postgres for {post_id}")
                        return True
            except Exception as e:
                print(f"⚠️ Postgres theme persistence failed: {e}")
                db.rollback()
            finally:
                if close_db: db.close()
        
        return False

    def _persist_approval_status(self, chat_id, theme_id, status, company_id, approval_data, key, db: Session = None):
        """Persist approval status to Postgres."""
        # 1. Update POSTGRES
        close_db = False
        if db is None:
            try:
            
                db = get_session_local()()
                close_db = True
            except Exception as e:
                print(f"⚠️ Could not create Postgres session for persistence: {e}")
                db = None

        if db:
            try:
                company_obj = db.query(Company).filter(Company.uuid == company_id).first()
                if company_obj:
                    # Resolve chat
                    chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
                    if chat_obj:
                        # Find the pending approval
                        approval = db.query(TelegramPendingApproval).filter(
                            TelegramPendingApproval.post_id == theme_id,
                            TelegramPendingApproval.company_id == company_obj.id,
                            TelegramPendingApproval.chat_id == chat_obj.id
                        ).first()
                        
                        if approval:
                            approval.status = status
                            approval.responded_at = func.now()
                            db.commit()
                            print(f"✅ Approval {status} persisted to Postgres for {theme_id}")
            except Exception as e:
                print(f"⚠️ Postgres approval persistence failed: {e}")
                db.rollback()
            finally:
                if close_db: db.close()
    def _save_approval(self, chat_id, image_url, caption, status, theme_id=None, db: Session = None):
        """Save a final approval to Postgres."""
        close_db = False
        if db is None:
            try:
                
                db = get_session_local()()
                close_db = True
            except: return

        try:
            chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
            if chat_obj and chat_obj.company:
                # We could store this in a separate TelegramApproval table if it existed,
                # but currently we just update TelegramPendingApproval status.
                # If there's a need for a permanent log, it should be implemented here.
                pass
        except Exception as e:
            print(f"⚠️ Failed to save approval: {e}")
        finally:
            if close_db: db.close()

    # ========= TELEGRAM HELPERS =========
    def _send_text_sync(self, chat_id, text):
        """Send text message SYNCHRONOUSLY for immediate user feedback"""
        try:
            self._session.post(
                f"{self.base_url}/sendMessage",
                data={"chat_id": chat_id, "text": text},
                timeout=1.5  # Fast timeout for immediate delivery
            )
        except Exception as e:
            print(f"⚠️ Error sending text to {chat_id}: {e}")
            # If sync fails, try async as fallback
            self._send_text(chat_id, text)
    
    def _send_text(self, chat_id, text):
        """Send text message - optimized for speed (non-blocking, uses thread pool)"""
        def _send():
            try:
                self._session.post(
                    f"{self.base_url}/sendMessage",
                    data={"chat_id": chat_id, "text": text},
                    timeout=2  # Fast timeout for quick response
                )
            except Exception as e:
                print(f"⚠️ Error sending text to {chat_id}: {e}")
        
        # Use thread pool executor for scalability
        self._executor.submit(_send)

    def _send_photo(self, chat_id, image_url, caption):
        """Send photo - uses shared session with connection pooling"""
        self._session.post(
            f"{self.base_url}/sendPhoto",
            data={"chat_id": chat_id, "photo": image_url, "caption": caption},
            timeout=10
        )

    def _send_approval_buttons(self, chat_id, post_id):
        """Send approval message with Yes/No buttons."""
        post_key = post_id if post_id else "none"
        
        # Show post_id in message if available
        message_text = f"🕓 Please approve this post"
        if post_id:
            message_text += f" (Post ID: {post_id})"
        message_text += ":"
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Yes", "callback_data": f"approve_{post_key}"},
                    {"text": "❌ No", "callback_data": f"reject_{post_key}"}
                ]
            ]
        }
        
        data = {
            "chat_id": chat_id,
            "text": message_text,
            "reply_markup": json.dumps(keyboard)
        }
        
        response = self._session.post(f"{self.base_url}/sendMessage", data=data, timeout=5)
        result = response.json()
        
        if result.get("ok"):
            return result["result"]["message_id"]
        return None
    
    def add_theme_selection_immediately(self, chat_id, themes, theme_id, company_id, month=None, db: Session = None):
        """Add theme selection to Postgres immediately."""
        if db:
            try:
                # Resolve Company ID (int) from UUID string
                company_obj = db.query(Company).filter(Company.uuid == company_id).first()
                if company_obj:
                    # Resolve Chat ID (int)
                    chat_obj = db.query(TelegramChat).filter(TelegramChat.telegram_chat_id == chat_id).first()
                    if chat_obj:
                        # Existing?
                        selection = db.query(TelegramThemeSelection).filter(
                            TelegramThemeSelection.post_id == theme_id,
                            TelegramThemeSelection.company_id == company_obj.id
                        ).first()
                        
                        if not selection:
                            selection = TelegramThemeSelection(
                                chat_id=chat_obj.id,
                                company_id=company_obj.id,
                                post_id=theme_id,
                                data={"themes": themes, "month": month},
                                status="pending",
                                created_at=func.now()
                            )
                            db.add(selection)
                        else:
                            # Update existing
                            selection.data = {"themes": themes, "month": month}
                            selection.status = "pending"
                            selection.updated_at = func.now()
                        
                        db.commit()
                        print(f"✅ Saved theme selection to Postgres for {company_id}")
                        return theme_id
            except Exception as e:
                print(f"⚠️ Postgres theme selection update failed: {e}")
                db.rollback()
        return None
    
    def send_theme_selection(self, chat_id, themes, theme_id, company_id):
        """Send theme selection message with buttons 1 and 2.
        
        Args:
            chat_id: Telegram chat ID
            themes: List of theme dicts with 'title' and 'description'
            theme_id: Theme ID to associate with selection
            company_id: Company ID
            
        Returns:
            message_id if successful, None otherwise
        """
        if len(themes) < 2:
            print(f"⚠️ Need at least 2 themes, got {len(themes)}")
            return None
        
        # Build message text
        message_text = "📅 Here are the themes for the month:\n\n"
        
        for i, theme in enumerate(themes[:2], 1):  # Only show first 2 themes
            title = theme.get("title", f"Theme {i}")
            description = theme.get("description", "")
            message_text += f"🎨 Theme {i}: {title}\n"
            if description:
                message_text += f"   {description}\n"
            message_text += "\n"
        
        message_text += f"📌 THEME ID: #{theme_id}\n\n"
        message_text += "Please select a theme:"
        
        # Create buttons (1 and 2)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "1️⃣ Theme 1", "callback_data": f"theme_select_1_{theme_id}_{company_id}"},
                    {"text": "2️⃣ Theme 2", "callback_data": f"theme_select_2_{theme_id}_{company_id}"}
                ]
            ]
        }
        
        data = {
            "chat_id": chat_id,
            "text": message_text,
            "reply_markup": json.dumps(keyboard)
        }
        
        try:
            response = self._session.post(f"{self.base_url}/sendMessage", data=data, timeout=5)
            result = response.json()
            
            if result.get("ok"):
                message_id = result["result"]["message_id"]
                
                # Update theme selection with message_id
                self._update_theme_selection_message_id(company_id, theme_id, message_id)
                
                return message_id
            return None
        except Exception as e:
            print(f"⚠️ Error sending theme selection: {e}")
            return None
    
    def send_theme_selection_and_wait(self, chat_id, themes, theme_id, company_id, wait_time=7200):
        """
        Send theme selection message.
        
        NOTE: With webhooks enabled, this method just sends the message and returns.
        Status updates are handled by the webhook callback handler.
        Cloud Run doesn't support long-running background tasks, so polling is removed.
        Use /theme-selection-status endpoint to check status after sending.
        
        Args:
            chat_id: Telegram chat ID
            themes: List of theme dicts with 'title' and 'description'
            theme_id: Theme ID to associate with selection
            company_id: Company ID
            wait_time: Not used (kept for compatibility)
            
        Returns:
            None (webhook handles status updates)
        """
        # Send the theme selection message
        message_id = self.send_theme_selection(chat_id, themes, theme_id, company_id)
        
        if not message_id:
            return None
        
        print(f"✅ Theme selection sent to chat_id {chat_id} for theme_id {theme_id}. Status will be updated via webhook when user responds.")
        return None  # Return immediately - webhook handles status updates
    

    def get_theme_selection_status(self, company_id, theme_id, db: Session = None):
        """Get theme selection status from Postgres.
        
        Returns dict with status information or None if not found.
        """
        close_db = False
        if db is None:
            try:
             
                db = get_session_local()()
                close_db = True
            except: return None

        try:
            # 1. Resolve Company ID (int) from UUID string
            company_obj = db.query(Company).filter(Company.uuid == company_id).first()
            if company_obj:
                # 2. Query Postgres
                selection = db.query(TelegramThemeSelection).filter(
                    TelegramThemeSelection.post_id == theme_id,
                    TelegramThemeSelection.company_id == company_obj.id
                ).first()
                
                if selection:
                    # Find the telegram_chat_id
                    chat = db.query(TelegramChat).filter(TelegramChat.id == selection.chat_id).first()
                    tg_chat_id = chat.telegram_chat_id if chat else None
                    
                    return {
                        "company_id": company_id,
                        "theme_id": theme_id,
                        "status": selection.status,
                        "selected_theme": selection.selected_theme,
                        "selected_theme_title": selection.selected_theme_title,
                        "chat_id": tg_chat_id,
                        "themes": (selection.data or {}).get("themes", []),
                        "created_at": selection.created_at.isoformat() if selection.created_at else None,
                        "responded_at": selection.responded_at.isoformat() if selection.responded_at else None,
                        "message_id": selection.message_id,
                        "month": (selection.data or {}).get("month"),
                        "source": "postgres"
                    }
        except Exception as e:
            print(f"⚠️ Postgres theme status lookup failed: {e}")
        finally:
            if close_db: db.close()
            
        return None

    def _update_theme_selection_message_id(self, company_id, post_id, message_id, db: Session = None):
        """Update theme selection with message_id in Postgres."""
        close_db = False
        if db is None:
            try:
               
                db = get_session_local()()
                close_db = True
            except: return

        try:
            company_obj = db.query(Company).filter(Company.uuid == company_id).first()
            if company_obj:
                selection = db.query(TelegramThemeSelection).filter(
                    TelegramThemeSelection.post_id == post_id,
                    TelegramThemeSelection.company_id == company_obj.id
                ).first()
                if selection:
                    selection.message_id = message_id
                    db.commit()
                    print(f"✅ Updated theme selection message_id in Postgres")
        except Exception as e:
            print(f"⚠️ Failed to update theme selection message_id: {e}")
            db.rollback()
        finally:
            if close_db: db.close()
    


    def _answer_callback_query_instant(self, query_id, text=""):
        """Answer callback query INSTANTLY with minimal data (best practice for fastest response)"""
        try:
            # Use minimal payload and very short timeout for absolute fastest response
            # Empty text stops spinner immediately without showing notification
            self._session.post(
                f"{self.base_url}/answerCallbackQuery",
                data={"callback_query_id": query_id, "text": text},
                timeout=0.5  # Ultra-fast timeout
            )
        except Exception as e:
            print(f"⚠️ Error answering callback query instantly: {e}")
    
    def _answer_callback_query(self, query_id, text, show_alert=False):
        """Answer a callback query (button click) - for alerts and notifications"""
        try:
            self._session.post(
                f"{self.base_url}/answerCallbackQuery",
                data={
                    "callback_query_id": query_id,
                    "text": text,
                    "show_alert": show_alert
                },
                timeout=1  # Fast timeout
            )
        except Exception as e:
            print(f"⚠️ Error answering callback query: {e}")

    def _edit_message_after_click_sync(self, chat_id, message_id, button_text, theme_id=None):
        """Update message text and remove buttons SYNCHRONOUSLY for instant visual feedback"""
        # Get the original message to preserve post_id info
        message_text = "🕓 Please approve this post"
        if theme_id:
            message_text += f" (Post ID: {theme_id})"
        message_text += f":\n\n{button_text}"
        
        # Update both text and remove buttons - SYNCHRONOUS for instant feedback
        try:
            self._session.post(
                f"{self.base_url}/editMessageText",
                data={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": message_text,
                    "reply_markup": json.dumps({"inline_keyboard": []})  # Remove buttons
                },
                timeout=1.5  # Very fast timeout for instant visual feedback
            )
        except Exception as e:
            print(f"⚠️ Error editing message: {e}")
            # If sync edit fails, try async as fallback
            self._edit_message_after_click_async(chat_id, message_id, button_text, theme_id)
    
    def _edit_message_after_click_async(self, chat_id, message_id, button_text, theme_id=None):
        """Update message text and remove buttons asynchronously (fallback)"""
        message_text = "🕓 Please approve this post"
        if theme_id:
            message_text += f" (Post ID: {theme_id})"
        message_text += f":\n\n{button_text}"
        
        def _edit():
            try:
                self._session.post(
                    f"{self.base_url}/editMessageText",
                    data={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": message_text,
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    },
                    timeout=2
                )
            except Exception as e:
                print(f"⚠️ Error editing message: {e}")
        
        self._executor.submit(_edit)

    def _edit_message_reply_markup(self, chat_id, message_id):
        """Remove buttons from message after approval - uses shared session"""
        try:
            self._session.post(
                f"{self.base_url}/editMessageReplyMarkup",
                data={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": json.dumps({"inline_keyboard": []})
                },
                timeout=1.5
            )
        except Exception as e:
            print(f"⚠️ Error removing buttons: {e}")
