"""The project's single Celery application.

Every feature module contributes queues, routes, beat entries and task imports
through its own ``workers/celery_app.py``. This is the only module in the
project that creates a ``Celery`` instance.

Run with::

    celery -A celery_app worker
    celery -A celery_app beat
"""

import os

from celery import Celery
from dotenv import load_dotenv

from core.product_gate import get_enabled_product_names
from core.workers import celery_app as core_workers
from product_catalog import load_optional_worker_modules
from shared.database.postgres.model_registry import import_all_models

load_dotenv()

# A worker imports only its own task modules, which is not enough for SQLAlchemy to
# resolve relationships pointing at classes declared elsewhere.
import_all_models()

# Optional worker modules are imported only when their package is present. Queues,
# routes, beat entries and task imports are gated further by core.installed_products
# so an installed-but-disabled product does not schedule work against a missing schema.
_WORKER_MODULES_BY_PRODUCT = {
    "core": core_workers,
    **load_optional_worker_modules(),
}

# Same fail-open read the web app uses in create_app(): an unreadable registry loads
# everything shipped, because a worker that silently consumes nothing is far harder
# to notice than one that errors. core is always included.
_ENABLED_PRODUCTS = get_enabled_product_names(
    fallback=frozenset(_WORKER_MODULES_BY_PRODUCT),
    required=frozenset({"core"}),
)

ENABLED_WORKER_PRODUCTS = tuple(
    name for name in _WORKER_MODULES_BY_PRODUCT if name in _ENABLED_PRODUCTS
)

WORKER_MODULES = tuple(
    _WORKER_MODULES_BY_PRODUCT[name] for name in ENABLED_WORKER_PRODUCTS
)

# REDIS_URL (or legacy CELERY_BROKER_URL), e.g. redis://:password@cache:6379/0 in Docker
redis_url = (
    os.getenv("REDIS_URL")
    or os.getenv("CELERY_BROKER_URL")
    or "redis://localhost:6379/0"
)

celery_app = Celery("mp_dev", broker=redis_url, backend=redis_url)


TASK_QUEUES = tuple(
    {
        queue.name: queue
        for module in WORKER_MODULES
        for queue in module.TASK_QUEUES
    }.values()
)

TASK_ROUTES = {
    task_name: route
    for module in WORKER_MODULES
    for task_name, route in module.TASK_ROUTES.items()
}

BEAT_SCHEDULE = {
    entry_name: entry
    for module in WORKER_MODULES
    for entry_name, entry in module.BEAT_SCHEDULE.items()
}

TASK_IMPORTS = tuple(
    dict.fromkeys(
        task_module
        for module in WORKER_MODULES
        for task_module in module.TASK_IMPORTS
    )
)


celery_app.conf.update(
    imports=TASK_IMPORTS,
    beat_schedule=BEAT_SCHEDULE,
    task_track_started=True,
    task_acks_late=True,  # Don't remove task from queue until it's completed
    task_reject_on_worker_lost=True,  # Requeue if worker crashes
    task_default_delivery_mode=2,  # Make messages persistent (durable)
    # Beat crontab uses Europe/Stockholm (Sweden, CET/CEST). Other periodic tasks use this wall clock too.
    timezone="Europe/Stockholm",
)

# Outside Docker a single worker consumes the default queue, so per-feature
# routing stays off to keep local runs working without -Q flags.
if os.getenv("DOCKER"):
    celery_app.conf.task_queues = TASK_QUEUES
    celery_app.conf.task_routes = TASK_ROUTES
