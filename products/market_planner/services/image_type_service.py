from sqlalchemy.orm import Session
import logging

from products.market_planner.repository.image_type_repo import ImageTypeRepository
from shared.database.postgres import serialization
from shared.utils.auth import auth
from shared.utils.error import error, error_handler
from shared.logger.schema import log_schema
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class ImageTypeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ImageTypeRepository(db)

    def create_image_type(self, data, user):
        company_id_int = auth.check_user_company_access(
            data.company_id,
            user["uid"],
            self.db,
            require_full_approval=False
        )

        if self.repo.get_image_config(company_id_int):
            raise error.BadRequest(
                "Image config already exists for this company"
            )

        try:
            image_config = self.repo.create_image_config(
                company_id=company_id_int,
                image_type=data.image_type,
            )

            return serialization.sqlalchemy_to_dict(image_config)

        except Exception as e:
            logger.error(f"Error creating image type: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"create_image_type: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    def get_image_type(self, company_id, user):
        company_id_int = auth.check_user_company_access(company_id, user["uid"], self.db, require_full_approval=False)

        try:
            image_config = self.repo.get_image_config(company_id_int)
            if not image_config:
                raise error.NotFound("Image config does not exist for this company")
            return serialization.sqlalchemy_to_dict(image_config)

        except Exception as e:
            logger.error(f"Error getting image type: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_image_type: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")


    def update_image_setting(self, data, user):
        company_id_int = auth.check_user_company_access(
            data.company_id,
            user["uid"],
            self.db,
            require_full_approval=False
        )

        try:
            image_config = self.repo.update_image_config(
                company_id=company_id_int,
                image_type=data.image_type,
            )

            return serialization.sqlalchemy_to_dict(image_config)

        except Exception as e:
            logger.error(f"Error updating image setting: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_image_setting: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

