from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from firebase_admin import auth
from sqlalchemy.orm import Session
import traceback






# /new imports
from shared.utils.constants import constants

from core.repository.user_repo import UserRepository
from core.tables.user_tables import User
from core.repository.company_repo import CompanyRepository 
from shared.utils.error import error
from shared.database.postgres.database_config import get_db
from core.services.company_service import CompanyService


# /

security = HTTPBearer(auto_error=False, scheme_name="FirebaseBearer")
api_key_security = APIKeyHeader(
    name="X-API-KEY",
    auto_error=False,
    scheme_name="X-API-KEY",
    description="Static service key (STATIC_API_KEY env var)",
)
admin_secret_security = APIKeyHeader(
    name="X-ADMIN-SECRET",
    auto_error=False,
    scheme_name="X-ADMIN-SECRET",
    description="Admin secret (ADMIN_SECRET env var)",
)


def is_guest_uid(uid: str | None) -> bool:
    return uid == constants.GUEST_USER_UID

def is_static_admin_uid(uid: str | None) -> bool:
    return uid == constants.STATIC_ADMIN_UID

def is_admin_secret_user(user: dict | None) -> bool:
    return bool((user or {}).get("is_admin_secret"))

def is_privileged_uid(uid: str | None) -> bool:
    """True for global bypass principals."""
    return is_guest_uid(uid) or uid == constants.ADMIN_SECRET_UID

def has_privileged_access(user: dict | None) -> bool:
    """True when authenticated user payload is a bypass principal."""
    uid = (user or {}).get("uid")
    return is_privileged_uid(uid)


def require_admin_access(user: dict, db: Session) -> None:
    """Raise 403 unless user authenticated via X-ADMIN-SECRET or User.is_admin."""
    if is_admin_secret_user(user):
        return
    user_record = UserRepository(db).get_user_by_firebase_id(user.get("uid"))
    if not user_record or not user_record.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def get_billing_api_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    admin_secret: str = Depends(admin_secret_security),
 ):
    """
    Salesforce billing usage auth: Authorization Bearer <ADMIN_SECRET>
    or X-ADMIN-SECRET header (same value as ADMIN_SECRET env).
    """
    if constants.ADMIN_SECRET and admin_secret and admin_secret == constants.ADMIN_SECRET:
        return {
            "uid": constants.ADMIN_SECRET_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Admin Secret User",
            "is_admin_secret": True,
        }

    if not constants.ADMIN_SECRET:
        raise error.ServiceUnavailable(
            message="ADMIN_SECRET is not configured",
        )
    if credentials is None:
        raise error.Unauthorized(
            message="Missing Authorization header or X-ADMIN-SECRET",
        )
    if credentials.credentials != constants.ADMIN_SECRET:
        raise error.Unauthorized(
            message="Invalid or expired token",
        )
    return {
        "uid": constants.ADMIN_SECRET_UID,
        "role": "admin",
        "email": "admin@holdflight.se",
        "name": "Admin Secret User",
        "is_admin_secret": True,
    }


def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    admin_secret: str = Depends(admin_secret_security),
    db: Session = Depends(get_db),
 ):
    """
    Admin-only auth: X-ADMIN-SECRET or Firebase user with User.is_admin == True.
    Does not accept STATIC_API_KEY, X-Special-Key, or other bypass keys.
    """
    if constants.ADMIN_SECRET and admin_secret and admin_secret == constants.ADMIN_SECRET:
        return {
            "uid": constants.ADMIN_SECRET_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Admin Secret User",
            "is_admin_secret": True,
        }

    if credentials is None:
        raise error.Unauthorized(
            message="Missing Authorization header or X-ADMIN-SECRET",
        )

    try:
        user = auth.verify_id_token(credentials.credentials)
    except Exception as e:
        raise error.Unauthorized(
            message="Invalid or expired token",
        ) from e

    user_record = UserRepository(db).get_user_by_firebase_id(user.get("uid"))
    if not user_record or not user_record.is_admin:
        raise error.Forbidden(
            message="Admin access required",
        )

    user["is_db_admin"] = True
    return user


