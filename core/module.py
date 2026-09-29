from fastapi import FastAPI

from core.api import billing_routes, company_routes, product_routes, user_routes

API_PREFIX = "/api/v1"

# Identity recorded in core.installed_products. Bump PRODUCT_VERSION on release.
# core is not optional: it owns users, companies and the registry itself, so it is
# always installed and always enabled.
PRODUCT_NAME = "core"
PRODUCT_VERSION = "1.0.0"
PRODUCT_SCHEMA = "core"


def register_core(app: FastAPI) -> None:
    app.include_router(company_routes.router, prefix=API_PREFIX)
    app.include_router(user_routes.router, prefix=API_PREFIX)
    app.include_router(user_routes.admin_router, prefix=f"{API_PREFIX}/admin")
    app.include_router(billing_routes.router, prefix=API_PREFIX)
    app.include_router(product_routes.router, prefix=API_PREFIX)
