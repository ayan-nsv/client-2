"""Celery configuration contributed by the ``core`` module.

Consumed by the root ``celery_app`` module, which owns the only Celery instance.
"""

from kombu import Queue

TASK_QUEUES = (
    Queue("email-queue", durable=True),
    Queue("update-company-queue", durable=True),
)

TASK_ROUTES = {
    "core.send_email": {"queue": "email-queue"},
    "core.update_company": {"queue": "update-company-queue"},
}

BEAT_SCHEDULE = {}

TASK_IMPORTS = ("core.workers.tasks",)
