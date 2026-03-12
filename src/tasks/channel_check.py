from __future__ import annotations

from src.queues.celery_app import celery_app


@celery_app.task(
    name="src.tasks.channel_check.check_all_channels",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
)
def check_all_channels(self):
    """Daily channel validation at 03:00. No auto-blocking."""
    # TODO: Implement in PR-2 — iterate all channels, verify bot is admin
    pass
