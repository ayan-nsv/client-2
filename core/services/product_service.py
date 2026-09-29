from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.repository.product_repo import InstalledProductRepository
from shared.logger.log import setup_logger
from shared.logger.schema import log_schema
from shared.utils.error import error, error_handler

logger = setup_logger("marketing-app")


class InstalledProductService:
    """Deployment-level product registry.

    Callers are admin-only: this is not tenant configuration, it decides what the
    whole deployment loads. Tenant-level switches stay in core.company_features.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = InstalledProductRepository(db)

    def list_products(self):
        try:
            return self.repo.list_installed_dicts()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error listing installed products: {e}")
            self._record_error(f"list_products: {str(e)[:100]}")
            raise error.InternalServerError(message="Internal server error")

    def set_product_enabled(self, product_name: str, payload):
        # Imported inside the method: product_catalog imports every module.py,
        # including core's, which reaches back here through the router.
        from product_catalog import get_descriptor

        try:
            descriptor = get_descriptor(product_name)
            if descriptor is not None and descriptor.required and not payload.enabled:
                raise error.BadRequest(
                    f"Product '{product_name}' is required and cannot be disabled"
                )

            return self.repo.set_enabled(product_name, payload.enabled)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating installed product {product_name}: {e}")
            self._record_error(f"set_product_enabled: {str(e)[:100]}")
            raise error.InternalServerError(message="Internal server error")

    def _record_error(self, message: str) -> None:
        error_handler.record_log(
            log_schema.LogRequest(
                company_id=None,
                severity="error",
                message=message,
                status="error",
                status_code=500,
                timestamp=datetime.now(timezone.utc),
            ),
            self.db,
        )
