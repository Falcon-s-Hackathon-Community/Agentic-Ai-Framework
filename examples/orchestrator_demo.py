"""
Orchestrator Demo
Demonstrates YAML-based workflow execution with the lightweight orchestrator.
"""

import time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from framework import (
    Orchestrator,
    create_orchestrator,
    tool,
    tool_registry,
    WorkflowStatus
)


# =============================================================================
# DEFINE TOOLS
# =============================================================================

@tool(name="fetch_data", description="Fetch data from a source")
def fetch_data_tool(source: str = "default") -> dict:
    """Simulated data fetching."""
    time.sleep(0.1)
    return {
        "source": source,
        "records": [
            {"id": 1, "name": "Record A", "value": 100},
            {"id": 2, "name": "Record B", "value": 200},
            {"id": 3, "name": "Record C", "value": 300},
        ],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }


@tool(name="transform_records", description="Transform data records")
def transform_records_tool(records = None) -> list:
    """Transform records by normalizing values."""
    # Handle both dict and list inputs
    if isinstance(records, dict):
        records = records.get("records", [])
    records = records or []
    time.sleep(0.05)
    return [
        {**r, "normalized_value": r.get("value", 0) / 100.0}
        for r in records
    ]


@tool(name="aggregate_data", description="Aggregate transformed data")
def aggregate_data_tool(data = None) -> dict:
    """Aggregate data statistics."""
    data = data or []
    time.sleep(0.05)
    values = [d.get("value", 0) for d in data]
    return {
        "count": len(values),
        "sum": sum(values),
        "avg": sum(values) / len(values) if values else 0,
        "min": min(values) if values else 0,
        "max": max(values) if values else 0
    }


# =============================================================================
# WORKFLOW YAML DEFINITIONS
# =============================================================================

# Simple sequential workflow
SEQUENTIAL_WORKFLOW = """
name: sequential_data_pipeline
description: A simple sequential data processing workflow

tasks:
  fetch:
    type: function
    config:
      function: fetch_data
    retry:
      max_retries: 2

  transform:
    type: function
    depends_on: [fetch]
    config:
      function: transform_data

  aggregate:
    type: function
    depends_on: [transform]
    config:
      function: aggregate_data
"""

# Parallel workflow with diamond dependency
PARALLEL_WORKFLOW = """
name: parallel_processing
description: Workflow with parallel execution paths

tasks:
  start:
    type: function
    config:
      function: start_task

  branch_a:
    type: function
    depends_on: [start]
    config:
      function: process_branch_a

  branch_b:
    type: function
    depends_on: [start]
    config:
      function: process_branch_b

  merge:
    type: function
    depends_on: [branch_a, branch_b]
    config:
      function: merge_results
"""

# Tool-based workflow
TOOL_WORKFLOW = """
name: tool_based_pipeline
description: Workflow using registered tools

tasks:
  fetch:
    type: tool
    config:
      tool_name: fetch_data
      args:
        source: "database"

  transform:
    type: tool
    depends_on: [fetch]
    config:
      tool_name: transform_records
      args:
        records: "{fetch_result}"

  aggregate:
    type: tool
    depends_on: [transform]
    config:
      tool_name: aggregate_data
      args:
        data: "{transform_result}"
"""


# =============================================================================
# REGISTER CUSTOM FUNCTIONS
# =============================================================================

def register_functions(orchestrator: Orchestrator):
    """Register custom functions with the orchestrator."""
    
    # Sequential workflow functions
    orchestrator.register_function("fetch_data", lambda ctx: {
        "data": [1, 2, 3, 4, 5],
        "timestamp": time.strftime("%H:%M:%S")
    })
    
    orchestrator.register_function("transform_data", lambda ctx: {
        "transformed": [x * 2 for x in ctx.get("fetch_result", {}).get("data", [])],
        "original_count": len(ctx.get("fetch_result", {}).get("data", []))
    })
    
    orchestrator.register_function("aggregate_data", lambda ctx: {
        "sum": sum(ctx.get("transform_result", {}).get("transformed", [])),
        "count": ctx.get("transform_result", {}).get("original_count", 0)
    })
    
    # Parallel workflow functions
    orchestrator.register_function("start_task", lambda ctx: {
        "initialized": True,
        "context": ctx.get("input", "default")
    })
    
    orchestrator.register_function("process_branch_a", lambda ctx: {
        "branch": "A",
        "result": "Processed by branch A",
        "value": 100
    })
    
    orchestrator.register_function("process_branch_b", lambda ctx: {
        "branch": "B",
        "result": "Processed by branch B",
        "value": 200
    })
    
    orchestrator.register_function("merge_results", lambda ctx: {
        "merged": True,
        "branch_a": ctx.get("branch_a_result", {}),
        "branch_b": ctx.get("branch_b_result", {}),
        "total": (
            ctx.get("branch_a_result", {}).get("value", 0) +
            ctx.get("branch_b_result", {}).get("value", 0)
        )
    })


