import os
import uuid as uuid_lib
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.repository.user_repo import UserRepository
from core.tables import user_tables
from shared.database.postgres import serialization
from shared.utils.auth import auth
from shared.utils.error import error, error_handler
from core.repository.company_repo import CompanyRepository
from shared.utils.constants import constants
from shared.utils.firebase import firebase_config
from core.workers import tasks
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema


logger = setup_logger("marketing-app")

class EmailHelperServiceForUser:
    def _app_origin() -> str:
        raw = (os.getenv("FRONTEND_URL") or constants._DEFAULT_APP_ORIGIN).strip().rstrip("/")
        if raw and not raw.startswith(("http://", "https://")):
            raw = f"https://{raw}"
        return raw or constants._DEFAULT_APP_ORIGIN

    def _enqueue_user_status_email(recipient_email: str, dynamic_data: dict) -> None:
        """Best-effort enqueue after the domain change has already committed."""
        if not recipient_email:
            logger.warning("user_status_email_skipped reason=missing_recipient")
            return
        if not constants.SENDGRID_USER_STATUS_EMAIL_TEMPLATE_ID:
            logger.error(
                "user_status_email_skipped reason=missing_template_id recipient=%s",
                recipient_email,
            )
            return
        try:
            tasks.send_email_task.delay(
                recipient_email=recipient_email,
                template_id=constants.SENDGRID_USER_STATUS_EMAIL_TEMPLATE_ID,
                dynamic_data=dynamic_data,
            )
        except Exception as e:
           logger.error(f"Error sending user status email: {e}")



