import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from products.market_planner.repository.channel_repo import ChannelRepository
from shared.utils.auth import auth
from shared.utils.error import error, error_handler
from shared.cache.redis import redis
from shared.database.postgres import serialization
from core.repository.company_repo import CompanyRepository
from shared.logger.schema import log_schema
from shared.logger.log import setup_logger
logger = setup_logger("marketing-app")

class ChannelService:
    def __init__(self, db: Session):
        self.db = db
        self.channel_repo = ChannelRepository(db)
        self.company_repo = CompanyRepository(db)

    async def configure_channel(self, company_uuid, data, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)


            config = self.channel_repo.get_channel_config(company_id_int)

            if config:
                config = self.channel_repo.update_channel_config(
                    company_id_int,
                    data.model_dump(exclude_unset=True),
                )

                message = "Channel config updated successfully"

            else:
                config = self.channel_repo.create_channel_config(
                    company_id_int,
                    data,
                )

                message = "Channels configured successfully"

            await redis.redis_set(
                f"channel_config_{company_uuid}",
                json.dumps(serialization.sqlalchemy_to_dict(config)),
            )

            return {
                "status": "success",
                "message": message,
                "company_id": company_uuid,
            }
        except Exception as e:
            logger.error(f"Error configuring channel: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"configure_channel: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def get_channel_config(self, company_uuid, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            cached = await redis.redis_get(f"channel_config_{company_uuid}")
            if cached:
                return cached


            config = self.channel_repo.get_channel_config(company_id_int)

            config_data = serialization.sqlalchemy_to_dict(config)

            await redis.redis_set(
                f"channel_config_{company_uuid}",
                json.dumps(config_data),
            )
            return config_data
        except Exception as e:
            logger.error(f"Error getting channel config: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"get_channel_config: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")

    async def update_channel_config(self, company_uuid, data, user):
        try:
            company_id_int = auth.check_user_company_access(company_uuid, user["uid"], self.db, require_full_approval=False)

            config = self.channel_repo.update_channel_config(
                company_id_int,
                data.model_dump(exclude_unset=True),
            )

            await redis.redis_delete(f"channel_config_{company_uuid}")

            return {
                "status": "success",
                "message": "Channel config updated successfully",
                "company_id": company_uuid,
            }
        except Exception as e:
            logger.error(f"Error updating channel config: {e}")
            error_handler.record_log(
                log_schema.LogRequest(
                    company_id=None,
                    severity="error",
                    message=f"update_channel_config: {str(e)[:100]}",
                    status="error",
                    status_code=500,
                    timestamp=datetime.now(timezone.utc),
                ),
                self.db,
            )
            raise error.InternalServerError(message="Internal server error")