# =============================================================================
# DEMO RUNNER
# =============================================================================

def run_sequential_demo(orchestrator: Orchestrator):
    """Run sequential workflow demo."""
    print("\n" + "=" * 60)
    print("SEQUENTIAL WORKFLOW DEMO")
    print("=" * 60)
    
    state = orchestrator.execute_yaml(
        SEQUENTIAL_WORKFLOW,
        context={"source": "test"},
        parallel=False
    )
    
    print(f"\nWorkflow: {state.name}")
    print(f"Status: {state.status.value}")
    print(f"Duration: {(state.completed_at - state.started_at).total_seconds():.2f}s")
    
    print("\nTask States:")
    for task_name, task_state in state.task_states.items():
        print(f"  {task_name}: {task_state['status']}")
    
    if state.errors:
        print(f"\nErrors: {state.errors}")


def run_parallel_demo(orchestrator: Orchestrator):
    """Run parallel workflow demo."""
    print("\n" + "=" * 60)
    print("PARALLEL WORKFLOW DEMO")
    print("=" * 60)
    
    state = orchestrator.execute_yaml(
        PARALLEL_WORKFLOW,
        context={"input": "parallel_test"},
        parallel=True
    )
    
    print(f"\nWorkflow: {state.name}")
    print(f"Status: {state.status.value}")
    print(f"Duration: {(state.completed_at - state.started_at).total_seconds():.2f}s")
    
    print("\nTask States:")
    for task_name, task_state in state.task_states.items():
        print(f"  {task_name}: {task_state['status']}")
    
    # Show merge result
    if "merge" in state.task_states:
        merge_result = state.task_states["merge"].get("result")
        print(f"\nMerge Result: {merge_result}")


def run_tool_workflow_demo(orchestrator: Orchestrator):
    """Run tool-based workflow demo."""
    print("\n" + "=" * 60)
    print("TOOL-BASED WORKFLOW DEMO")
    print("=" * 60)
    
    state = orchestrator.execute_yaml(
        TOOL_WORKFLOW,
        context={},
        parallel=False
    )
    
    print(f"\nWorkflow: {state.name}")
    print(f"Status: {state.status.value}")
    
    print("\nTask Results:")
    for task_name, task_state in state.task_states.items():
        print(f"  {task_name}: {task_state['status']}")
        if task_state.get("result"):
            print(f"    Result: {str(task_state['result'])[:100]}...")


def run_persistence_demo(orchestrator: Orchestrator):
    """Demonstrate state persistence."""
    print("\n" + "=" * 60)
    print("STATE PERSISTENCE DEMO")
    print("=" * 60)
    
    # Run a workflow
    state = orchestrator.execute_yaml(
        SEQUENTIAL_WORKFLOW,
        context={"test": "persistence"},
        parallel=False
    )
    
    workflow_id = state.workflow_id
    print(f"\nExecuted workflow: {workflow_id}")
    
    # Query workflow status
    status = orchestrator.get_workflow_status(workflow_id)
    print(f"Persisted Status: {status['status']}")
    print(f"Task Count: {len(status['task_states'])}")
    
    # List all workflows
    workflows = orchestrator.list_workflows()
    print(f"\nTotal Workflows in Store: {len(workflows)}")
    for wf in workflows[-3:]:  # Show last 3
        print(f"  - {wf['name']} ({wf['workflow_id'][:8]}...): {wf['status']}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("LIGHTWEIGHT ORCHESTRATOR DEMO")
    print("=" * 60)
    
    # Create orchestrator with persistence
    persist_path = Path(__file__).parent / "workflow_states.json"
    orchestrator = create_orchestrator(
        persist_path=str(persist_path),
        max_workers=4
    )
    
    # Register functions
    register_functions(orchestrator)
    
    # Run demos
    run_sequential_demo(orchestrator)
    run_parallel_demo(orchestrator)
    run_tool_workflow_demo(orchestrator)
    run_persistence_demo(orchestrator)
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETED")
    print("=" * 60)
    print(f"\nState persisted to: {persist_path}")


if __name__ == "__main__":
    main()
