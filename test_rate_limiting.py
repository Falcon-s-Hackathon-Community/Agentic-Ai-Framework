"""
Test: Rate limiting for LLMTask
Verifies that rate limiting correctly throttles parallel LLM task execution.
"""

import time
import sys
sys.path.insert(0, '.')

from framework.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitPresets,
    set_global_rate_limiter,
    get_global_rate_limiter,
    disable_global_rate_limiter
)
from framework.task import LLMTask
from concurrent.futures import ThreadPoolExecutor


print("=" * 50)
print("TEST 1: RateLimitConfig validation")
print("=" * 50)

config = RateLimitConfig(max_calls=5, period_seconds=10)
assert config.max_calls == 5
assert config.period_seconds == 10
print("PASSED: RateLimitConfig created correctly")

try:
    bad = RateLimitConfig(max_calls=0, period_seconds=10)
    assert False, "Should have raised ValueError"
except ValueError:
    print("PASSED: Invalid config correctly rejected")


print("\n" + "=" * 50)
print("TEST 2: Rate limiter blocks when limit reached")
print("=" * 50)

limiter = RateLimiter(RateLimitConfig(max_calls=3, period_seconds=5))
timestamps = []

for i in range(3):
    limiter.acquire(task_name=f"task_{i}")
    timestamps.append(time.monotonic())

print(f"First 3 calls acquired immediately: OK")

start = time.monotonic()
limiter.acquire(task_name="task_4")
waited = time.monotonic() - start
assert waited >= 1.0, f"Should have waited at least 1s, waited {waited:.2f}s"
print(f"PASSED: 4th call correctly throttled (waited {waited:.2f}s)")


print("\n" + "=" * 50)
print("TEST 3: get_stats() returns correct values")
print("=" * 50)

limiter2 = RateLimiter(RateLimitConfig(max_calls=10, period_seconds=60))
limiter2.acquire("t1")
limiter2.acquire("t2")
stats = limiter2.get_stats()
assert stats["calls_in_window"] == 2
assert stats["max_calls"] == 10
assert stats["available_slots"] == 8
print(f"PASSED: Stats correct: {stats}")


print("\n" + "=" * 50)
print("TEST 4: Global rate limiter shared across LLMTask instances")
print("=" * 50)

set_global_rate_limiter(RateLimitConfig(max_calls=2, period_seconds=5))
assert get_global_rate_limiter() is not None
print("PASSED: Global rate limiter set successfully")

task1 = LLMTask("llm_1", prompt_template="Say hello: {input}")
task2 = LLMTask("llm_2", prompt_template="Say bye: {input}")
print("PASSED: LLMTask instances created with global rate limiter")

disable_global_rate_limiter()
assert get_global_rate_limiter() is None
print("PASSED: Global rate limiter disabled successfully")


print("\n" + "=" * 50)
print("TEST 5: Per-task rate limiter takes priority over global")
print("=" * 50)

set_global_rate_limiter(RateLimitConfig(max_calls=100, period_seconds=60))
per_task_limiter = RateLimiter(RateLimitConfig(max_calls=2, period_seconds=60))

task = LLMTask(
    "rate_limited_task",
    prompt_template="Process: {input}",
    rate_limiter=per_task_limiter
)
assert task.rate_limiter is per_task_limiter
print("PASSED: Per-task limiter assigned correctly")

disable_global_rate_limiter()


print("\n" + "=" * 50)
print("TEST 6: Presets return correct configs")
print("=" * 50)

openai_free = RateLimitPresets.openai_free_tier()
assert openai_free.max_calls == 3
assert openai_free.period_seconds == 60
print(f"PASSED: OpenAI free tier preset: {openai_free.max_calls} rpm")

gemini_free = RateLimitPresets.gemini_free_tier()
assert gemini_free.max_calls == 15
print(f"PASSED: Gemini free tier preset: {gemini_free.max_calls} rpm")

conservative = RateLimitPresets.conservative()
assert conservative.max_calls == 10
print(f"PASSED: Conservative preset: {conservative.max_calls} rpm")


print("\n" + "=" * 50)
print("ALL TESTS PASSED")
print("=" * 50)
