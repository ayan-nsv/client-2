"""Reads core.installed_products to decide what the deployment should load.

Called from ``create_app()`` at import time, which is before the lifespan hook has
run ``sync_installed_products``. On the normal Docker path that is fine — the
entrypoint runs ``alembic upgrade head`` before uvicorn, and the migration seeds the
table — but every other path has to be survivable.

**This function fails open.** If the table is missing, empty, or the database cannot
be reached, it returns every product in the catalogue. The reasoning: a deployment
that cannot read its own registry should behave exactly as it did before the registry
existed, not silently serve a subset of its API. A wrong "everything is on" is a
visible no-op; a wrong "everything is off" is an outage.
"""

from __future__ import annotations

from sqlalchemy import text

from shared.database.postgres.database_config import get_engine
from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

# The registry is read once per process. Three entry points now consult it at import
# time (create_app, celery_app, and each product's provider registration), and they
# all decide the same thing about the same database. Caching also keeps the warning
# below from being logged three times on a deployment that has no database yet.
#
# A one-element tuple is the "already read" marker so that a legitimately empty
# result is not mistaken for a cold cache. None inside it means the read failed.
_cached_read: tuple[frozenset[str] | None] | None = None


def reset_cache() -> None:
    """Forget the cached registry read. For tests that switch databases."""
    global _cached_read
    _cached_read = None


def _read_enabled_names() -> frozenset[str] | None:
    """Enabled product names from the registry, or None if it could not be read.

    Deliberately raw SQL rather than the ORM. This runs at import time from several
    entry points — including a product's own provider module, which is imported long
    before ``import_all_models()`` finishes. Querying through a mapped class there
    triggers ``configure_mappers()`` against a half-populated registry and fails with
    "expression 'Company' failed to locate a name", which the fail-open path then
    swallows into "load everything" — silently undoing the gating.

    A single-table SELECT has no such ordering requirement, so the gate is safe to
    call from anywhere.
    """
    global _cached_read
    if _cached_read is not None:
        return _cached_read[0]

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT product_name FROM core.installed_products "
                    "WHERE enabled = true"
                )
            ).fetchall()
        names = frozenset(row[0] for row in rows)
    except Exception as exc:
        logger.warning(
            "Could not read core.installed_products (%s); loading all products. "
            "This is expected before the first migration has run.",
            exc,
        )
        names = None

    _cached_read = (names,)
    return names


def get_enabled_product_names(fallback=None, required=None) -> frozenset[str]:
    """Product names this deployment should load. Never raises.

    ``fallback`` is what to return when the registry cannot be read, and ``required``
    is what to include regardless of what the registry says. Both default to the
    product catalogue.

    Callers on the Celery path must pass them. ``product_catalog`` imports every
    product's ``module.py``, which pulls in the FastAPI routers, which import
    ``celery_app`` — so reading the catalogue from inside ``celery_app`` closes an
    import cycle. Passing the small set the caller already knows avoids it.
    """
    if fallback is None or required is None:
        # Imported here for the same reason as in bootstrap: product_catalog imports
        # every module.py, and core must not pull products in at import time.
        from product_catalog import get_catalog

        catalog = get_catalog()
        if fallback is None:
            fallback = frozenset(d.name for d in catalog)
        if required is None:
            # core owns users/companies; it loads even if a row says otherwise.
            required = frozenset(d.name for d in catalog if d.required)

    all_names = frozenset(fallback)
    required = frozenset(required)

    enabled = _read_enabled_names()
    if enabled is None:
        return all_names

    if not enabled:
        logger.warning(
            "core.installed_products is empty; loading all products. "
            "Startup sync will populate it."
        )
        return all_names

    return frozenset(enabled) | required
