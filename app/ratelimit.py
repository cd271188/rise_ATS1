"""Sliding-window rate limiter. In-memory implementation behind a small interface so Redis can replace it."""
import logging
import time
import threading
from collections import defaultdict, deque

log = logging.getLogger("ats.ratelimit")


class Ratelimiter:
    """Interface: hit() records an attempt and returns (allowed, retry_after_seconds)."""
    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        raise NotImplementedError

    def reset(self):
        pass


class MemoryRatelimiter(Ratelimiter):
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._ops = 0

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + window - now) + 1)
            q.append(now)
            self._ops += 1
            if self._ops % 1000 == 0:
                self._sweep(now, window)
            return True, 0

    def _sweep(self, now: float, window: int):
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]

    def reset(self):
        with self._lock:
            self._hits.clear()


class RedisRatelimiter(Ratelimiter):
    """Sliding window shared by every worker and server. If Redis is unreachable it lets requests through (and logs):
    losing throttling for a while is better than taking the whole service down."""

    PREFIX = "ats:rl:"

    def __init__(self, client):
        self.r = client
        self._last_warn = 0.0

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        k, now, member = self.PREFIX + key, time.time(), uuid.uuid4().hex
        try:
            pipe = self.r.pipeline(transaction=True)
            pipe.zremrangebyscore(k, 0, now - window)
            pipe.zcard(k)
            pipe.zadd(k, {member: now})
            pipe.expire(k, window + 1)
            count = pipe.execute()[2]
            if count <= limit:
                return True, 0
            self.r.zrem(k, member)
            oldest = self.r.zrange(k, 0, 0, withscores=True)
            wait = int(oldest[0][1] + window - now) + 1 if oldest else window
            return False, max(1, wait)
        except Exception as e:
            if now - self._last_warn > 60:
                log.warning("rate limiter could not reach Redis; allowing requests: %s", e)
                self._last_warn = now
            return True, 0

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False

    def reset(self):
        for k in self.r.scan_iter(self.PREFIX + "*"):
            self.r.delete(k)


class NullRatelimiter(Ratelimiter):
    def hit(self, key, limit, window):
        return True, 0


def build(settings) -> Ratelimiter:
    if not settings.rate_limit_enabled:
        return NullRatelimiter()
    if settings.redis_url:
        import redis
        return RedisRatelimiter(redis.Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1))
    return MemoryRatelimiter()


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("too many requests")
        self.retry_after = retry_after