def get_static_or_token_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    api_key: str = Depends(api_key_security),
 ):
    """
    Category/service auth: X-API-KEY (STATIC_API_KEY) or any valid Firebase token.
    Does not accept X-Special-Key, X-ADMIN-SECRET, or is_admin checks.
    """
    if constants.STATIC_API_KEY and api_key and api_key == constants.STATIC_API_KEY:
        return {
            "uid": constants.STATIC_ADMIN_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Static Admin",
            "is_static_admin": True,
        }

    if credentials is None:
        raise error.Unauthorized(
            message="Missing Authorization header or X-API-KEY",
        )

    try:
        return auth.verify_id_token(credentials.credentials)
    except Exception as e:
        raise error.Unauthorized(
            message="Invalid or expired token",
        ) from e


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    api_key: str = Depends(api_key_security),
    admin_secret: str = Depends(admin_secret_security),
  ):

    # 1. Check for the legacy special bypass key
    special_key = request.headers.get("X-Special-Key")
    if special_key and special_key == constants.SPECIAL_BYPASS_KEY:
        return {
            "uid": constants.GUEST_USER_UID,
            "companyId": "guest_company",
            "role": "admin",
            "is_guest_admin": True,
            "email": "guest@example.com",
            "name": "Guest User"
        }

    # 2. Check for the new static API key
    if constants.STATIC_API_KEY and api_key and api_key == constants.STATIC_API_KEY:
        return {
            "uid": constants.STATIC_ADMIN_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Static Admin",
            "is_static_admin": True
        }

    # 3. Check for ADMIN_SECRET
    if constants.ADMIN_SECRET and admin_secret and admin_secret == constants.ADMIN_SECRET:
        return {
            "uid": constants.ADMIN_SECRET_UID,
            "role": "admin",
            "email": "admin@holdflight.se",
            "name": "Admin Secret User",
            "is_admin_secret": True
        }
    if not credentials:
        raise error.Unauthorized(
            message="Missing Authorization header",
        )

    token = credentials.credentials

    try:
        return auth.verify_id_token(token)
    except Exception as e:
        print("🔥 FIREBASE ERROR 🔥")
        traceback.print_exc()
        raise error.Unauthorized(
            message=str(e),   
        )


def check_user_company_access(
    company_uuid: str,
    firebase_uid: str,
    db: Session,
    *,
    require_full_approval: bool = True,
) -> int:
    """
    Check if user has access to company and return company integer ID.
    
    Args:
        company_uuid: Company UUID string
        firebase_uid: Firebase user ID or user UUID string
        db: Database session
        require_full_approval: When True, block users pending one-time onboarding approval.
        
    Returns:
        int: Company integer ID
        
    Raises:
        HTTPException: If company not found or user doesn't have access
    """
    # Get company integer ID
    company_id_int = CompanyRepository(db).get_company_id_from_uuid(company_uuid)
    if company_id_int is None:
        raise error.NotFound(
            message="Company not found",
        )

    # Service principal (X-API-KEY / STATIC_API_KEY) may access any company.
    # X-ADMIN-SECRET does not bypass here — use get_admin_user routes for platform admin APIs.
    if is_static_admin_uid(firebase_uid) or is_privileged_uid(firebase_uid):
        return company_id_int

    user_repo = UserRepository(db)

    if require_full_approval:
        CompanyService(db).ensure_user_fully_approved(firebase_uid)

    # Get user integer ID from Firebase UID
    user_record = user_repo.get_user_by_firebase_id(firebase_uid)
    if not user_record:
        raise error.Forbidden(
            message="User does not have access to this company",
        )

    if user_record.is_admin:
        return company_id_int

    # Check if user has access
    company_user_record = user_repo.check_user_company_access(
        user_record.id,
        company_id_int,
    )

    if not company_user_record:
        raise error.Forbidden(
            message="User does not have access to this company",
        )

    return company_id_int


