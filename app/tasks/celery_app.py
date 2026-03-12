"""Celery application configuration.

Broker: Redis
Serializer: JSON
Timezone: Europe/Kyiv
Retry policy: max_retries=5, exponential backoff
"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "voltyk_bot",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone=settings.TZ,
    enable_utc=True,
    # Worker
    worker_concurrency=settings.CELERY_CONCURRENCY,
    worker_prefetch_multiplier=1,
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result backend TTL (1 day)
    result_expires=86400,
    # Default retry policy for all tasks
    task_annotations={
        "*": {
            "max_retries": 5,
            "default_retry_delay": 60,
        }
    },
    # Task routes — extended as tasks are added
    task_routes={
        "app.tasks.notifications.*": {"queue": "notifications"},
        "app.tasks.schedule.*": {"queue": "schedule"},
        "app.tasks.channels.*": {"queue": "channels"},
    },
    # Beat schedule
    beat_schedule={
        # Channel verification — once a day at 03:00 (Rule #3)
        "check-channels-daily": {
            "task": "app.tasks.channels.check_all_channels",
            "schedule": crontab(hour=3, minute=0),
        },
        # Daily metrics aggregation at 00:05
        "aggregate-daily-metrics": {
            "task": "app.tasks.metrics.aggregate_daily_metrics",
            "schedule": crontab(hour=0, minute=5),
        },
    },
)
