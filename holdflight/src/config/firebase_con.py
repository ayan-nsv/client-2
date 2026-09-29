# Firebase integration

import os
import firebase_admin
from firebase_admin import credentials, storage
from dotenv import load_dotenv

# firebase_con.py lives at holdflight/src/config/ — go up 3 levels to project root
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_BASE_DIR)))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))


def _configured_storage_bucket() -> str:
    bucket = os.environ.get(
        'FIREBASE_STORAGE_BUCKET',
        'marketing-planner-c8f02.firebasestorage.app',
    ).strip()
    if bucket.startswith("gs://"):
        bucket = bucket[5:]

    # Newer Firebase projects use firebasestorage.app buckets. If an old
    # appspot.com value is still present in local env, prefer the matching
    # Firebase Storage bucket so uploads do not fail with bucket-not-found.
    if bucket.endswith(".appspot.com"):
        project_id = bucket[:-len(".appspot.com")]
        return f"{project_id}.firebasestorage.app"
    return bucket


def init_firebase():
    if not firebase_admin._apps:
        storage_bucket = _configured_storage_bucket()

        cred_path = os.environ.get('FIREBASE_CREDENTIALS_PATH')
        if not cred_path or not os.path.exists(cred_path):
            # Fallback: look for service account file in project root
            fallback = os.path.join(_PROJECT_ROOT, "firebase-service-account.json")
            if os.path.exists(fallback):
                cred_path = fallback

        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
        else:
            cred = credentials.ApplicationDefault()

        firebase_admin.initialize_app(cred, {"storageBucket": storage_bucket})

def get_bucket():
    init_firebase()
    return storage.bucket(_configured_storage_bucket())




