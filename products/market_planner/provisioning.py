"""What market_planner sets up for a newly created company.

These values used to be literals inside ``core.repository.company_repo.create_company``.
They are market_planner policy, so they live here now, and core reaches them through
``core.product_hooks`` without importing this module.

Note the ``*_active`` flags. The SQLAlchemy column defaults are ``False``, and
``ChannelRepository.create_channel_config`` does not set them at all, so this dict is
the only thing that makes a new company start with its channels switched on. That
behaviour predates this module; it is preserved deliberately, not inherited by
accident.
"""

from __future__ import annotations

from products.market_planner.tables import channel_tables, content_tables
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

DEFAULT_CHANNEL_CONFIG = {
    "instagram_post_count": 1,
    "facebook_post_count": 1,
    "linkedin_post_count": 1,
    "email_campaign_count": 1,
    "blog_post_count": 1,
    "blog_post_active": True,
    "email_campaign_active": True,
    "facebook_active": True,
    "instagram_active": True,
    "linkedin_active": True,
    "tiktok_active": True,
}

DEFAULT_IMAGE_TYPE = 5


def seed_company_defaults(db, company) -> None:
    """company_created hook: add market_planner's per-company rows.

    Adds only — core owns the transaction and commits once. Guarded so that a rerun
    (or a company that already went through backfill) cannot create duplicates:
    ChannelConfig.company_id is unique, and a second ImageConfig would leave two rows
    competing to describe the same company.
    """
    if not _has_channel_config(db, company.id):
        db.add(
            channel_tables.ChannelConfig(
                company_id=company.id,
                **DEFAULT_CHANNEL_CONFIG,
            )
        )

    if not _has_image_config(db, company.id):
        db.add(
            content_tables.ImageConfig(
                company_id=company.id,
                image_type=DEFAULT_IMAGE_TYPE,
            )
        )


def backfill_company_defaults(db) -> None:
    """backfill hook: give companies that predate market_planner their config.

    Reaches companies created while the product was switched off, which
    seed_company_defaults never saw. Idempotent — runs on every startup.
    """
    from core.tables import company_tables

    missing_channel = (
        db.query(company_tables.Company.id)
        .outerjoin(
            channel_tables.ChannelConfig,
            channel_tables.ChannelConfig.company_id == company_tables.Company.id,
        )
        .filter(channel_tables.ChannelConfig.id.is_(None))
        .all()
    )

    missing_image = (
        db.query(company_tables.Company.id)
        .outerjoin(
            content_tables.ImageConfig,
            content_tables.ImageConfig.company_id == company_tables.Company.id,
        )
        .filter(content_tables.ImageConfig.id.is_(None))
        .all()
    )

    for (company_id,) in missing_channel:
        db.add(
            channel_tables.ChannelConfig(
                company_id=company_id,
                **DEFAULT_CHANNEL_CONFIG,
            )
        )

    for (company_id,) in missing_image:
        db.add(
            content_tables.ImageConfig(
                company_id=company_id,
                image_type=DEFAULT_IMAGE_TYPE,
            )
        )

    if missing_channel or missing_image:
        db.commit()
        logger.info(
            "market_planner backfill: added %s channel configs, %s image configs",
            len(missing_channel),
            len(missing_image),
        )


def _has_channel_config(db, company_id) -> bool:
    return (
        db.query(channel_tables.ChannelConfig.id)
        .filter(channel_tables.ChannelConfig.company_id == company_id)
        .first()
        is not None
    )


def _has_image_config(db, company_id) -> bool:
    return (
        db.query(content_tables.ImageConfig.id)
        .filter(content_tables.ImageConfig.company_id == company_id)
        .first()
        is not None
    )
