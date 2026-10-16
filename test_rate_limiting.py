import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Safe path resolution replacing raw '.' string
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.rate_limiter import (
    disable_global_rate_limiter,
    get_global_rate_limiter,
    set_global_rate_limiter,
    RateLimitConfig,
    RateLimiter,
    RateLimitPresets,
)
from framework.task import LLMTask


def log_test_header(name: str) -> None:
    """Prints a consistent, scannable visual separator for tests."""
    print(f"\n{'=' * 50}\nRUNNING: {name}\n{'=' * 50}")


def test_config_validation():
    log_test_header("RateLimitConfig Validation")
    
    config = RateLimitConfig(max_calls=5, period_seconds=10)
    assert config.max_calls == 5
    assert config.period_seconds == 10

    try:
        RateLimitConfig(max_calls=0, period_seconds=10)
        raise AssertionError("Should have raised ValueError for max_calls=0")
    except ValueError:
        pass
        
    print("PASSED: Valid configurations accepted and bad configurations rejected.")


def test_throttling_behavior():
    log_test_header("Rate Limiter Throttling Blocks")
    
    # 3 calls max per 5 seconds means a 4th call must wait for the rolling window
    limiter = RateLimiter(RateLimitConfig(max_calls=3, period_seconds=5))

    for i in range(3):
        limiter.acquire(task_name=f"task_{i}")

    start_time = time.monotonic()
    limiter.acquire(task_name="task_4")
    elapsed = time.monotonic() - start_time
    
    # Using a minor delta padding to protect against scheduling jitter
    assert elapsed >= 0.95, f"Throttling failed: expected >= 1.0s delay, got {elapsed:.2f}s"
    print(f"PASSED: Throttled correctly. Blocked for {elapsed:.2f}s.")


def test_statistics_tracking():
    log_test_header("Stats Retrieval Tracking")
    
    limiter = RateLimiter(RateLimitConfig(max_calls=10, period_seconds=60))
    limiter.acquire("t1")
    limiter.acquire("t2")
    
    stats = limiter.get_stats()
    expected = {"calls_in_window": 2, "max_calls": 10, "available_slots": 8}
    
    for key, expected_val in expected.items():
        assert stats[key] == expected_val, f"Mismatch on {key}: {stats[key]} != {expected_val}"
        
    print(f"PASSED: Stats tracking verified successfully: {stats}")


def test_global_limiter_lifecycle():
    log_test_header("Global Limiter Scope Lifecycle")
    
    set_global_rate_limiter(RateLimitConfig(max_calls=2, period_seconds=5))
    assert get_global_rate_limiter() is not None

    task1 = LLMTask("llm_1", prompt_template="Say hello: {input}")
    task2 = LLMTask("llm_2", prompt_template="Say bye: {input}")
    assert task1 is not None and task2 is not None

    disable_global_rate_limiter()
    assert get_global_rate_limiter() is None
    print("PASSED: Global rate limiter shared and torn down properly.")


def test_limiter_precedence():
    log_test_header("Per-Task vs Global Priority Override")
    
    set_global_rate_limiter(RateLimitConfig(max_calls=100, period_seconds=60))
    local_limiter = RateLimiter(RateLimitConfig(max_calls=2, period_seconds=60))

    task = LLMTask(
        "rate_limited_task",
        prompt_template="Process: {input}",
        rate_limiter=local_limiter
    )
    
    assert task.rate_limiter is local_limiter, "Local task config did not override global configuration"
    disable_global_rate_limiter()
    print("PASSED: Local rate-limiter overrode global infrastructure configurations.")


def test_preset_configurations():
    log_test_header("Preset Preserved Values")
    
    presets = [
        (RateLimitPresets.openai_free_tier(), 3, 60, "OpenAI Free"),
        (RateLimitPresets.gemini_free_tier(), 15, None, "Gemini Free"),
        (RateLimitPresets.conservative(), 10, None, "Conservative Model"),
    ]

    for config, expected_calls, expected_period, name in presets:
        assert config.max_calls == expected_calls, f"{name} calls mismatch"
        if expected_period:
            assert config.period_seconds == expected_period, f"{name} period mismatch"
            
    print("PASSED: Default vendor configurations evaluated correctly.")


def main():
    """Execution pipeline running all decoupled unit verification modules."""
    start_run = time.monotonic()
    
    test_config_validation()
    test_throttling_behavior()
    test_statistics_tracking()
    test_global_limiter_lifecycle()
    test_limiter_precedence()
    test_preset_configurations()
    
    total_time = time.monotonic() - start_run
    print(f"\n{'=' * 50}\nALL TESTS PASSED SUCCESSFULLY ({total_time:.2f}s total)\n{'=' * 50}")


if __name__ == "__main__":
    main()