class UserService:

    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)
        self.company_repo = CompanyRepository(db)

    def _is_bypass_caller(self, user) -> bool:
        return (user or {}).get("uid") in (
            constants.GUEST_USER_UID,
            constants.STATIC_ADMIN_UID,
        ) or auth.has_privileged_access(user)

    def _parse_user_uuid(self, value):
        """users.uuid is a native UUID column, so reject malformed input up front."""
        try:
            return uuid_lib.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            raise error.BadRequest("Invalid user UUID")

    def _require_admin_caller(self, user):
        """Return the calling user record, or None for bypass principals."""
        if self._is_bypass_caller(user):
            return None

        caller = self.repo.get_user_by_firebase_id(user["uid"])
        if not caller:
            raise error.NotFound("User not found")
        if not caller.is_admin:
            raise error.PermissionDenied(
                "You are not authorized to access this resource"
            )
        return caller
    
    def _require_platform_admin(self, user: dict) -> None:
        if user.get("uid") in (constants.GUEST_USER_UID, constants.STATIC_ADMIN_UID):
            return
        caller = self.db.query(user_tables.User).filter(user_tables.User.firebase_uid == user["uid"]).first()
        if not caller:
            raise error.NotFound(message="User not found")
        if not caller.is_admin:
            raise error.NotFound(message="You are not authorized to access this resource")


    def create_user(self, data, user):
        try:
            if not user:
                raise error.Unauthorized("Unauthorized")

            ## check if the user presents in the database
            return self.repo.create_user(data)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_user: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    def get_users(self):
        try:
            users = self.repo.get_users()
            user_ids = [u.id for u in users]
            companies_by_user: dict[int, list[dict]] = {uid: [] for uid in user_ids}
            if user_ids:
                memberships = self.repo.get_companies_of_multiple_users(user_ids)
                for row in memberships:
                    companies_by_user.setdefault(row.user_id, []).append({
                        "company_uuid": str(row.uuid),
                        "company_name": row.company_name or "",
                    })

            result = []
            for u in users:
                user_dict = serialization.sqlalchemy_to_dict(u)
                user_dict["companies"] = companies_by_user.get(u.id, [])
                result.append(user_dict)
            logger.info(f"Users fetched successfully: {result}")
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_user(self, user_uuid, user):
        try:
            user_uuid = self._parse_user_uuid(user_uuid)

            if not self._is_bypass_caller(user):
                caller = self.repo.get_user_by_firebase_id(user["uid"])
                if not caller:
                    raise error.NotFound("User not found")
                if not caller.is_admin and str(caller.uuid) != str(user_uuid):
                    raise error.PermissionDenied(
                        "You are not authorized to access this resource"
                    )

            user_record = self.repo.get_user(user_uuid)
            if not user_record:
                raise error.NotFound("User not found")
            return serialization.sqlalchemy_to_dict(user_record)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_user: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_user_role(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(
                company_uuid,
                user["uid"],
                self.db,
            )

            caller = self.repo.get_user_by_firebase_id(user["uid"])
            if not caller:
                return None

            record = self.repo.get_user_role(caller.id, company_id_int)
            if record is None:
                return None
            record = dict(record._mapping)
            record["company_id"] = company_uuid
            return record
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user role: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_user_role: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def update_user_company_role(self, data, user):
        try:
            company_id_int = auth.check_user_company_access(
                data.company_id,
                user["uid"],
                self.db,
            )
            target_user = self.repo.get_user(self._parse_user_uuid(data.user_uuid))
            if not target_user:
                raise error.BadRequest("Target user not found")
            role_record = self.repo.get_role(data.role)
            if not role_record:
                raise error.BadRequest(f"Unknown role: {data.role}")
            return self.repo.update_user_company_role(company_id_int, target_user.id, role_record.id)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating user company role: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_user_company_role: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
    
    def get_user_companies(self, firebase_id, user):
        caller_uid = user.get("uid")
        if not self._is_bypass_caller(user):
            caller = self.repo.get_user_by_firebase_id(caller_uid)
            if not caller:
                raise error.NotFound("User not found")
            if caller_uid != firebase_id and not caller.is_admin:
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )
        try:
            # Perform a Join to get all company UUIDs in one trip to the DB
            companies = self.repo.get_user_companies(firebase_id)

            if not companies:
                # Note: This triggers if the user doesn't exist OR has no companies
                return []

            # companies is a list of Row objects, convert to list of UUID strings
            return [c.uuid for c in companies]

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user companies: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_user_companies: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
            

        

    def add_company_users(self, data, user):
        try:
            self._require_admin_caller(user)

            company_id_int = self.company_repo.get_company_id_from_uuid(data.company_id)
            if company_id_int is None:
                raise error.NotFound("Company not found")
            users_data = data.company_user_payload

            company_ids_int = []
            user_ids_int = []
            role_ids = []

            for users in users_data:
                
                user_record = self.repo.get_user(self._parse_user_uuid(users.user_id))
                if not user_record:
                    raise error.NotFound(f"User {users.user_id} not found")

                existing = self.repo.get_company_user_record(company_id_int, user_record.id)
                if existing:
                    raise error.AlreadyExists(
                        f"User {users.user_id} is already assigned to this company"
                    )

                if not self.repo.get_role_by_id(users.role_id):
                    raise error.BadRequest(f"Unknown role_id: {users.role_id}")

                company_ids_int.append(company_id_int)
                user_ids_int.append(user_record.id)
                role_ids.append(users.role_id)
            return self.repo.add_company_users(company_ids_int, user_ids_int, role_ids)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding company users: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"add_company_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,

                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def remove_company_users(self, data, user):
        try:
            # Authorization
            self._require_admin_caller(user)

            company_id_int = self.company_repo.get_company_id_from_uuid(data.company_id)
            if company_id_int is None:
                raise error.NotFound("Company not found")

            company_users = []

            for user_id in data.users:
                try:
                    user_uuid = uuid_lib.UUID(user_id)
                except ValueError:
                    raise error.BadRequest("Invalid user UUID")

                user_record = self.repo.get_user(user_uuid)
                if not user_record:
                    raise error.NotFound("User not found")

                company_user = self.repo.get_company_user_record(
                    company_id_int,
                    user_record.id,
                )

                if not company_user:
                    raise error.NotFound("User is not assigned to this company")

                company_users.append(company_user)

            return self.repo.remove_company_users(company_users)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error removing company users: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"remove_company_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
            self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_company_users(self, company_uuid, user):
         # Authorization
        self._require_admin_caller(user)
        try:
            company_id_int = self.company_repo.get_company_id_from_uuid(company_uuid)
            if company_id_int is None:
                raise error.NotFound("Company not found")
            company_users = self.repo.get_company_users(company_id_int)
            return [
                {**serialization.sqlalchemy_to_dict(user_row), "role": role_name}
                for user_row, role_name in company_users
            ]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company users: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_company_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
    
    def update_user(self, data, user):
        try:
            if user.get("uid") != constants.GUEST_USER_UID and user.get("uid") != constants.STATIC_ADMIN_UID:
                caller = self.db.query(user_tables.User).filter(user_tables.User.firebase_uid == user["uid"]).first()
                if not caller:
                    raise error.NotFound(message="User not found")
                if not caller.is_admin:
                    raise error.Unauthorized(message="You are not authorized to access this resource")

            user_record = self.repo.get_user(self._parse_user_uuid(data.user_id))
            if not user_record:
                raise error.NotFound("User not found")

            if not self._is_bypass_caller(user):
                caller = self.repo.get_user_by_firebase_id(user["uid"])
                if not caller:
                    raise error.NotFound("User not found")
                if not caller.is_admin and caller.id != user_record.id:
                    raise error.PermissionDenied(
                        "You are not authorized to access this resource"
                    )

            payload = data.model_dump(exclude_unset=True)
            payload.pop("user_id", None)
            payload["updated_at"] = datetime.now()

            return self.repo.update_user(user_record, payload)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_user: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
    

    def request_user_signup(self, data):
        user = self.repo.get_user_by_email(data.email)

        if user:
            if user.is_active:
                raise error.EmailAlreadyInUseError(data.email)

            raise error.EmailPendingApprovalError(data.email)

        firebase_uid = None

        try:
            try:
                firebase_user = firebase_config.create_disabled_firebase_user(
                    data.email,
                    data.password,
                )
                firebase_uid = firebase_user.uid

            except auth.EmailAlreadyExistsError:
                firebase_user = firebase_config.get_firebase_user_by_email(data.email)

                if firebase_user and firebase_user.disabled:
                    firebase_uid = firebase_user.uid
                else:
                    raise error.EmailAlreadyRegisteredError(data.email)

            if not firebase_uid:
                raise error.InternalServerError(
                    "Firebase user created without uid"
                )

            user = self.repo.create_pending_user(
                data.email,
                firebase_uid,
            )

        except HTTPException:
            raise

        except Exception:
            if firebase_uid:
                try:
                    firebase_config.delete_firebase_user(firebase_uid)
                except Exception:
                    pass
            raise

        origin = EmailHelperServiceForUser._app_origin()

        EmailHelperServiceForUser._enqueue_user_status_email(
            data.email,
            {
                "email_subject": "We received your signup request!",
                "theme_color": "#3B82F6",
                "heading_text": "Thanks for signing up!",
                "body_html": (
                    "We have received your signup request for HoldFlight. "
                    "Our team is currently reviewing your application."
                ),
                "footer_instruction": "Have questions? Visit our help center:",
                "action_url": f"{origin}/",
                "button_text": "Go to Help Center",
            },
        )

        return user
    

    def get_pending_users(self, user):
        try:
        # only admins can get pending users
            self._require_admin_caller(user)

            return self.repo.get_pending_users()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting pending users: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_pending_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
        
    
    def approve_pending_users(self, user_id, user):
        # Authorization
        self._require_admin_caller(user)

        pending_user = self.repo.get_user(self._parse_user_uuid(user_id))

        if not pending_user:
            raise error.NotFound("User not found")

        firebase_uid = pending_user.firebase_uid

        if not firebase_uid:
            recovered = firebase_config.get_firebase_user_by_email(
                pending_user.email
            )

            if not recovered or not recovered.uid:
                raise error.BadRequest(
                    "User has no Firebase account linked. Ask them to sign up again."
                )

            firebase_uid = recovered.uid

        try:
            firebase_config.enable_firebase_user(firebase_uid)

        except auth.UserNotFoundError:
            raise error.NotFound("Firebase user not found")

        except Exception as e:
            raise error.InternalServerError(str(e))

        pending_user = self.repo.approve_pending_user(
            pending_user,
            firebase_uid,
        )

        origin = EmailHelperServiceForUser._app_origin()

        EmailHelperServiceForUser._enqueue_user_status_email(
            pending_user.email,
            {
                "email_subject": "Good news! Your HoldFlight account is approved",
                "theme_color": "#2ECC71",
                "heading_text": "Your HoldFlight account is approved!",
                "body_html": (
                    "Your account application has been reviewed and officially approved."
                ),
                "footer_instruction": "Log in to your dashboard below:",
                "action_url": f"{origin}/#/email-auth",
                "button_text": "Login now",
            },
        )

        return {
            "success": True,
            "message": f"User {user_id} approved successfully",
        }
        
    
    def reject_pending_users(self, user_id, user):
        # Authorization
        self._require_admin_caller(user)

        pending_user = self.repo.get_user(self._parse_user_uuid(user_id))

        if not pending_user:
            raise error.NotFound("User not found")

        recipient_email = pending_user.email

        firebase_uid = pending_user.firebase_uid

        if not firebase_uid:
            recovered = firebase_config.get_firebase_user_by_email(
                pending_user.email
            )

            if recovered:
                firebase_uid = recovered.uid

        if firebase_uid:
            try:
                firebase_config.delete_firebase_user(firebase_uid)

            except auth.UserNotFoundError:
                # Already deleted - ignore
                pass

            except Exception as e:
                raise error.InternalServerError(str(e))

        self.repo.delete_user(pending_user)

        origin = EmailHelperServiceForUser._app_origin()

        EmailHelperServiceForUser._enqueue_user_status_email(
            recipient_email,
            {
                "email_subject": "Update regarding your HoldFlight account application",
                "theme_color": "#E74C3C",
                "heading_text": "An update on your application",
                "body_html": (
                    "Thank you for your interest in joining HoldFlight. "
                    "Our team has carefully reviewed your application, "
                    "but unfortunately we are unable to approve your "
                    "account at this time.<br><br>"
                    "You can apply again whenever you're ready."
                ),
                "footer_instruction": "Click below to sign up again:",
                "action_url": f"{origin}/#/email-auth",
                "button_text": "Sign up",
            },
        )

        return {
            "success": True,
            "message": f"User {user_id} rejected successfully",
        }

    def get_user_id_from_firebase_uid(self, firebase_id):
        if auth.is_static_admin_uid(firebase_id):
            return None
    # Look up user by firebase_uid
        user = self.repo.get_user_by_firebase_id(firebase_id)
        if user:
            return user.id
        return None

    
    def get_pending_onboarding_users(self):
        try:
            pending_users = self.user_repo.get_pending_onboarding_users()

            result = []

            for pending_user in pending_users:
                user_dict = serialization.sqlalchemy_to_dict(pending_user)

                memberships = self.repo.get_user_companies(
                    pending_user.id
                )

                user_dict["companies"] = [
                    {
                        "company_uuid": str(row.uuid),
                        "company_name": row.company_name or "",
                    }
                    for row in memberships
                ]

                result.append(user_dict)

            return result

        except HTTPException:
            raise

        except Exception as e:
            logger.error(
                f"Error getting pending onboarding users: {e}"
            )

            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="critical",
                    message=f"get_pending_onboarding_users: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )

            raise error.InternalServerError(
                message="Internal server error"
            )


    def approve_pending_onboarding_user(self, user_id):
        try:
            pending_user = self.repo.get_user(user_id)

            if not pending_user:
                raise error.NotFound(message="User not found")

            if not pending_user.has_created_company:
                raise error.Unauthorized(
                    message="User has not created a company yet.",
                )

            if pending_user.is_fully_approved:
                return {
                    "success": True,
                    "message": f"User {user_id} is already approved",
                }

            recipient_email = pending_user.email

            self.user_repo.approve_user(pending_user)

            origin = EmailHelperServiceForUser._app_origin()

            EmailHelperServiceForUser._enqueue_user_status_email(
                recipient_email,
                {
                    "email_subject": (
                        "Good news! Your HoldFlight account is fully approved"
                    ),
                    "theme_color": "#2ECC71",
                    "heading_text": "You're all set to use HoldFlight!",
                    "body_html": (
                        "Your account has been reviewed and approved. "
                        "You now have full access to all HoldFlight features."
                    ),
                    "footer_instruction": (
                        "Log in to your dashboard below:"
                    ),
                    "action_url": f"{origin}/#/email-auth",
                    "button_text": "Go to dashboard",
                },
            )

            return {
                "success": True,
                "message": f"User {user_id} approved successfully",
            }

        except HTTPException:
            raise

        except Exception as e:
            logger.error(
                f"Error approving pending onboarding user: {e}"
            )

            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="critical",
                    message=(
                        f"approve_pending_onboarding_user: "
                        f"{str(e)[:100]}"
                    ),
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )