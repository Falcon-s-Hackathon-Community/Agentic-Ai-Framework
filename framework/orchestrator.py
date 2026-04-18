"""
Lightweight Orchestrator Module
Parses flow YAML, resolves dependencies, executes tasks in topological order,
and persists task state after execution.
"""

import json
import yaml
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .task import Task, TaskStatus, TaskResult, FunctionTask, LLMTask, ToolTask, ConditionalTask
from .tools import ToolRegistry, tool_registry
from .memory import MemoryStore, get_memory_store, FileBackend

logger = logging.getLogger(__name__)


class WorkflowStatus(Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class WorkflowState:
    """Persistent state for a workflow execution."""
    workflow_id: str
    name: str
    status: WorkflowStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    task_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "task_states": self.task_states,
            "context": self.context,
            "errors": self.errors
        }
    
    def to_summary_dict(self) -> Dict[str, Any]:
        """Returns a stringified/truncated version of the state for logging/UI."""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "status": self.status.value,
            "context": {k: str(v)[:500] for k, v in self.context.items()},
            "errors": self.errors
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        return cls(
            workflow_id=data["workflow_id"],
            name=data["name"],
            status=WorkflowStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            task_states=data.get("task_states", {}),
            context=data.get("context", {}),
            errors=data.get("errors", [])
        )


@dataclass
class TaskDefinition:
    """Definition of a task from YAML."""
    name: str
    type: str  # "function", "llm", "tool"
    dependencies: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    retry_config: Dict[str, Any] = field(default_factory=dict)


class StateStore:
    """
    Persistent state storage for workflow and task states.
    Supports both in-memory and file-based persistence.
    """
    
    def __init__(self, persist_path: Optional[Path] = None):
        self._states: Dict[str, WorkflowState] = {}
        self.persist_path = persist_path
        self._lock = threading.RLock()
        
        if persist_path:
            self._load_states()
    
    def _load_states(self) -> None:
        """Load states from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return
        
        try:
            with open(self.persist_path, 'r') as f:
                data = json.load(f)
                for wf_id, state_dict in data.items():
                    self._states[wf_id] = WorkflowState.from_dict(state_dict)
            logger.info(f"Loaded {len(self._states)} workflow states from {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to load states: {e}")
    
    def _save_states(self) -> None:
        """Persist states to disk."""
        if not self.persist_path:
            return
        
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persist_path, 'w') as f:
                data = {wf_id: state.to_dict() for wf_id, state in self._states.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save states: {e}")
    
    def save_workflow_state(self, state: WorkflowState) -> None:
        """Save or update workflow state."""
        with self._lock:
            self._states[state.workflow_id] = state
            self._save_states()
    
    def get_workflow_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state by ID."""
        return self._states.get(workflow_id)
    
    def update_task_state(
        self,
        workflow_id: str,
        task_name: str,
        status: str,
        result: Any = None,
        error: str = None
    ) -> None:
        """Update task state within a workflow."""
        with self._lock:
            state = self._states.get(workflow_id)
            if state:
                state.task_states[task_name] = {
                    "status": status,
                    "result": result,
                    "error": error,
                    "updated_at": datetime.now().isoformat()
                }
                self._save_states()
    
    def list_workflows(self, status: Optional[WorkflowStatus] = None) -> List[WorkflowState]:
        """List all workflows, optionally filtered by status."""
        if status:
            return [s for s in self._states.values() if s.status == status]
        return list(self._states.values())


