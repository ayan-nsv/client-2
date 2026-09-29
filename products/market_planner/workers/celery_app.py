"""Celery configuration contributed by the ``market_planner`` module.

Consumed by the root ``celery_app`` module, which owns the only Celery instance.
"""

from celery.schedules import crontab
from kombu import Queue

TASK_QUEUES = (
    Queue("draft-posts-queue", durable=True),
    Queue("publish-posts-queue", durable=True),
    Queue("save-post-queue", durable=True),
    Queue("update-post-queue", durable=True),
    Queue("delete-post-queue", durable=True),
    Queue("whatsapp-match-replies-queue", durable=True),
)

TASK_ROUTES = {
    "market_planner.generate_draft_posts": {"queue": "draft-posts-queue"},
    "market_planner.publish_scheduled_posts": {"queue": "publish-posts-queue"},
    "market_planner.save_post": {"queue": "save-post-queue"},
    "market_planner.update_post": {"queue": "update-post-queue"},
    "market_planner.delete_post": {"queue": "delete-post-queue"},
    "market_planner.whatsapp_match_replies": {"queue": "whatsapp-match-replies-queue"},
}

BEAT_SCHEDULE = {
    "publish-scheduled-posts-every-10-minutes": {
        "task": "market_planner.publish_scheduled_posts",
        "schedule": crontab(minute="*/10"),
    },
    "whatsapp-match-replies-every-3-hours": {
        "task": "market_planner.whatsapp_match_replies",
        "schedule": crontab(minute=0, hour="*/3"),
    },
}

TASK_IMPORTS = ("products.market_planner.workers.tasks",)
