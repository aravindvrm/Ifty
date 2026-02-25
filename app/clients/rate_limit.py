import threading
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    rate_per_sec: float
    capacity: float
    tokens: float
    last_refill: float

    def consume(self, amount: float = 1.0) -> float:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return 0.0
        deficit = amount - self.tokens
        wait = deficit / self.rate_per_sec if self.rate_per_sec > 0 else 0.0
        self.tokens = 0.0
        return wait


class ProviderRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, TokenBucket] = {}

    def register(self, provider: str, rate_per_sec: float, capacity: float | None = None) -> None:
        cap = capacity if capacity is not None else max(rate_per_sec, 1.0)
        self._buckets[provider] = TokenBucket(
            rate_per_sec=rate_per_sec,
            capacity=cap,
            tokens=cap,
            last_refill=time.monotonic(),
        )

    def acquire(self, provider: str) -> None:
        with self._lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                return
            wait = bucket.consume(1.0)
        if wait > 0:
            time.sleep(wait)