class FlowParser:
    """
    Parses YAML flow definitions into executable task graphs.
    
    YAML Format:
    ```yaml
    name: my_workflow
    description: A sample workflow
    
    tasks:
      task1:
        type: function
        config:
          function: process_data
        
      task2:
        type: tool
        depends_on: [task1]
        config:
          tool_name: web_search
          
      task3:
        type: llm
        depends_on: [task1, task2]
        config:
          prompt_template: "Summarize: {input}"
        retry:
          max_retries: 3
          retry_delay: 1.0
    ```
    """
    
    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.tools = tool_registry or ToolRegistry.get_instance()
        self._function_registry: Dict[str, Callable] = {}
    
    def register_function(self, name: str, func: Callable) -> None:
        """Register a function for use in function tasks."""
        self._function_registry[name] = func
    
    def parse_file(self, filepath: Union[str, Path]) -> Dict[str, Any]:
        """Parse a YAML flow file."""
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Flow file not found: {filepath}")
        
        with open(filepath, 'r') as f:
            return self.parse_yaml(f.read())
    
    def parse_yaml(self, yaml_content: str) -> Dict[str, Any]:
        """Parse YAML content into a flow definition."""
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")
        
        # Validate required fields
        if "name" not in data:
            raise ValueError("Flow must have a 'name' field")
        if "tasks" not in data or not data["tasks"]:
            raise ValueError("Flow must have at least one task")
        
        # Parse task definitions
        tasks = {}
        for task_name, task_config in data["tasks"].items():
            tasks[task_name] = self._parse_task(task_name, task_config)
        
        return {
            "name": data["name"],
            "description": data.get("description", ""),
            "tasks": tasks,
            "config": data.get("config", {})
        }
    
    def _parse_task(self, name: str, config: Dict[str, Any]) -> TaskDefinition:
        """Parse a single task definition."""
        task_type = config.get("type", "function")
        dependencies = config.get("depends_on", [])
        
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        
        retry_config = config.get("retry", {})
        task_config = config.get("config", {})
        
        return TaskDefinition(
            name=name,
            type=task_type,
            dependencies=dependencies,
            config=task_config,
            retry_config=retry_config
        )
    
    def create_tasks(
        self,
        flow_def: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Dict[str, Task]:
        """Create executable Task objects from flow definition."""
        tasks = {}
        task_defs: Dict[str, TaskDefinition] = flow_def["tasks"]
        
        for name, task_def in task_defs.items():
            task = self._create_task(task_def, context or {})
            
            # Set up dependencies
            for dep in task_def.dependencies:
                task.add_dependency(dep)
            
            tasks[name] = task
        
        # Set up dependents (reverse mapping)
        for name, task_def in task_defs.items():
            for dep in task_def.dependencies:
                if dep in tasks:
                    tasks[dep].add_dependent(name)
        
        return tasks
    
    def _create_task(self, task_def: TaskDefinition, context: Dict[str, Any]) -> Task:
        """Create a Task instance from TaskDefinition."""
        retry_config = task_def.retry_config
        max_retries = retry_config.get("max_retries", 3)
        retry_delay = retry_config.get("retry_delay", 1.0)
        
        if task_def.type == "function":
            func_name = task_def.config.get("function", "noop")
            func = self._function_registry.get(func_name, lambda ctx: None)
            
            return FunctionTask(
                name=task_def.name,
                func=func,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
        
        elif task_def.type == "tool":
            tool_name = task_def.config.get("tool_name", "noop")
            tool_args = task_def.config.get("args", {})
            
            return ToolTask(
                name=task_def.name,
                tool_name=tool_name,
                tool_registry=self.tools,
                tool_args=tool_args,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
        
        elif task_def.type == "llm":
            prompt_template = task_def.config.get("prompt_template", "{input}")
            llm_handler = task_def.config.get("handler")
            
            return LLMTask(
                name=task_def.name,
                prompt_template=prompt_template,
                llm_handler=llm_handler,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
        
        elif task_def.type == "conditional":
            condition_name = task_def.config.get("condition")
            if not condition_name:
                raise ValueError(f"Conditional task '{task_def.name}' must specify a 'condition' function")
                
            condition_func = self._function_registry.get(condition_name)
            if not condition_func:
                raise ValueError(f"Condition function '{condition_name}' not found for task '{task_def.name}'")
                
            return ConditionalTask(
                name=task_def.name,
                condition=condition_func,
                true_task=task_def.config.get("true_task"),
                false_task=task_def.config.get("false_task"),
                max_retries=max_retries,
                retry_delay=retry_delay
            )
        
        else:
            raise ValueError(f"Unknown task type: {task_def.type}")


class Orchestrator:
    """
    Lightweight workflow orchestrator.
    
    Features:
    - Parse flow definitions from YAML
    - Resolve task dependencies using topological sort
    - Execute tasks in correct order (parallel when possible)
    - Persist workflow and task state
    - Support for resuming failed workflows
    """
    
    def __init__(
        self,
        state_store: Optional[StateStore] = None,
        memory_store: Optional[MemoryStore] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_workers: int = 4,
        persist_path: Optional[Path] = None
    ):
        self.state_store = state_store or StateStore(persist_path)
        self.memory = memory_store or get_memory_store()
        self.tools = tool_registry or ToolRegistry.get_instance()
        self.max_workers = max_workers
        
        self.parser = FlowParser(self.tools)
        self._active_workflows: Dict[str, WorkflowState] = {}
        self._lock = threading.RLock()
        
        logger.info("Orchestrator initialized")
    
    def register_function(self, name: str, func: Callable) -> "Orchestrator":
        """Register a function for use in flows."""
        self.parser.register_function(name, func)
        return self
    
    def load_flow(self, yaml_source: Union[str, Path]) -> Dict[str, Any]:
        """
        Load a flow definition from YAML file or string.
        
        Args:
            yaml_source: Path to YAML file or YAML string
            
        Returns:
            Parsed flow definition
        """
        if isinstance(yaml_source, Path) or (
            isinstance(yaml_source, str) and Path(yaml_source).exists()
        ):
            return self.parser.parse_file(yaml_source)
        else:
            return self.parser.parse_yaml(yaml_source)
    
    def execute(
        self,
        flow_def: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None,
        parallel: bool = True
    ) -> WorkflowState:
        """
        Execute a workflow from a flow definition.
        
        Args:
            flow_def: Parsed flow definition
            context: Initial execution context
            workflow_id: Optional workflow ID (generated if not provided)
            parallel: Enable parallel task execution
            
        Returns:
            Final WorkflowState
        """
        # Ensure workflow_id is set
        workflow_id = workflow_id or str(uuid.uuid4())
        context = context or {}
        
        # Initialize or Load workflow state
        state = self.state_store.get_workflow_state(workflow_id)
        if not state:
            state = WorkflowState(
                workflow_id=workflow_id,
                name=flow_def["name"],
                status=WorkflowStatus.PENDING,
                created_at=datetime.now(),
                context=context.copy()
            )
            self.state_store.save_workflow_state(state)
            logger.info(f"Starting workflow '{flow_def['name']}' (ID: {workflow_id})")
        else:
            logger.info(f"Resuming workflow '{flow_def['name']}' (ID: {workflow_id}) from existing state")
            # Clear previous errors and reset status for the new attempt
            state.errors = []
            state.status = WorkflowStatus.RUNNING
            state.completed_at = None
            if context:
                state.context.update(context)
            self.state_store.save_workflow_state(state)
        
        try:
            # Create executable tasks
            tasks = self.parser.create_tasks(flow_def, context)
            
            # Validate and get execution order
            execution_order = self._topological_sort(tasks)
            logger.debug(f"Execution order: {execution_order}")
            
            # Update state to running
            state.status = WorkflowStatus.RUNNING
            state.started_at = datetime.now()
            self.state_store.save_workflow_state(state)
            
            # Execute tasks
            if parallel:
                state = self._execute_parallel(state, tasks, context)
            else:
                state = self._execute_sequential(state, tasks, execution_order, context)
            
            # Finalize state
            state.completed_at = datetime.now()
            if state.errors:
                state.status = WorkflowStatus.FAILED
            else:
                state.status = WorkflowStatus.COMPLETED
            
            self.state_store.save_workflow_state(state)
            logger.info(f"Workflow '{flow_def['name']}' {state.status.value}")
            
        except Exception as e:
            state.status = WorkflowStatus.FAILED
            state.errors.append(str(e))
            state.completed_at = datetime.now()
            self.state_store.save_workflow_state(state)
            logger.error(f"Workflow failed: {e}")
        
        return state
    
    def execute_yaml(
        self,
        yaml_source: Union[str, Path],
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> WorkflowState:
        """
        Load and execute a workflow from YAML.
        
        Args:
            yaml_source: Path to YAML file or YAML string
            context: Initial execution context
            **kwargs: Additional arguments for execute()
            
        Returns:
            Final WorkflowState
        """
        flow_def = self.load_flow(yaml_source)
        return self.execute(flow_def, context, **kwargs)
    
    def resume(self, workflow_id: str, yaml_source: Optional[Union[str, Path]] = None) -> Optional[WorkflowState]:
        """
        Resume a paused or failed workflow.
        
        Args:
            workflow_id: ID of workflow to resume
            
        Returns:
            Updated WorkflowState or None if not found
        """
        state = self.state_store.get_workflow_state(workflow_id)
        if not state:
            logger.error(f"Workflow {workflow_id} not found")
            return None
        
        if state.status == WorkflowStatus.COMPLETED:
            logger.warning(f"Workflow {workflow_id} already completed")
            return state
        
        logger.info(f"Resuming workflow {workflow_id}")
        
        # Determine the flow definition
        flow_def = None
        if yaml_source:
            flow_def = self.load_flow(yaml_source)
        
        if not flow_def:
            # Try to reconstruct tasks or find def? 
            # For now, require yaml_source for resume if not in memory
            logger.error("YAML source required to resume workflow (task definitions not in state)")
            return state

        # Merge context from state
        current_context = state.context.copy()
        
        # Reset errors for the new run
        state.errors = []
        state.status = WorkflowStatus.RUNNING
        self.state_store.save_workflow_state(state)
        
        return self.execute(flow_def, current_context, workflow_id=workflow_id)
    
    def _topological_sort(self, tasks: Dict[str, Task]) -> List[str]:
        """
        Perform topological sort to determine task execution order.
        
        Args:
            tasks: Dictionary of task name to Task
            
        Returns:
            List of task names in execution order
            
        Raises:
            ValueError: If cycle detected in dependencies
        """
        in_degree = {name: len(task.dependencies) for name, task in tasks.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            current = queue.pop(0)
            result.append(current)
            
            for dependent in tasks[current].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        if len(result) != len(tasks):
            raise ValueError("Cycle detected in task dependencies")
        
        return result
    
    def _execute_sequential(
        self,
        state: WorkflowState,
        tasks: Dict[str, Task],
        execution_order: List[str],
        context: Dict[str, Any]
    ) -> WorkflowState:
        """Execute tasks sequentially in topological order."""
        # Track actual results (not stringified versions)
        actual_results: Dict[str, Any] = {
            name: s.get("result") for name, s in state.task_states.items()
            if s.get("status") == "completed" and "result" in s
        }
        
        # Ensure context is updated with existing results
        for name, result in actual_results.items():
            state.context[f"{name}_result"] = result
            context[f"{name}_result"] = result
        
        for task_name in execution_order:
            task = tasks[task_name]
            
            # Build task context with results from dependencies
            task_context = context.copy()
            for dep in task.dependencies:
                if dep in actual_results:
                    task_context[f"{dep}_result"] = actual_results[dep]
            
            # Skip if already completed (for resume)
            if state.task_states.get(task_name, {}).get("status") == "completed":
                # Ensure result is in context for downstream tasks
                result_data = state.task_states[task_name].get("result")
                if result_data is not None:
                    actual_results[task_name] = result_data
                    state.context[f"{task_name}_result"] = result_data
                    context[f"{task_name}_result"] = result_data
                logger.info(f"Skipping already completed task: {task_name}")
                continue

            # Update state: task starting
            self.state_store.update_task_state(
                state.workflow_id, task_name, "running"
            )
            
            logger.info(f"Executing task: {task_name}")
            result = task.execute(task_context)
            
            # Update state: task completed
            if result.success:
                actual_results[task_name] = result.output
                self.state_store.update_task_state(
                    state.workflow_id, task_name, "completed",
                    result=result.output
                )
                state.context[f"{task_name}_result"] = result.output
                context[f"{task_name}_result"] = result.output  # Update running context
                
                # Store in memory
                self.memory.store_result(task_name, result.output, state.workflow_id)

                # Special handling for ConditionalTask: skip the unselected branch
                if task.task_type == "conditional" and isinstance(result.output, dict):
                    next_task = result.output.get("next_task")
                    true_task = getattr(task, "true_task", None)
                    false_task = getattr(task, "false_task", None)
                    
                    # Determine which task to skip
                    to_skip = None
                    if next_task == true_task:
                        to_skip = false_task
                    elif next_task == false_task:
                        to_skip = true_task
                    
                    if to_skip and to_skip in tasks:
                        logger.info(f"Condition evaluated to {result.output.get('condition_result')}, skipping branch: {to_skip}")
                        # Propagate skip
                        skip_queue = [to_skip]
                        while skip_queue:
                            s_name = skip_queue.pop(0)
                            if s_name not in actual_results: # Don't skip if already run (shouldn't happen in DAG)
                                self.state_store.update_task_state(
                                    state.workflow_id, s_name, "skipped",
                                    error=f"Skipped by conditional task '{task_name}'"
                                )
                                execution_order = [t for t in execution_order if t != s_name]
                                if s_name in tasks:
                                    skip_queue.extend(tasks[s_name].dependents)
            else:
                self.state_store.update_task_state(
                    state.workflow_id, task_name, "failed",
                    error=result.error
                )
                state.errors.append(f"Task '{task_name}' failed: {result.error}")
                break  # Stop on failure
            
            # Refresh state from store
            state = self.state_store.get_workflow_state(state.workflow_id) or state
        
        return state
    
    def _execute_parallel(
        self,
        state: WorkflowState,
        tasks: Dict[str, Task],
        context: Dict[str, Any]
    ) -> WorkflowState:
        """Execute tasks in parallel where dependencies allow."""
        # Initialize from existing state (for resume)
        completed: Set[str] = {
            name for name, s in state.task_states.items() 
            if s.get("status") == "completed"
        }
        # failed set should track failures IN THE CURRENT RUN ONLY.
        failed: Set[str] = set()
        # Track actual results (not stringified versions)
        actual_results: Dict[str, Any] = {
            name: s.get("result") for name, s in state.task_states.items()
            if s.get("status") == "completed" and "result" in s
        }
        
        # Ensure context is updated with existing results
        for name, result in actual_results.items():
            state.context[f"{name}_result"] = result
            context[f"{name}_result"] = result
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while len(completed) + len(failed) < len(tasks):
                # Find tasks ready to execute (skip already failed/skipped tasks)
                ready = [
                    name for name, task in tasks.items()
                    if name not in completed
                    and name not in failed
                    and task.status == TaskStatus.PENDING
                    and all(dep in completed for dep in task.dependencies)
                ]
                
                if not ready:
                    # Only flag a deadlock if there are tasks that are truly
                    # pending (not failed/skipped) and cannot proceed
                    truly_pending = [
                        n for n in tasks
                        if n not in completed and n not in failed
                    ]
                    if truly_pending:
                        state.errors.append(
                            f"Deadlock detected: tasks {truly_pending} cannot proceed. "
                            f"Check for circular dependencies."
                        )
                    break
                
                # Submit ready tasks
                futures = {}
                for task_name in ready:
                    task = tasks[task_name]
                    task.status = TaskStatus.RUNNING
                    
                    # Build task context with actual results
                    task_context = context.copy()
                    for dep in task.dependencies:
                        if dep in actual_results:
                            task_context[f"{dep}_result"] = actual_results[dep]
                    
                    self.state_store.update_task_state(
                        state.workflow_id, task_name, "running"
                    )
                    
                    future = executor.submit(task.execute, task_context)
                    futures[future] = task_name
                
                # Wait for batch completion
                for future in as_completed(futures):
                    task_name = futures[future]
                    
                    try:
                        result = future.result()
                        
                        if result.success:
                            completed.add(task_name)
                            actual_results[task_name] = result.output
                            self.state_store.update_task_state(
                                state.workflow_id, task_name, "completed",
                                result=result.output
                            )
                            state.context[f"{task_name}_result"] = result.output
                            context[f"{task_name}_result"] = result.output  # Update running context
                            self.memory.store_result(task_name, result.output, state.workflow_id)
                            logger.info(f"Task '{task_name}' completed")
                        else:
                            self.state_store.update_task_state(
                                state.workflow_id, task_name, "failed",
                                error=result.error
                            )
                            state.errors.append(f"Task '{task_name}' failed: {result.error}")
                            logger.error(f"Task '{task_name}' failed: {result.error}")
                            
                            # Propagate skip to all downstream dependents
                            failed.add(task_name)
                            skip_queue = list(tasks[task_name].dependents)
                            while skip_queue:
                                skip_name = skip_queue.pop(0)
                                if skip_name not in failed:
                                    failed.add(skip_name)
                                    self.state_store.update_task_state(
                                        state.workflow_id, skip_name, "skipped",
                                        error=f"Skipped because dependency '{task_name}' failed"
                                    )
                                    state.errors.append(
                                        f"Task '{skip_name}' skipped: dependency '{task_name}' failed"
                                    )
                                    logger.warning(
                                        f"Task '{skip_name}' skipped due to failed dependency '{task_name}'"
                                    )
                                    if skip_name in tasks:
                                        skip_queue.extend(tasks[skip_name].dependents)
                        
                        # Special handling for ConditionalTask: skip the unselected branch
                        if task.task_type == "conditional" and isinstance(result.output, dict):
                            next_task = result.output.get("next_task")
                            true_task = getattr(task, "true_task", None)
                            false_task = getattr(task, "false_task", None)
                            
                            to_skip = None
                            if next_task == true_task:
                                to_skip = false_task
                            elif next_task == false_task:
                                to_skip = true_task
                            
                            if to_skip and to_skip in tasks and to_skip not in completed and to_skip not in failed:
                                logger.info(f"Condition evaluated to {result.output.get('condition_result')}, skipping branch: {to_skip}")
                                failed.add(to_skip) # Using failed as a way to mark skipped in the while loop condition
                                skip_queue = [to_skip]
                                while skip_queue:
                                    s_name = skip_queue.pop(0)
                                    if s_name not in completed:
                                        failed.add(s_name)
                                        self.state_store.update_task_state(
                                            state.workflow_id, s_name, "skipped",
                                            error=f"Skipped by conditional task '{task_name}'"
                                        )
                                        if s_name in tasks:
                                            skip_queue.extend(tasks[s_name].dependents)
                    
                    except Exception as e:
                        self.state_store.update_task_state(
                            state.workflow_id, task_name, "failed",
                            error=str(e)
                        )
                        state.errors.append(f"Task '{task_name}' exception: {e}")
                        
                        # Propagate skip to all downstream dependents
                        failed.add(task_name)
                        skip_queue = list(tasks[task_name].dependents)
                        while skip_queue:
                            skip_name = skip_queue.pop(0)
                            if skip_name not in failed:
                                failed.add(skip_name)
                                self.state_store.update_task_state(
                                    state.workflow_id, skip_name, "skipped",
                                    error=f"Skipped because dependency '{task_name}' failed"
                                )
                                state.errors.append(
                                    f"Task '{skip_name}' skipped: dependency '{task_name}' failed"
                                )
                                logger.warning(
                                    f"Task '{skip_name}' skipped due to failed dependency '{task_name}'"
                                )
                                if skip_name in tasks:
                                    skip_queue.extend(tasks[skip_name].dependents)
                
                # Refresh state
                state = self.state_store.get_workflow_state(state.workflow_id) or state
        
        return state
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a workflow."""
        state = self.state_store.get_workflow_state(workflow_id)
        return state.to_dict() if state else None
    
    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None
    ) -> List[Dict[str, Any]]:
        """List all workflows, optionally filtered by status."""
        states = self.state_store.list_workflows(status)
        return [s.to_dict() for s in states]


# Factory function
def create_orchestrator(
    persist_path: Optional[str] = None,
    max_workers: int = 4
) -> Orchestrator:
    """
    Create an orchestrator instance.
    
    Args:
        persist_path: Path for state persistence (optional)
        max_workers: Maximum parallel workers
        
    Returns:
        Configured Orchestrator
    """
    path = Path(persist_path) if persist_path else None
    return Orchestrator(persist_path=path, max_workers=max_workers)


# Example YAML workflow
EXAMPLE_WORKFLOW_YAML = """
name: example_workflow
description: An example workflow demonstrating the orchestrator

tasks:
  fetch_data:
    type: function
    config:
      function: fetch_data
    retry:
      max_retries: 2
      retry_delay: 1.0

  process_data:
    type: function
    depends_on: [fetch_data]
    config:
      function: process_data

  analyze:
    type: tool
    depends_on: [process_data]
    config:
      tool_name: sentiment_analysis
      args:
        text: "{process_data_result}"

  summarize:
    type: llm
    depends_on: [analyze]
    config:
      prompt_template: "Summarize the following analysis: {analyze_result}"
    retry:
      max_retries: 3
"""