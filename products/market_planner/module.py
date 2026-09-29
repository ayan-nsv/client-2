from fastapi import FastAPI

from core.product_hooks import register_backfill_hook, register_company_created_hook
from products.market_planner import provisioning
from products.market_planner.api import (
    blog_routes,
    channel_routes,
    content_routes,
    image_type_route,
    newsletter_routes,
    planner_routes,
    theme_routes,
)
from products.market_planner.social_media.linkedin.api import linkedin_routes
from products.market_planner.social_media.meta.facebook.api import facebook_routes
from products.market_planner.social_media.meta.instagram.api import instagram_routes
from products.market_planner.social_media.meta.whatsapp.api import whatsapp_routes
from products.market_planner.social_media.telegram.api import telegram_routes
from products.market_planner.social_media.tiktok.api import tiktok_routes
from products.market_planner.social_media.meta.boost.api import meta_boost

API_PREFIX = "/api/v1"

# Identity recorded in core.installed_products. Bump PRODUCT_VERSION on release.
PRODUCT_NAME = "market_planner"
PRODUCT_VERSION = "1.0.0"
PRODUCT_SCHEMA = "market_planner"


def register_market_planner(app: FastAPI) -> None:
    # Registered here rather than at import time: main.py imports this module even
    # when the product is disabled, and a disabled product must not seed its tables.
    register_company_created_hook(provisioning.seed_company_defaults)
    register_backfill_hook(provisioning.backfill_company_defaults)

    app.include_router(planner_routes.router, prefix=API_PREFIX)
    app.include_router(theme_routes.router, prefix=API_PREFIX)
    app.include_router(content_routes.router, prefix=API_PREFIX)
    app.include_router(channel_routes.router, prefix=API_PREFIX)
    app.include_router(blog_routes.router, prefix=API_PREFIX)
    app.include_router(newsletter_routes.router, prefix=API_PREFIX)
    app.include_router(image_type_route.router, prefix=API_PREFIX)

    app.include_router(instagram_routes.router, prefix=API_PREFIX)
    app.include_router(facebook_routes.router, prefix=API_PREFIX)
    app.include_router(whatsapp_routes.router, prefix=API_PREFIX)
    app.include_router(linkedin_routes.router, prefix=API_PREFIX)
    app.include_router(telegram_routes.router, prefix=f"{API_PREFIX}/telegram")
    app.include_router(tiktok_routes.router, prefix=API_PREFIX)
    app.include_router(meta_boost.router, prefix=API_PREFIX)