"""
Flow Module
Provides DAG-based workflow execution with dependency resolution.
"""

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .task import Task, TaskStatus, TaskResult, set_task_flow_logger
from .memory import MemoryStore, get_memory_store
from .tools import ToolRegistry, tool_registry
from .logging import FlowLogger, flow_logger as default_flow_logger

logger = logging.getLogger(__name__)


class FlowStatus(Enum):
    """Enumeration of possible flow states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class FlowResult:
    """Container for flow execution results."""
    success: bool
    flow_id: str
    status: FlowStatus
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class Flow:
    """
    DAG-based workflow execution engine.
    
    Features:
    - Task dependency resolution
    - Parallel execution of independent tasks
    - Conditional branching
    - Error handling and recovery
    - Progress tracking
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        max_workers: int = 4,
        memory_store: Optional[MemoryStore] = None,
        tool_registry: Optional[ToolRegistry] = None,
        flow_logger: Optional[FlowLogger] = None
    ):
        self.name = name
        self.description = description
        self.flow_id = str(uuid.uuid4())
        self.max_workers = max_workers
        
        # Task management
        self._tasks: Dict[str, Task] = {}
        self._entry_tasks: Set[str] = set()  # Tasks with no dependencies
        
        # Execution state
        self.status = FlowStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        
        # Dependencies
        self.memory = memory_store or get_memory_store()
        self.tools = tool_registry or ToolRegistry.get_instance()
        self.flow_log = flow_logger or default_flow_logger
        
        # Callbacks
        self._on_task_complete: List[Callable] = []
        self._on_task_fail: List[Callable] = []
        self._on_flow_complete: List[Callable] = []
        
        # Thread safety
        self._lock = threading.RLock()
    
    def add_task(self, task: Task) -> "Flow":
        """
        Add a task to the flow.
        
        Args:
            task: Task to add
            
        Returns:
            Self for chaining
        """
        with self._lock:
            self._tasks[task.name] = task
            
            # Set tool registry for tool tasks
            if hasattr(task, 'set_registry'):
                task.set_registry(self.tools)  # type: ignore[attr-defined]
            
            # Update entry tasks
            self._update_entry_tasks()
            
            logger.debug(f"Added task '{task.name}' to flow '{self.name}'")
        
        return self
    
    def add_tasks(self, *tasks: Task) -> "Flow":
        """Add multiple tasks to the flow."""
        for task in tasks:
            self.add_task(task)
        return self
    
    def add_dependency(self, task_name: str, depends_on: str) -> "Flow":
        """
        Add a dependency between tasks.
        
        Args:
            task_name: The dependent task
            depends_on: The task it depends on
            
        Returns:
            Self for chaining
        """
        with self._lock:
            if task_name not in self._tasks:
                raise KeyError(f"Task '{task_name}' not found")
            if depends_on not in self._tasks:
                raise KeyError(f"Dependency task '{depends_on}' not found")
            
            self._tasks[task_name].add_dependency(depends_on)
            self._tasks[depends_on].add_dependent(task_name)
            
            self._update_entry_tasks()
            
            logger.debug(f"Added dependency: '{task_name}' depends on '{depends_on}'")
        
        return self
    
    def chain(self, *task_names: str) -> "Flow":
        """
        Chain tasks in sequence (each depends on the previous).
        
        Args:
            *task_names: Task names in execution order
            
        Returns:
            Self for chaining
        """
        for i in range(1, len(task_names)):
            self.add_dependency(task_names[i], task_names[i-1])
        return self
    
    def _update_entry_tasks(self) -> None:
        """Update the set of entry tasks (no dependencies)."""
        self._entry_tasks = {
            name for name, task in self._tasks.items()
            if not task.dependencies
        }
    
    def _get_ready_tasks(self, completed: Set[str]) -> List[str]:
        """Get tasks that are ready to execute (all dependencies met)."""
        ready = []
        for name, task in self._tasks.items():
            if task.status == TaskStatus.PENDING:
                if all(dep in completed for dep in task.dependencies):
                    ready.append(name)
        return ready
    
    def _topological_sort(self) -> List[str]:
        """
        Perform topological sort to get execution order.
        
        Returns:
            List of task names in execution order
            
        Raises:
            ValueError: If cycle detected
        """
        in_degree = {name: len(task.dependencies) for name, task in self._tasks.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            current = queue.pop(0)
            result.append(current)
            
            for dependent in self._tasks[current].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        if len(result) != len(self._tasks):
            raise ValueError("Cycle detected in task dependencies")
        
        return result
    
    def validate(self) -> List[str]:
        """
        Validate the flow configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not self._tasks:
            errors.append("Flow has no tasks")
        
        if not self._entry_tasks:
            errors.append("Flow has no entry points (all tasks have dependencies)")
        
        # Check for cycles
        try:
            self._topological_sort()
        except ValueError as e:
            errors.append(str(e))
        
        # Check for missing dependencies
        for name, task in self._tasks.items():
            for dep in task.dependencies:
                if dep not in self._tasks:
                    errors.append(f"Task '{name}' has missing dependency '{dep}'")
        
        return errors
    
    def execute(
        self,
        context: Optional[Dict[str, Any]] = None,
        parallel: bool = True
    ) -> FlowResult:
        """
        Execute the flow.
        
        Args:
            context: Initial execution context
            parallel: Whether to execute independent tasks in parallel
            
        Returns:
            FlowResult containing execution outcome
        """
        import time
        start_time = time.time()
        
        # Validate flow
        errors = self.validate()
        if errors:
            return FlowResult(
                success=False,
                flow_id=self.flow_id,
                status=FlowStatus.FAILED,
                errors=errors
            )
        
        self.status = FlowStatus.RUNNING
        self.started_at = datetime.now()
        
        # Initialize context
        ctx = context or {}
        ctx['flow_id'] = self.flow_id
        ctx['flow_name'] = self.name
        
        completed: Set[str] = set()
        task_results: Dict[str, TaskResult] = {}
        errors: List[str] = []
        
        # Log flow start
        self.flow_log.flow_start(
            flow_id=self.flow_id,
            flow_name=self.name,
            task_count=len(self._tasks),
            context_keys=list(ctx.keys()),
            parallel=parallel
        )
        
        # Set flow logger for task-level retry logging
        set_task_flow_logger(self.flow_log)
        
        try:
            if parallel:
                task_results, errors = self._execute_parallel(ctx, completed)
            else:
                task_results, errors = self._execute_sequential(ctx, completed)
            
            # Determine final status
            if errors:
                self.status = FlowStatus.FAILED
            else:
                self.status = FlowStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"Flow execution failed: {e}")
            self.status = FlowStatus.FAILED
            errors.append(str(e))
            self.flow_log.error(
                message=f"Flow execution failed: {e}",
                error_type="flow_exception",
                flow_id=self.flow_id,
                flow_name=self.name
            )
        
        self.completed_at = datetime.now()
        execution_time = time.time() - start_time
        
        # Calculate task stats
        tasks_completed = sum(1 for r in task_results.values() if r.success)
        tasks_failed = sum(1 for r in task_results.values() if not r.success)
        
        # Log flow end
        self.flow_log.flow_end(
            flow_id=self.flow_id,
            flow_name=self.name,
            status=self.status.value,
            duration=execution_time,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            errors=errors
        )
        
        # Store final results in memory
        self.memory.store_result(
            f"flow_{self.name}",
            {
                "status": self.status.value,
                "task_results": {k: v.output for k, v in task_results.items() if v.success}
            },
            workflow_id=self.flow_id
        )
        
        result = FlowResult(
            success=self.status == FlowStatus.COMPLETED,
            flow_id=self.flow_id,
            status=self.status,
            task_results=task_results,
            errors=errors,
            execution_time=execution_time
        )
        
        # Run completion callbacks
        for callback in self._on_flow_complete:
            try:
                callback(self, result)
            except Exception as e:
                logger.warning(f"Flow completion callback failed: {e}")
        
        return result
    
    def _execute_sequential(
        self,
        context: Dict[str, Any],
        completed: Set[str]
    ) -> tuple[Dict[str, TaskResult], List[str]]:
        """Execute tasks sequentially in topological order."""
        import time as time_module
        task_results = {}
        errors = []
        
        execution_order = self._topological_sort()
        
        for task_name in execution_order:
            task = self._tasks[task_name]
            
            # Log task start
            self.flow_log.task_start(
                task_name=task_name,
                task_type=task.task_type,
                flow_id=self.flow_id,
                flow_name=self.name,
                dependencies=task.dependencies
            )
            
            # Build task context with results from dependencies
            task_context = {**context}
            for dep in task.dependencies:
                if dep in task_results and task_results[dep].success:
                    task_context[f"{dep}_result"] = task_results[dep].output
            
            task_start = time_module.time()
            result = task.execute(task_context)
            task_duration = time_module.time() - task_start
            
            task_results[task_name] = result
            
            # Log task end
            output_summary = None
            if result.output is not None:
                output_summary = str(result.output)[:200]
            
            self.flow_log.task_end(
                task_name=task_name,
                task_type=task.task_type,
                status="completed" if result.success else "failed",
                duration=task_duration,
                flow_id=self.flow_id,
                flow_name=self.name,
                retries_used=result.retries_used,
                output_summary=output_summary
            )
            
            # Store result in memory
            self.memory.store_result(task_name, result.output, workflow_id=self.flow_id)
            
            if result.success:
                completed.add(task_name)
                context[f"{task_name}_result"] = result.output
                
                for callback in self._on_task_complete:
                    try:
                        callback(task, result)
                    except Exception as e:
                        logger.warning(f"Task completion callback failed: {e}")
            else:
                errors.append(f"Task '{task_name}' failed: {result.error}")
                
                for callback in self._on_task_fail:
                    try:
                        callback(task, result)
                    except Exception as e:
                        logger.warning(f"Task failure callback failed: {e}")
                
                # Stop on first failure (can be made configurable)
                break
        
        # Check if flow was interrupted by failure
        if len(task_results) < len(execution_order):
            logger.warning(f"Flow '{self.name}' stopped early due to task failure")
        
        return task_results, errors
    
    def _execute_parallel(
        self,
        context: Dict[str, Any],
        completed: Set[str]
    ) -> tuple[Dict[str, TaskResult], List[str]]:
        """Execute independent tasks in parallel."""
        import time as time_module
        task_results = {}
        errors = []
        failed: Set[str] = set()
        task_start_times = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while (len(completed) + len(failed)) < len(self._tasks):
                ready = [t for t in self._get_ready_tasks(completed) if t not in failed]
                
                if not ready:
                    if (len(completed) + len(failed)) < len(self._tasks):
                        logger.warning(f"Flow '{self.name}' stalled: {len(self._tasks) - len(completed) - len(failed)} tasks unreachable due to failures")
                        errors.append(f"Flow stalled: {len(self._tasks) - len(completed) - len(failed)} tasks unreachable due to failures")
                    break
                
                # Submit ready tasks
                futures = {}
                for task_name in ready:
                    task = self._tasks[task_name]
                    task.status = TaskStatus.RUNNING
                    
                    # Log task start
                    self.flow_log.task_start(
                        task_name=task_name,
                        task_type=task.task_type,
                        flow_id=self.flow_id,
                        flow_name=self.name,
                        dependencies=task.dependencies
                    )
                    task_start_times[task_name] = time_module.time()
                    
                    # Build task context
                    task_context = {**context}
                    for dep in task.dependencies:
                        if dep in task_results and task_results[dep].success:
                            task_context[f"{dep}_result"] = task_results[dep].output
                    
                    future = executor.submit(task.execute, task_context)
                    futures[future] = task_name
                
                # Wait for batch completion
                for future in as_completed(futures):
                    task_name = futures[future]
                    task = self._tasks[task_name]
                    task_duration = time_module.time() - task_start_times.get(task_name, time_module.time())
                    
                    try:
                        result = future.result()
                        task_results[task_name] = result
                        
                        # Log task end
                        output_summary = None
                        if result.output is not None:
                            output_summary = str(result.output)[:200]
                        
                        self.flow_log.task_end(
                            task_name=task_name,
                            task_type=task.task_type,
                            status="completed" if result.success else "failed",
                            duration=task_duration,
                            flow_id=self.flow_id,
                            flow_name=self.name,
                            retries_used=result.retries_used,
                            output_summary=output_summary
                        )
                        
                        # Store result in memory
                        self.memory.store_result(task_name, result.output, workflow_id=self.flow_id)
                        
                        if result.success:
                            completed.add(task_name)
                            context[f"{task_name}_result"] = result.output
                            
                            for callback in self._on_task_complete:
                                try:
                                    callback(task, result)
                                except Exception as e:
                                    logger.warning(f"Task completion callback failed: {e}")
                        else:
                            failed.add(task_name)
                            errors.append(f"Task '{task_name}' failed: {result.error}")
                            
                            for callback in self._on_task_fail:
                                try:
                                    callback(task, result)
                                except Exception as e:
                                    logger.warning(f"Task failure callback failed: {e}")
                    
                    except Exception as e:
                        # Log error
                        self.flow_log.error(
                            message=f"Task '{task_name}' raised exception: {e}",
                            error_type="task_exception",
                            task_name=task_name,
                            flow_id=self.flow_id,
                            flow_name=self.name
                        )
                        errors.append(f"Task '{task_name}' raised exception: {e}")
                        task_results[task_name] = TaskResult(
                            success=False,
                            error=str(e)
                        )
        
        return task_results, errors
    
    def on_task_complete(self, callback: Callable) -> "Flow":
        """Register a callback for task completion."""
        self._on_task_complete.append(callback)
        return self
    
    def on_task_fail(self, callback: Callable) -> "Flow":
        """Register a callback for task failure."""
        self._on_task_fail.append(callback)
        return self
    
    def on_flow_complete(self, callback: Callable) -> "Flow":
        """Register a callback for flow completion."""
        self._on_flow_complete.append(callback)
        return self
    
    def reset(self) -> None:
        """Reset flow and all tasks to initial state."""
        with self._lock:
            self.status = FlowStatus.PENDING
            self.started_at = None
            self.completed_at = None
            self.flow_id = str(uuid.uuid4())
            
            for task in self._tasks.values():
                task.reset()
    
    def get_task(self, name: str) -> Optional[Task]:
        """Get a task by name."""
        return self._tasks.get(name)
    
    def get_tasks(self) -> Dict[str, Task]:
        """Get all tasks."""
        return self._tasks.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize flow to dictionary."""
        return {
            "name": self.name,
            "flow_id": self.flow_id,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tasks": {name: task.to_dict() for name, task in self._tasks.items()},
            "entry_tasks": list(self._entry_tasks)
        }
    
    def visualize(self) -> str:
        """Generate a text visualization of the flow DAG."""
        lines = [f"Flow: {self.name} ({self.status.value})", "=" * 40]
        
        for name in self._topological_sort():
            task = self._tasks[name]
            deps = ", ".join(task.dependencies) or "none"
            lines.append(f"  [{task.status.value:10}] {name} (depends on: {deps})")
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return f"Flow(name={self.name}, tasks={len(self._tasks)}, status={self.status.value})"


class FlowBuilder:
    """Builder pattern for creating flows."""
    
    def __init__(self, name: str):
        self._flow = Flow(name)
    
    def description(self, desc: str) -> "FlowBuilder":
        self._flow.description = desc
        return self
    
    def max_workers(self, workers: int) -> "FlowBuilder":
        self._flow.max_workers = workers
        return self
    
    def memory(self, store: MemoryStore) -> "FlowBuilder":
        self._flow.memory = store
        return self
    
    def tools(self, registry: ToolRegistry) -> "FlowBuilder":
        self._flow.tools = registry
        return self
    
    def task(self, task: Task) -> "FlowBuilder":
        self._flow.add_task(task)
        return self
    
    def dependency(self, task_name: str, depends_on: str) -> "FlowBuilder":
        self._flow.add_dependency(task_name, depends_on)
        return self
    
    def chain(self, *task_names: str) -> "FlowBuilder":
        self._flow.chain(*task_names)
        return self
    
    def build(self) -> Flow:
        return self._flow
