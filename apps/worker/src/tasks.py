"""Background tasks for Heliox Gateway."""

import httpx
import structlog
from celery import shared_task

from src.celery_app import app

logger = structlog.get_logger(__name__)


@app.task(bind=True, max_retries=3)
def refresh_cache(self, cache_key: str, upstream_url: str, headers: dict, timeout: int = 30):
    """
    Background task to refresh a stale cache entry.
    
    Used for stale-while-revalidate (SWR) pattern.
    """
    import asyncio
    
    async def do_refresh():
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    upstream_url,
                    headers=headers,
                    timeout=timeout,
                )
                
                if response.status_code == 200:
                    # Store in cache
                    # Note: This would need Redis connection
                    logger.info(
                        "Cache refresh completed",
                        cache_key=cache_key,
                        status_code=response.status_code,
                    )
                    return {"success": True, "status_code": response.status_code}
                else:
                    logger.warning(
                        "Cache refresh returned non-200",
                        cache_key=cache_key,
                        status_code=response.status_code,
                    )
                    return {"success": False, "status_code": response.status_code}
                    
        except httpx.TimeoutException:
            logger.error("Cache refresh timed out", cache_key=cache_key)
            raise self.retry(countdown=60)
        except Exception as e:
            logger.error("Cache refresh failed", cache_key=cache_key, error=str(e))
            raise self.retry(countdown=60)
    
    return asyncio.run(do_refresh())


@app.task
def aggregate_hourly_metrics():
    """
    Aggregate request metrics for the past hour.
    
    Runs hourly to compute aggregated statistics.
    """
    logger.info("Running hourly metrics aggregation")
    
    # This would:
    # 1. Query request_logs for the past hour
    # 2. Compute aggregates (count, avg latency, cache hit rate, etc.)
    # 3. Store in a metrics table or time-series database
    
    return {"status": "completed"}


@app.task
def cleanup_old_logs(days: int = 30):
    """
    Clean up old request logs.
    
    Runs daily to remove logs older than the specified number of days.
    """
    logger.info("Running log cleanup", retention_days=days)
    
    # This would:
    # 1. Delete request_logs older than X days
    # 2. Optionally archive to cold storage first
    
    return {"status": "completed", "retention_days": days}


@app.task
def reset_expired_quotas():
    """
    Reset expired quota counters.
    
    Checks for and resets any quota counters that have expired.
    """
    logger.info("Checking for expired quotas")
    
    # Redis keys with expiration handle this automatically,
    # but this task can clean up any orphaned data
    
    return {"status": "completed"}


@app.task(bind=True, max_retries=5)
def send_webhook_notification(self, webhook_url: str, event_type: str, payload: dict):
    """
    Send webhook notification for events like:
    - Rate limit exceeded
    - Quota exhausted
    - Key blocked
    """
    import asyncio
    
    async def send():
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json={
                        "event_type": event_type,
                        "payload": payload,
                    },
                    timeout=10,
                )
                
                if response.status_code >= 400:
                    logger.warning(
                        "Webhook returned error",
                        url=webhook_url,
                        status_code=response.status_code,
                    )
                    raise self.retry(countdown=60 * (self.request.retries + 1))
                    
                return {"success": True}
                
        except httpx.RequestError as e:
            logger.error("Webhook request failed", url=webhook_url, error=str(e))
            raise self.retry(countdown=60 * (self.request.retries + 1))
    
    return asyncio.run(send())


@app.task
def update_bloom_filter(route_name: str, paths: list[str]):
    """
    Batch update bloom filter with multiple 404 paths.
    
    More efficient than updating one at a time.
    """
    logger.info(
        "Updating bloom filter",
        route=route_name,
        path_count=len(paths),
    )
    
    # This would batch-update the bloom filter
    
    return {"status": "completed", "paths_added": len(paths)}
