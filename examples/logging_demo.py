"""
Demo: Structured Logging for Flows and Tasks

Demonstrates:
1. Flow start/end logging
2. Task execution time logging
3. Error and retry logging
4. Local log storage (JSONL format)
"""

import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from framework import (
    Flow,
    FunctionTask,
    FlowLogger,
    get_flow_logger,
    flow_logger
)
from pathlib import Path


def divider(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)


# =============================================================================
# 1. Basic Flow with Logging
# =============================================================================
divider("1. Basic Flow with Structured Logging")

def step_one(ctx):
    time.sleep(0.1)
    return {"step": 1, "data": "Hello from step 1"}

def step_two(ctx):
    time.sleep(0.15)
    result = ctx.get("step_one_result", {})
    return {"step": 2, "previous": result.get("data")}

def step_three(ctx):
    time.sleep(0.05)
    return {"step": 3, "status": "complete"}

# Create flow
flow = Flow("basic_logging_demo")
flow.add_tasks(
    FunctionTask("step_one", step_one),
    FunctionTask("step_two", step_two),
    FunctionTask("step_three", step_three)
)
flow.chain("step_one", "step_two", "step_three")

# Execute flow (logs are automatically captured)
result = flow.execute({})

print(f"\nFlow completed: {result.success}")
print(f"Execution time: {result.execution_time:.3f}s")


# =============================================================================
# 2. Flow with Retries (Logging Retry Events)
# =============================================================================
divider("2. Flow with Retry Logging")

# Counter to simulate intermittent failures
failure_counter = {"count": 0}

def flaky_task(ctx):
    """Task that fails first 2 times, then succeeds."""
    failure_counter["count"] += 1
    if failure_counter["count"] <= 2:
        raise RuntimeError(f"Simulated failure #{failure_counter['count']}")
    return {"success": True, "attempts": failure_counter["count"]}

# Create flow with retry-enabled task
retry_flow = Flow("retry_demo")
retry_flow.add_task(
    FunctionTask(
        "flaky_operation",
        flaky_task,
        max_retries=3,
        retry_delay=0.5  # Short delay for demo
    )
)

# Execute (will retry and eventually succeed)
failure_counter["count"] = 0  # Reset counter
result = retry_flow.execute({})

print(f"\nFlow completed: {result.success}")
print(f"Retries used: {result.task_results.get('flaky_operation', {}).retries_used}")


# =============================================================================
# 3. Flow with Errors (Logging Error Events)
# =============================================================================
divider("3. Flow with Error Logging")

def failing_task(ctx):
    """Task that always fails."""
    raise ValueError("This task always fails!")

error_flow = Flow("error_demo")
error_flow.add_task(
    FunctionTask(
        "always_fails",
        failing_task,
        max_retries=1,
        retry_delay=0.2
    )
)

# Execute (will fail)
result = error_flow.execute({})

print(f"\nFlow completed: {result.success}")
print(f"Errors: {result.errors}")


# =============================================================================
# 4. Parallel Flow with Logging
# =============================================================================
divider("4. Parallel Flow Logging")

def parallel_task_a(ctx):
    time.sleep(random.uniform(0.1, 0.2))
    return {"task": "A", "result": "completed"}

def parallel_task_b(ctx):
    time.sleep(random.uniform(0.1, 0.2))
    return {"task": "B", "result": "completed"}

def parallel_task_c(ctx):
    time.sleep(random.uniform(0.05, 0.1))
    return {"task": "C", "result": "completed"}

def final_aggregator(ctx):
    a_result = ctx.get("task_a_result", {})
    b_result = ctx.get("task_b_result", {})
    c_result = ctx.get("task_c_result", {})
    return {
        "aggregated": [a_result, b_result, c_result],
        "count": 3
    }

parallel_flow = Flow("parallel_demo", max_workers=3)
parallel_flow.add_tasks(
    FunctionTask("task_a", parallel_task_a),
    FunctionTask("task_b", parallel_task_b),
    FunctionTask("task_c", parallel_task_c),
    FunctionTask("aggregator", final_aggregator)
)

# task_a, task_b, task_c run in parallel, then aggregator runs
parallel_flow.add_dependency("aggregator", "task_a")
parallel_flow.add_dependency("aggregator", "task_b")
parallel_flow.add_dependency("aggregator", "task_c")

result = parallel_flow.execute({}, parallel=True)

print(f"\nFlow completed: {result.success}")
print(f"Total execution time: {result.execution_time:.3f}s")


# =============================================================================
# 5. View Stored Logs
# =============================================================================
divider("5. Viewing Stored Logs")

# Get the flow logger instance
logger = get_flow_logger()

print(f"Log directory: {logger.log_dir}")
print(f"Aggregated log file: {logger._all_flows_log}")

# Check if log files exist
if logger._all_flows_log.exists():
    print(f"\n[OK] Log file exists")
    
    # Count log entries
    with open(logger._all_flows_log, "r") as f:
        lines = f.readlines()
    print(f"  Total log entries: {len(lines)}")
    
    # Show recent logs
    recent_logs = logger.get_recent_logs(limit=5)
    print(f"\nRecent log entries:")
    for log in recent_logs:
        event = log.get("event_type", "UNKNOWN")
        msg = log.get("message", "")
        ts = log.get("timestamp", "")[:19]
        print(f"  [{ts}] {event}: {msg[:50]}...")

# Get error summary
error_summary = logger.get_error_summary()
print(f"\nError Summary:")
print(f"  Total errors: {error_summary['total_errors']}")
print(f"  By type: {error_summary['by_type']}")


# =============================================================================
# 6. View Flow-Specific Logs
# =============================================================================
divider("6. Flow-Specific Logs")

# Get logs for the retry demo flow
flow_logs = logger.get_flow_logs("retry_demo", retry_flow.flow_id)
if flow_logs:
    print(f"Logs for 'retry_demo' flow ({retry_flow.flow_id[:8]}...):")
    for log in flow_logs:
        event = log.get("event_type", "UNKNOWN")
        level = log.get("level", "INFO")
        msg = log.get("message", "")
        print(f"  [{level:7}] {event}: {msg}")
else:
    print("No flow-specific logs found")


# =============================================================================
# Summary
# =============================================================================
divider("Summary")

print("""
Structured Logging Features Demonstrated:

[OK] FLOW_START  - Logged when flow execution begins
[OK] FLOW_END    - Logged when flow execution completes/fails  
[OK] TASK_START  - Logged when each task begins
[OK] TASK_END    - Logged when each task completes/fails
[OK] TASK_RETRY  - Logged when task retries after failure
[OK] ERROR       - Logged when errors occur

Log Storage:
  - logs/flows/all_flows.jsonl     (all flow logs)
  - logs/flows/<flow_name>/<id>.jsonl (per-flow logs)

Log Format: JSON Lines (JSONL) - one JSON object per line
""")

print("[OK] All logging demos completed!")
