from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "voltyk",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    timezone=settings.tz,
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "daily-channel-check": {
            "task": "src.tasks.channel_check.check_all_channels",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
