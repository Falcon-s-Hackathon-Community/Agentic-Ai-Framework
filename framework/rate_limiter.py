"""
Rate Limiter Module
Provides configurable rate limiting for LLM API calls to prevent
quota exhaustion when multiple LLMTasks run in parallel.
"""

import time
import threading
import logging
from collections import deque
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_calls: int          # Maximum number of calls allowed
    period_seconds: float   # Time window in seconds
    retry_on_limit: bool = True    # Whether to wait and retry or raise error
    max_wait_seconds: float = 60.0 # Maximum time to wait before giving up

    def __post_init__(self):
        if self.max_calls <= 0:
            raise ValueError("max_calls must be greater than 0")
        if self.period_seconds <= 0:
            raise ValueError("period_seconds must be greater than 0")
        if self.max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be greater than 0")


class RateLimiter:
    """
    Token bucket rate limiter using a sliding window algorithm.

    Tracks timestamps of recent calls in a deque. Before each call,
    it removes timestamps older than the time window and checks if
    the number of recent calls is below the limit.

    Thread-safe — designed for use with ThreadPoolExecutor.

    Example:
        # Allow max 10 calls per 60 seconds
        limiter = RateLimiter(RateLimitConfig(max_calls=10, period_seconds=60))

        # Before each LLM API call:
        limiter.acquire()  # blocks if limit reached, resumes when slot available
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._call_timestamps: deque = deque()
        self._lock = threading.RLock()

    def acquire(self, task_name: str = "unknown") -> None:
        """
        Acquire a rate limit slot. Blocks if limit is reached until
        a slot becomes available or max_wait_seconds is exceeded.

        Args:
            task_name: Name of the task requesting the slot (for logging)

        Raises:
            RuntimeError: If max_wait_seconds exceeded and retry_on_limit is False
        """
        waited = 0.0

        while True:
            with self._lock:
                now = time.monotonic()

                # Remove timestamps outside the current window
                cutoff = now - self.config.period_seconds
                while self._call_timestamps and self._call_timestamps[0] < cutoff:
                    self._call_timestamps.popleft()

                # Check if we are under the limit
                if len(self._call_timestamps) < self.config.max_calls:
                    self._call_timestamps.append(now)
                    if waited > 0:
                        logger.info(
                            f"Rate limit slot acquired for '{task_name}' "
                            f"after waiting {waited:.1f}s"
                        )
                    return

                # Calculate how long to wait for the oldest call to expire
                oldest = self._call_timestamps[0]
                wait_time = (oldest + self.config.period_seconds) - now
                wait_time = max(0.1, min(wait_time, 1.0))  # clamp between 0.1s and 1s

            # Check max wait exceeded
            if waited >= self.config.max_wait_seconds:
                if not self.config.retry_on_limit:
                    raise RuntimeError(
                        f"Rate limit exceeded for task '{task_name}'. "
                        f"Waited {waited:.1f}s (max: {self.config.max_wait_seconds}s). "
                        f"Limit: {self.config.max_calls} calls per {self.config.period_seconds}s."
                    )

            logger.warning(
                f"Rate limit reached for '{task_name}'. "
                f"Waiting {wait_time:.1f}s... "
                f"({len(self._call_timestamps)}/{self.config.max_calls} calls used)"
            )

            time.sleep(wait_time)
            waited += wait_time

    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.config.period_seconds
            active = sum(1 for t in self._call_timestamps if t >= cutoff)
            return {
                "calls_in_window": active,
                "max_calls": self.config.max_calls,
                "period_seconds": self.config.period_seconds,
                "available_slots": max(0, self.config.max_calls - active)
            }

    def reset(self) -> None:
        """Reset the rate limiter — clears all tracked timestamps."""
        with self._lock:
            self._call_timestamps.clear()
            logger.debug("Rate limiter reset.")


# Pre-built common configurations
class RateLimitPresets:
    """Common rate limit presets for popular LLM providers."""

    @staticmethod
    def openai_free_tier() -> RateLimitConfig:
        """OpenAI free tier: 3 requests per minute."""
        return RateLimitConfig(max_calls=3, period_seconds=60)

    @staticmethod
    def openai_pay_as_you_go() -> RateLimitConfig:
        """OpenAI pay-as-you-go: 60 requests per minute."""
        return RateLimitConfig(max_calls=60, period_seconds=60)

    @staticmethod
    def gemini_free_tier() -> RateLimitConfig:
        """Google Gemini free tier: 15 requests per minute."""
        return RateLimitConfig(max_calls=15, period_seconds=60)

    @staticmethod
    def conservative() -> RateLimitConfig:
        """Conservative default: 10 requests per minute."""
        return RateLimitConfig(max_calls=10, period_seconds=60)

    @staticmethod
    def custom(max_calls: int, period_seconds: float) -> RateLimitConfig:
        """Custom configuration."""
        return RateLimitConfig(max_calls=max_calls, period_seconds=period_seconds)


# Global shared rate limiter instance (shared across all LLMTask instances)
_global_llm_rate_limiter: Optional[RateLimiter] = None
_global_lock = threading.Lock()


def get_global_rate_limiter() -> Optional[RateLimiter]:
    """Get the global shared rate limiter."""
    return _global_llm_rate_limiter


def set_global_rate_limiter(config: RateLimitConfig) -> RateLimiter:
    """
    Set up the global rate limiter shared across all LLMTask instances.
    Call this once at application startup.

    Args:
        config: Rate limit configuration

    Returns:
        The configured RateLimiter instance
    """
    global _global_llm_rate_limiter
    with _global_lock:
        _global_llm_rate_limiter = RateLimiter(config)
        logger.info(
            f"Global LLM rate limiter set: "
            f"{config.max_calls} calls per {config.period_seconds}s"
        )
        return _global_llm_rate_limiter


def disable_global_rate_limiter() -> None:
    """Disable the global rate limiter."""
    global _global_llm_rate_limiter
    with _global_lock:
        _global_llm_rate_limiter = None
        logger.info("Global LLM rate limiter disabled.")
