"""
Rate limiting (tiêu chí 7) — sliding window lưu state trong Redis.
"""
import time
import uuid
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60
_memory_requests: dict[str, list[float]] = {}


def check_rate_limit(key: str) -> None:
    """Giới hạn RATE_LIMIT_PER_MINUTE request / 60 giây cho mỗi API key."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"rate_limit:{key}"

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()

            if count >= limit:
                oldest = r.zrange(redis_key, 0, 0, withscores=True)
                retry_after = (
                    max(1, int(WINDOW_SECONDS - (now - oldest[0][1])))
                    if oldest
                    else WINDOW_SECONDS
                )
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS)
            pipe.execute()
            return
        except HTTPException:
            raise
        except Exception:
            pass

    timestamps = [t for t in _memory_requests.get(key, []) if t > window_start]
    if len(timestamps) >= limit:
        retry_after = max(1, int(WINDOW_SECONDS - (now - timestamps[0])))
        _memory_requests[key] = timestamps
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    timestamps.append(now)
    _memory_requests[key] = timestamps
