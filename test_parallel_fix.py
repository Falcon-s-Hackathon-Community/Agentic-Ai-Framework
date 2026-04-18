import sys
sys.path.insert(0, '.')

from framework.orchestrator import create_orchestrator

YAML = """
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

orc = create_orchestrator()
orc.register_function("always_fail",            lambda ctx: (_ for _ in ()).throw(RuntimeError("intentional failure")))
orc.register_function("should_be_skipped",      lambda ctx: "this should never run")
orc.register_function("should_also_be_skipped", lambda ctx: "this should never run either")
orc.register_function("independent_task",       lambda ctx: "independent ran fine")

# Use parse_yaml directly to avoid the path-detection heuristic in load_flow
flow_def = orc.parser.parse_yaml(YAML)
state = orc.execute(flow_def, parallel=True)

print("\n=== Results ===")
for task_name, task_state in state.task_states.items():
    print(f"  {task_name}: {task_state['status']}")

print(f"\nWorkflow status: {state.status.value}")
print(f"Errors recorded: {len(state.errors)}")
for err in state.errors:
    print(f"  - {err}")

assert state.task_states["task_a"]["status"] == "failed",    "task_a should be failed"
assert state.task_states["task_b"]["status"] == "skipped",   "task_b should be skipped"
assert state.task_states["task_c"]["status"] == "skipped",   "task_c should be skipped"
assert state.task_states["task_d"]["status"] == "completed", "task_d (independent) should complete"
assert "Deadlock" not in str(state.errors),                  "No false deadlock error should appear"

print("\nAll assertions passed. Bug is fixed.")
