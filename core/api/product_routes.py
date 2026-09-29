from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.services.product_service import InstalledProductService
from core.schema import product_schema
from shared.database.postgres.database_config import get_db
from shared.utils.auth import auth

router = APIRouter()


# Admin-only throughout: these endpoints describe the deployment, not a tenant.
# A regular user must not be able to disable a product for everyone.
@router.get("/products", tags=["Installed_products"])
def list_installed_products(
    user: dict = Depends(auth.get_admin_user),
    db: Session = Depends(get_db),
):
    """Which products are installed on this deployment, and at what version."""
    service = InstalledProductService(db)
    return service.list_products()


@router.put("/products/{product_name}", tags=["Installed_products"])
def update_installed_product(
    product_name: str,
    payload: product_schema.InstalledProductUpdateRequest,
    user: dict = Depends(auth.get_admin_user),
    db: Session = Depends(get_db),
):
    """Enable or disable a product. Does not drop its schema or data."""
    service = InstalledProductService(db)
    return service.set_product_enabled(product_name, payload)
