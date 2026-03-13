from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from bot.config import settings

celery_app = Celery(
    "voltyk",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.TZ,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "channel-guard-daily": {
        "task": "bot.tasks.channel_guard.validate_all_channels",
        "schedule": crontab(hour=3, minute=0),
    },
    "schedule-check": {
        "task": "bot.tasks.schedule_tasks.check_all_schedules",
        "schedule": 60.0,
    },
}
