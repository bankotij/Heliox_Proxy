"""Celery application configuration."""

import os

from celery import Celery

# Get broker URL from environment
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery(
    "heliox_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["src.tasks"],
)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
    worker_prefetch_multiplier=4,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Rate limiting for tasks
    task_default_rate_limit="100/s",
    # Retry configuration
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Beat schedule for periodic tasks
app.conf.beat_schedule = {
    "aggregate-metrics-hourly": {
        "task": "src.tasks.aggregate_hourly_metrics",
        "schedule": 3600.0,  # Every hour
    },
    "cleanup-old-logs-daily": {
        "task": "src.tasks.cleanup_old_logs",
        "schedule": 86400.0,  # Every 24 hours
    },
    "reset-daily-quotas": {
        "task": "src.tasks.reset_expired_quotas",
        "schedule": 3600.0,  # Check every hour
    },
}

if __name__ == "__main__":
    app.start()
