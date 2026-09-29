"""The list of modules that declare SQLAlchemy models, and a helper to import them.

A ``relationship("Company")`` is resolved by class name against the declarative
registry, which a class only joins when the module declaring it is imported. The
FastAPI app happens to import every model module transitively through its routers;
a Celery worker imports only its task modules, so a mapper referring to a class
from an unimported module fails at first use with "failed to locate a name".

Importing every *shipped* model module up front makes mapper configuration
independent of which entrypoint is running. Alembic autogenerate needs the same
completeness for products present in this build.

A client image may omit unpaid product packages; those modules are skipped when
missing. A new module holding a ``__tablename__`` must be added to
``MODEL_MODULES``. Modules that only re-export classes declared elsewhere are
deliberately left out.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger("marketing-app")

MODEL_MODULES = (
    "core.tables.company_tables",
    "core.tables.product_tables",
    "core.tables.usage_tables",
    "core.tables.user_tables",
    "core.tables.invitation_tables",
    "products.knowledge.rag.tables.chatbot_tables",
    "products.knowledge.rag.tables.rag_tables",
    "products.market_planner.social_media.linkedin.tables.linkedin_tables",
    "products.market_planner.social_media.meta.facebook.tables.facebook_tables",
    "products.market_planner.social_media.meta.instagram.tables.instagram_tables",
    "products.market_planner.social_media.meta.whatsapp.tables.whatsapp_tables",
    "products.market_planner.social_media.telegram.tables.telegram_tables",
    "products.market_planner.social_media.tiktok.tables.tiktok_tables",
    "products.market_planner.tables.blog_tables",
    "products.market_planner.tables.channel_tables",
    "products.market_planner.tables.content_tables",
    "products.market_planner.tables.newsletter_tables",
    "products.market_planner.tables.rtyui_tables",
    "products.market_planner.tables.theme_tables",
    "products.telephone_agent.vapi.tables.agent_tables",
    "products.telephone_agent.vapi.tables.calender_tables",
    "products.telephone_agent.vapi.tables.call_concurrency_tables",
    "products.telephone_agent.vapi.tables.category_tables",
    "products.telephone_agent.vapi.tables.email_status_record_tables",
    "products.telephone_agent.vapi.tables.quality_tables",
    "shared.logger.tables.log_tables",
)


def import_all_models() -> None:
    """Import every shipped model module so the declarative registry is complete."""
    for module in MODEL_MODULES:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            missing = getattr(exc, "name", None) or ""
            # Skip only when the product package itself is absent from this build.
            if missing.startswith("products.") or missing == "products":
                logger.info("Model module %s not in this build; skipping", module)
                continue
            raise
