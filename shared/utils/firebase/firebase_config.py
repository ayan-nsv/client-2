import uuid
import gc, tempfile
import os as _os
import firebase_admin
from firebase_admin import auth, credentials
from google.cloud import storage, firestore

from shared.utils.error import error
from shared.utils.constants import constants
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

_storage_client = None
_db = None

_storage_client = None
_db_client = None


def init_firebase_admin() -> None:
    """
    Initialize the default Firebase Admin app so auth.verify_id_token works.

    Must run once at application startup. Without it, every token check raises
    "The default Firebase app does not exist.", which the auth dependencies
    surface to clients as the generic "Invalid or expired token".

    Credentials are resolved in order:
      1. FIREBASE_CREDENTIALS_PATH / GOOGLE_APPLICATION_CREDENTIALS, if it
         points to a real service-account *file*.
      2. Application Default Credentials (e.g. gcloud ADC).
    """
    if firebase_admin._apps:
        return

    options = {}
    if constants.FIREBASE_STORAGE_BUCKET:
        options["storageBucket"] = constants.FIREBASE_STORAGE_BUCKET

    cred_path = (
        _os.getenv("FIREBASE_CREDENTIALS_PATH")
        or _os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    # isfile guards the common Docker gotcha where a missing bind-mount source
    # gets auto-created as an empty *directory* at the target path.
    if cred_path and _os.path.isfile(cred_path):
        cred = credentials.Certificate(cred_path)
        logger.info("Initializing Firebase Admin from service account file: %s", cred_path)
    else:
        if cred_path:
            logger.warning(
                "Firebase credentials path %r is not a file; falling back to "
                "Application Default Credentials.",
                cred_path,
            )
        cred = credentials.ApplicationDefault()
        logger.info("Initializing Firebase Admin with Application Default Credentials")

    firebase_admin.initialize_app(cred, options)
    logger.info("Firebase Admin initialized successfully")

def get_firebase_client():
    """
    Returns singleton instances of storage and firestore clients
    to prevent memory leaks from multiple client instances
    """
    global _storage_client, _db_client
    
    project_id = constants.FIREBASE_PROJECT_ID
    
    if _storage_client is None:
        _storage_client = storage.Client(project=project_id)
    
    if _db_client is None:
        _db_client = firestore.Client(project=project_id)
    
    return _storage_client, _db_client

def get_firestore_client():
    """
    Returns singleton firestore client instance
    """
    global _db_client
    
    if _db_client is None:
        project_id = constants.FIREBASE_PROJECT_ID
        _db_client = firestore.Client(project=project_id)
    
    return _db_client



def create_disabled_firebase_user(email: str, password: str):
    """Create a disabled Firebase Auth user for admin-approved signup."""
    return auth.create_user(email=email, password=password, disabled=True)


def get_firebase_user_by_email(email: str):
    """Return Firebase user record for an email, or None if not found."""
    try:
        return auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        return None


def enable_firebase_user(firebase_uid: str) -> None:
    auth.update_user(firebase_uid, disabled=False)


def delete_firebase_user(firebase_uid: str) -> None:
    auth.delete_user(firebase_uid)


def _get_clients():
    """Lazily initialize Firebase clients"""
    global _storage_client, _db
    if _storage_client is None or _db is None:
        _storage_client, _db = get_firebase_client()
    return _storage_client, _db


async def upload_image(image_bytes: bytes, path: str, content_type: str = "image/png") -> str:
    try:
        storage_client, db = _get_clients()
        bucket_name = constants.FIREBASE_STORAGE_BUCKET
        if not bucket_name:
            raise Exception("No Bucket found!")
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(path)

        # Reduce peak memory by streaming from a temporary file with controlled chunk size
        # 1MB chunks limit RAM spikes across concurrent requests
        blob.chunk_size = 1 * 1024 * 1024

        tmp_file = None
        try:
            tmp_file = tempfile.NamedTemporaryFile(delete=False)
            tmp_file.write(image_bytes)
            tmp_file.flush()
            tmp_file.close()

            blob.upload_from_filename(tmp_file.name, content_type=content_type)
        finally:
            if tmp_file is not None:
                try:
                    _os.unlink(tmp_file.name)
                except Exception:
                    pass
        
        encoded_path = path.replace('/', '%2F')
        public_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_path}?alt=media"
        
       
        return public_url
        
    except Exception as e:

        raise Exception(f"Upload failed: {str(e)}")




async def upload_image_to_firebase(image_bytes: bytes, company_id: str, mime_type: str) -> str:
    """
    Upload image to Firebase Storage and return the public URL.
    """
    try:

        content_id = str(uuid.uuid4())
        # Sanity check image size; guard against corrupt/empty results
        if not image_bytes or len(image_bytes) < 1024:  # <1 KB is almost certainly invalid
            raise RuntimeError("Generated image appears invalid or truncated (size < 1KB)")

        # Create storage path with the generated content ID
        # Choose file extension based on mime type
        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
        }
        file_ext = ext_map.get(mime_type, ".png")
        path = f"content/{company_id}/{content_id}{file_ext}"
        
        # Upload image to Firebase Storage (this function will handle cleanup)
        url = await upload_image(image_bytes, path, content_type=mime_type)
      

        # Clear image bytes from memory immediately after upload
        del image_bytes
        image_bytes = None
        gc.collect()

        return url

    except Exception as e:
        raise error.InternalServerError(f"Failed to upload image to Firebase: {str(e)}")
