import json, asyncio, requests
from typing import Optional, Union, List
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from core.repository.company_repo import CompanyRepository
from core.repository.user_repo import UserRepository
from shared.database.postgres import serialization
from shared.utils.error import error, error_handler
from shared.cache.redis import redis
from shared.utils.email.onboarding_email_utils import enqueue_onboarding_admin_approval_email

from shared.utils.constants import constants  
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema
from shared.utils.auth import auth
from core.tables import company_tables, user_tables
from core.schema import company_schema
logger = setup_logger("marketing-app")

class CompanyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)

    @staticmethod
    def fetch_eniro_company_data(eco_id: str) -> dict:
        """Fetch and map company data from Eniro API."""
        eniro_base_url = constants.eniro_base_url
        eniro_url = f"{eniro_base_url}/SE/get/{eco_id}?source=COMPANY"
        eniro_user = constants.eniro_user
        eniro_pass = constants.eniro_pass
        auth = (eniro_user, eniro_pass) if eniro_user and eniro_pass else None
        
        result = {}
        try:
            resp = requests.get(eniro_url, auth=auth, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # logger.info("Eniro API returned data for eco_id %s (companies=%s)", eco_id, len(data.get("companies", [])))
                eniro_companies = data.get("companies", [])
                if eniro_companies:
                    eniro_company = eniro_companies[0]
                    
                    # 1. Company Name
                    result["company_name"] = eniro_company.get("name")
                    
                    # 2. Address
                    addrs = eniro_company.get("addresses", [])
                    if addrs:
                        addr = addrs[0]
                        parts = [
                            f"{addr.get('streetName', '')} {addr.get('streetNumber', '')}".strip(),
                            f"{addr.get('postalCode', '')} {addr.get('postalArea', '')}".strip(),
                            addr.get('municipality', ''),
                            addr.get('region', '')
                        ]
                        result["address"] = ", ".join(filter(None, [p for p in parts if str(p).strip()]))

                    # 3. Handle data from 'products' array
                    products = eniro_company.get("products", [])
                    for product in products:
                        p_name = product.get("name")
                        if p_name == "company_description":
                            text_data = product.get("text")
                            result["company_info"] = text_data[0] if isinstance(text_data, list) and text_data else text_data
                        if p_name == "logo":
                            result["logo_url"] = product.get("image")
                        if p_name == "homepage":
                            result["url"] = product.get("url")
        except Exception as e:
            logger.warning(f"Failed to fetch Eniro data for eco_id {eco_id}: {e}")
            
        
        return result


    def get_companies(self, page: int, limit: int, user):
        try:
            total_count, companies, image_analyses = self.repo.get_companies(
                page,
                limit,
            )

            image_analysis_map = {
                analysis.company_id: analysis
                for analysis in image_analyses
            }

            companies_with_analysis = []

            for company in companies:
                company_dict = serialization.sqlalchemy_to_dict(company)

                image_analysis = image_analysis_map.get(company.id)

                if image_analysis:
                    image_dict = serialization.sqlalchemy_to_dict(image_analysis)

                    for field in (
                        "id",
                        "uuid",
                        "company_id",
                        "created_at",
                        "updated_at",
                    ):
                        image_dict.pop(field, None)

                    company_dict.update(image_dict)

                companies_with_analysis.append(company_dict)

            return {
                "data": companies_with_analysis,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total_count,
                    "pages": (total_count + limit - 1) // limit,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting companies: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_companies: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),

            ),
            self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    

    def account_pending_approval_detail(self, message: str | None = None) -> dict:
        return {
            "code": constants.ACCOUNT_PENDING_APPROVAL_CODE,
            "message": message or constants.ACCOUNT_PENDING_APPROVAL_MESSAGE,
        }


    def raise_account_pending_approval(self, message: str | None = None) -> None:
        raise HTTPException(
            status_code=403,
            detail=self.account_pending_approval_detail(message),
        )


    def ensure_user_fully_approved(self, firebase_uid: str) -> None:
        """Raise 403 if the user created a company but has not received one-time admin approval."""
        if auth.is_static_admin_uid(firebase_uid) or auth.is_guest_uid(firebase_uid):
            return

        user = self.user_repo.get_user_by_firebase_id(firebase_uid)
        if not user:
            raise error.NotFound(
                f"User with Firebase UID '{firebase_uid}' not found in database. "
                "Please ensure the user is registered in the local database.",
            )
        if user.is_admin:
            return
        if user.has_created_company and not user.is_fully_approved:
            self.raise_account_pending_approval()


    async def create_company(self, data, user):
        try:
            if not user:
                raise error.Unauthorized("Unauthorized")

            creating_user: Optional[user_tables.User] = None
            if not auth.is_static_admin_uid(user["uid"]) and not data.eco_id:
                creating_user = self.user_repo.get_user_by_firebase_id(user["uid"])
                if not creating_user:
                    raise error.NotFound("User not found")
                if creating_user.has_created_company and not creating_user.is_fully_approved:
                    self.raise_account_pending_approval(constants.ACCOUNT_PENDING_CREATE_COMPANY_MESSAGE)

            if self.repo.company_exists(data.company_name):
                raise error.AlreadyExists("Company already exists")

            if data.eco_id:
                if self.repo.company_uuid_exists(data.eco_id):
                    raise error.AlreadyExists(
                        f"Company with eco_id {data.eco_id} already exists"
                    )

                eniro = await asyncio.to_thread(
                    self.fetch_eniro_company_data,
                    data.eco_id,
                )
                
                if eniro:
                    data.company_name = eniro.get("company_name") or data.company_name
                    data.address = eniro.get("address") or data.address
                    data.company_info = eniro.get("company_info") or data.company_info
                    data.logo_url = eniro.get("logo_url") or data.logo_url
                    data.url = eniro.get("url") or data.url

            company = self.repo.create_company(data)

            if not auth.is_static_admin_uid(user["uid"]) and not data.eco_id:
                owner = self.user_repo.get_user_by_firebase_id(user["uid"])
                if owner:
                    self.repo.create_company_owner(company.id, owner.id)
                    if creating_user and not creating_user.has_created_company:
                        creating_user.has_created_company = True
                        creating_user.is_fully_approved = False
                        logger.info(
                            "User %s marked pending onboarding approval after first company creation",
                            creating_user.email,
                        )

            self.repo.create_default_company_features(company.id)


            if (
                creating_user
                and creating_user.has_created_company
                and not creating_user.is_fully_approved
            ):
                enqueue_onboarding_admin_approval_email(
                    self.db,
                    user_email=creating_user.email,
                    user_name=creating_user.name,
                    user_uuid=str(creating_user.uuid),
                    company_name=data.company_name or "",
                    company_uuid=str(company.uuid),
                )

            await redis.redis_set(
                f"company_{company.uuid}",
                json.dumps(serialization.sqlalchemy_to_dict(company)),
            )

            await redis.redis_list_push("companies", str(company.uuid))

            return {
                "status": "success",
                "message": f"Company '{company.company_name}' created successfully",
                "id": company.uuid,
                "company_name": company.company_name,
                "onboarding_pending": bool(
                creating_user and creating_user.has_created_company and not creating_user.is_fully_approved
            ),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating company: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_company: {str(e)[:100]}",
                    status="error",
                    status_code=500,

            ),
            self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def update_company_feature(self, data, user):
        try:
            if not auth.check_user_company_access(data.company_id, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            company_id_int = self.repo.get_company_id_from_uuid(data.company_id)

            return self.repo.update_company_feature(
                company_id_int,
                data.feature_id,
                data.enabled,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating company feature: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_company_feature: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_company_features(self, company_id, user):
        try:
            if not auth.check_user_company_access(company_id, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            company_id_int = self.repo.get_company_id_from_uuid(company_id)

            return self.repo.get_company_features(company_id_int)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company features: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_company_features: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def patch_company_billing(self, company_id, data, user):
        try:
            if not user:
                raise error.PermissionDenied("Unauthorized")

            update_data = data.model_dump(exclude_unset=True)

            if not update_data:
                raise error.BadRequest(
                    "At least one of tier or agent_category is required"
                )

            company = self.repo.patch_company_billing(
                company_id,
                update_data,
            )

            await redis.redis_delete(f"company_{company_id}")
            await redis.redis_list_remove_by_value("companies", company_id)

            return {
                "status": "success",
                "message": "Company billing fields updated successfully",
                "data": serialization.sqlalchemy_to_dict(company),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error patching company billing: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"patch_company_billing: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def _company_notification_email_item(self, company_id: str, company_name: str, email_recipients: Optional[list]):
        recipients = []
        if email_recipients:
            recipients = [
                str(email).strip()
                for email in email_recipients
                if email is not None and str(email).strip()
            ]
        return {
            "company_id": str(company_id),
            "company_name": company_name,
            "email_id": ", ".join(recipients) if recipients else None,
        }

    def _parse_company_id_values(self, company_ids: Optional[Union[str, List[str]]]) -> List[str]:
        if not company_ids:
            return []
        if isinstance(company_ids, str):
            company_ids = [company_ids]

        values = []
        for raw_value in company_ids:
            for raw_part in str(raw_value).split(","):
                cleaned = raw_part.strip().strip("\"'")
                if cleaned:
                    values.append(cleaned)
        return values

    def get_company_notification_emails(self, data, user):
        if data.all_company:
            rows = self.repo.get_all_company_notification_emails()
        else:
            company_ids = self._parse_company_id_values(data.company_ids)
            company_ids.extend(self._parse_company_id_values(data.company_id))
            company_ids = list(dict.fromkeys(company_ids))

            if not company_ids:
                raise error.BadRequest(
                    "company_ids is required when all_company is false"
                )

            rows = self.repo.get_company_notification_emails(company_ids)

        return {
            "success": True,
            "status_code": 200,
            "message": "Company notification emails retrieved successfully",
            "data": [
                self._company_notification_email_item(
                    company_id,
                    company_name,
                    email_recipients,
                )
                for company_id, company_name, email_recipients in rows
            ],
        }


    async def get_company(self, company_id, user):
        try:
            if not auth.check_user_company_access(company_id, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            cached_company = await redis.redis_get(f"company_{company_id}")

            if cached_company:
                return cached_company

            company, image_analysis = self.repo.get_company(company_id)

            company_data = serialization.sqlalchemy_to_dict(company)

            if image_analysis:
                image_data = serialization.sqlalchemy_to_dict(image_analysis)

                for field in (
                    "id",
                    "uuid",
                    "company_id",
                    "created_at",
                    "updated_at",
                ):
                    image_data.pop(field, None)

                company_data.update(image_data)

            await redis.redis_set(
                f"company_{company_id}",
                json.dumps(company_data),
            )

            await redis.redis_list_push(
                "companies",
                company_id,
            )
            return company_data
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_company: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),

            ),
            self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    async def update_company(self, company_uuid, data, user):
        try:
            if not auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            # Refresh data from Eniro if eco_id is provided
            if data.eco_id:
                eniro_data = await asyncio.to_thread(
                    self.fetch_eniro_company_data,
                    data.eco_id,
                )

                if eniro_data:
                    for key, value in eniro_data.items():
                        if value is not None:
                            setattr(data, key, value)

            payload = data.model_dump(exclude_unset=True)

            company = self.repo.update_company(company_uuid, payload)

            company_data = serialization.sqlalchemy_to_dict(company)

            await redis.redis_delete(f"company_{company_uuid}")
            await redis.redis_list_remove_by_value("companies", company_uuid)

            return {
                "status": "success",
                "message": "Company updated successfully",
                "data": company_data,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating company: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_company: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def delete_company(self, company_uuid, user):
        try:
            if not auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            self.repo.delete_company(company_uuid)

            # Invalidate Redis
            await redis.redis_delete(f"company_{company_uuid}")
            await redis.redis_list_remove_by_value("companies", company_uuid)

            await redis.redis_delete(f"all_themes_{company_uuid}")

            await redis.redis_delete(f"all_instagram_posts_{company_uuid}")
            await redis.redis_delete(f"all_facebook_posts_{company_uuid}")
            await redis.redis_delete(f"all_linkedin_posts_{company_uuid}")

            await redis.redis_delete(f"channel_config_{company_uuid}")

            return {
                "status": "success",
                "message": f"Company {company_uuid} deleted",
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting company: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"delete_company: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),

            ),
            self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def _company_config_row_to_item(self, row: company_tables.CompanyConfig, company_uuid: str):
        return company_schema.CompanyConfigItem(
            uuid=row.uuid,
            company_id=company_uuid,
            supported_languages=row.supported_languages or [],
            default_language=row.default_language or "",
            location_mode=row.location_mode or "",
            company_address=row.company_address,
            business_hours=row.business_hours,
            exception_hours=row.exception_hours,
            notification_email_recipients=row.notification_email_recipients,
            bookings_enabled=row.bookings_enabled if row.bookings_enabled is not None else True,
            caller_data_collection=row.caller_data_collection,
            callback_settings=row.callback_settings,
            phone_no=row.phone_no,
            phone_summary=row.phone_summary,
            email_summary=row.email_summary,
            daily_summary=row.daily_summary,
            customer_sms_enabled=row.customer_sms_enabled,
            sms_email=row.sms_email,
            scheduled_email_time=(
                row.scheduled_email_time.isoformat()
                if getattr(row, "scheduled_email_time", None) is not None
                else None
            ),
            scheduled_timezone=getattr(row, "scheduled_timezone", None),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


    def create_company_config(self, data, user):
        try:
            company_id_int = auth.check_user_company_access(
                data.company_id,
                user["uid"],
                self.db,
                require_full_approval=False
            )

            config = self.repo.create_company_config(
                company_id_int,
                data,
            )

            return {
                "success": True,
                "message": "Company configuration created successfully",
                "data": self._company_config_row_to_item(
                    config,
                    data.company_id,
                ),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating company config: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_company_config: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_company_config_by_company(self, company_id, user):
        try:
            if not auth.check_user_company_access(company_id, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            config = self.repo.get_company_config_by_company(company_id)

            return {
                "success": True,
                "message": "Company configuration retrieved successfully",
                "data": (
                    self._company_config_row_to_item(config, company_id)
                    if config
                    else None
                ),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting company config by company: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_company_config_by_company: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")
    
    def delete_company_config(self, company_uuid, config_uuid, user):
        try:
            if not auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False):
                raise error.PermissionDenied(
                    "You are not authorized to access this resource"
                )

            self.repo.delete_company_config(config_uuid)

            return {
                "success": True,
                "message": "Company configuration deleted successfully",
                "data": None,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting company config: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"delete_company_config: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def update_company_config(self, config_uuid, data, user):
        try:
            existing = self.repo.get_company_config(config_uuid)
            if existing is None:
                raise error.NotFound("Company configuration not found")

            auth.check_user_company_access(
                self.repo.get_company_uuid_from_id(existing.company_id),
                user["uid"],
                self.db,
                require_full_approval=False
            )

            config = self.repo.update_company_config(
                config_uuid,
                data.model_dump(exclude_unset=True),
            )

            config_data = serialization.sqlalchemy_to_dict(config)
            config_data["company_id"] = self.repo.get_company_uuid_from_id(config.company_id)

            return {
                "success": True,
                "message": "Company configuration updated successfully",
                "data": config_data,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating company config: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_company_config: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def update_notification_config(self, data, user):
        if not auth.check_user_company_access(data.company_id, user["uid"], self.db, require_full_approval=False):
            raise error.PermissionDenied(
                "You are not authorized to access this resource"
            )

        config = self.repo.update_notification_config(data)

        return {
            "success": True,
            "status_code": 200,
            "message": "Notification settings updated successfully",
            "data": self._notification_config_to_dict(
                    config,
                    data.company_id,
                ),
        }
    
    def get_notification_config(self, company_id, user):
        if not auth.check_user_company_access(company_id, user["uid"], self.db, require_full_approval=False):
            raise error.PermissionDenied(
                "You are not authorized to access this resource"
            )

        config = self.repo.get_notification_config(company_id)

        return {
            "success": True,
            "status_code": 200,
            "message": "Notification settings retrieved successfully",
            "data": self._notification_config_to_dict(
                            config,
                            company_id,
                        ),
        }


    def _notification_config_to_dict(self, config, company_uuid):
        return {
            "company_id": company_uuid,
            "phone_no": config.phone_no,
            "phone_summary": config.phone_summary,
            "email_summary": config.email_summary,
            "email_recipients": config.notification_email_recipients,
            "daily_summary": config.daily_summary,
            "customer_sms_enabled": config.customer_sms_enabled,
            "sms_email": config.sms_email,
            "scheduled_email_time": (
                config.scheduled_email_time.isoformat()
                if config.scheduled_email_time
                else None
            ),
            "scheduled_timezone": config.scheduled_timezone,
        }














