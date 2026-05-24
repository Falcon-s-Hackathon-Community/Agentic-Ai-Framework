import sys
from pathlib import Path

# Add current directory to path safely
sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework.orchestrator import create_orchestrator

# Multi-line string cleaned up
YAML_CONFIG = """
name: test_failure_propagation
tasks:
  task_a:
    type: function
    config:
      function: always_fail

  task_b:
    type: function
    depends_on: [task_a]
    config:
      function: should_be_skipped

  task_c:
    type: function
    depends_on: [task_b]
    config:
      function: should_also_be_skipped

  task_d:
    type: function
    config:
      function: independent_task
"""


def raise_failure(ctx):
    """Explicitly raises a runtime error to test failure propagation."""
    raise RuntimeError("intentional failure")


def main():
    # Initialize and configure orchestrator
    orc = create_orchestrator()
    
    # Register functions cleanly using proper callables
    orc.register_function("always_fail", raise_failure)
    orc.register_function("should_be_skipped", lambda ctx: "skipped")
    orc.register_function("should_also_be_skipped", lambda ctx: "skipped")
    orc.register_function("independent_task", lambda ctx: "success")

    # Parse and execute flow
    flow_def = orc.parser.parse_yaml(YAML_CONFIG)
    state = orc.execute(flow_def, parallel=True)

    # Print results summary
    print("\n=== Task Results ===")
    for name, task in state.task_states.items():
        print(f"  {name}: {task['status']}")

    print(f"\nWorkflow overall status: {state.status.value}")
    print(f"Errors recorded: {len(state.errors)}")
    for error in state.errors:
        print(f"  - {error}")

    # Validate state outcomes
    expected_statuses = {
        "task_a": "failed",
        "task_b": "skipped",
        "task_c": "skipped",
        "task_d": "completed",
    }

    for task_name, expected in expected_statuses.items():
        actual = state.task_states[task_name]["status"]
        assert actual == expected, f"{task_name} status was {actual}, expected {expected}"

    assert "Deadlock" not in str(state.errors), "False deadlock detected in error logs"

    print("\nAll assertions passed successfully.")


if __name__ == "__main__":
    main()
