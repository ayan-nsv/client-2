import os
from zoneinfo import ZoneInfo

eniro_base_url = os.getenv("ENIRO_API_BASE_URL", "https://api.eniro.com/api/v2.0").rstrip("/")
eniro_user = os.getenv("ENIRO_USERNAME")
eniro_pass = os.getenv("ENIRO_PASSWORD")

SPECIAL_BYPASS_KEY = os.getenv("SPECIAL_BYPASS_KEY")
STATIC_API_KEY = os.getenv("STATIC_API_KEY")
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
GUEST_USER_UID = "guest_user"  # Used for full admin bypass when X-Special-Key is sent
STATIC_ADMIN_UID = "static_admin"
ADMIN_SECRET_UID = "admin_secret_user"


_DEFAULT_APP_ORIGIN = "https://apps.holdflight.se"
SENDGRID_USER_STATUS_EMAIL_TEMPLATE_ID = ""
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "").strip()
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "").strip()
SENDGRID_POST_CALL_TEMPLATE_ID = os.environ.get("SENDGRID_POST_CALL_TEMPLATE_ID", "").strip()
SENDGRID_DAILY_SUMMARY_TEMPLATE_ID = os.environ.get("SENDGRID_DAILY_SUMMARY_TEMPLATE_ID", "").strip()
SENDGRID_STATUS_EMAIL_TEMPLATE_ID = os.environ.get("SENDGRID_STATUS_EMAIL_TEMPLATE_ID", "").strip()
SENDGRID_USER_STATUS_EMAIL_TEMPLATE_ID = os.environ.get("SENDGRID_USER_STATUS_EMAIL_TEMPLATE_ID", "").strip()
SENDGRID_USAGE_WARNING_TEMPLATE_ID = os.environ.get("SENDGRID_USAGE_WARNING_TEMPLATE_ID", "").strip()
SENDGRID_CONCURRENCY_ALERT_TEMPLATE_ID = os.environ.get("SENDGRID_CONCURRENCY_ALERT_TEMPLATE_ID", "").strip()
_DEFAULT_CONCURRENCY_ALERT_EMAIL_RECIPIENTS = "support@teamrobin.com"
CONCURRENCY_ALERT_EMAIL_RECIPIENTS = (
    os.environ.get("CONCURRENCY_ALERT_EMAIL_RECIPIENTS", "").strip()
    or _DEFAULT_CONCURRENCY_ALERT_EMAIL_RECIPIENTS
)
SENDGRID_CHATBOT_LEAD_TEMPLATE_ID = os.environ.get("SENDGRID_CHATBOT_LEAD_TEMPLATE_ID", "").strip()


IMAGE_ANALYSIS_FIELDS = frozenset(
    {
        "composition_and_style",
        "environment_settings",
        "image_types_and_animation",
        "keywords_for_ai_image_generation",
        "lighting_and_color_tone",
        "subjects_and_people",
        "technology_elements",
        "theme_and_atmosphere",
        "image_urls",
        "analyzed_images_urls",
        "analyzed_images",
    }
)

STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")
FREE_MINUTES_BY_TIER = {
    "FREE": 20,
    "PAID": 100,
}


IMAGE_DOWNLOAD_TIMEOUT = 30  # seconds
MIN_IMAGE_SIZE = 1024  # 1 KB minimum
MAX_IMAGE_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
VALID_CHANNELS=frozenset({"instagram", "facebook", "linkedin"})
MIME_TYPE_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET")

FACEBOOK_GRAPH_URL = os.getenv("FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v19.0")
FACEBOOK_APP_ID = os.getenv("FB_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FB_APP_SECRET")
FACEBOOK_REDIRECT_URI = os.getenv("FB_REDIRECT_URI", "http://localhost:8000/facebook/callback")



INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET")
INSTAGRAM_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI"
)

SCOPES = (
    "instagram_business_basic,"
    "instagram_business_content_publish"
)

GRAPH_FB_BASE = "https://graph.facebook.com/v21.0"
GRAPH_IG_BASE = "https://graph.instagram.com/v21.0"


LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")
LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_API_BASE = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202511"
LINKEDIN_AUTH_URL = (
   f"https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code&client_id={LINKEDIN_CLIENT_ID}"
    f"&redirect_uri={LINKEDIN_REDIRECT_URI}"
    f"&scope=rw_organization_admin%20r_basicprofile%20w_organization_social"
)
 

LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")  # Must be set in environment!

MONTH_DAYS = {
        1: 31,
        2: 28,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }


VAPI_API_KEY = os.getenv("VAPI_API_KEY")
ELEVEN_LAB_BASEURL = (os.getenv("ELEVEN_LAB_BASEURL") or "https://api.elevenlabs.io/v1").strip().rstrip("/")

ACCOUNT_PENDING_APPROVAL_CODE = "ACCOUNT_PENDING_APPROVAL"
ACCOUNT_PENDING_APPROVAL_MESSAGE = (
    "Your account is pending admin approval. You will be notified once approved."
)
ACCOUNT_PENDING_CREATE_COMPANY_MESSAGE = (
    "Your account is pending admin approval. You cannot create another company yet."
)
SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID = os.environ.get(
    "SENDGRID_ONBOARDING_ADMIN_EMAIL_TEMPLATE_ID", ""
).strip()
_DEFAULT_ONBOARDING_ADMIN_EMAIL_RECIPIENTS = "robin@holdflight.se,magnus@holdflight.se"
ONBOARDING_ADMIN_EMAIL_RECIPIENTS = (
    os.environ.get("ONBOARDING_ADMIN_EMAIL_RECIPIENTS", "").strip()
    or _DEFAULT_ONBOARDING_ADMIN_EMAIL_RECIPIENTS
)