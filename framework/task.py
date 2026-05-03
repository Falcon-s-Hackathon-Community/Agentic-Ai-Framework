"""
Task Abstraction Module
Provides base Task class with execution, retries, and status tracking.
"""

import time
import logging
from enum import Enum
from typing import Any, Callable, Dict, Optional, List, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import traceback

if TYPE_CHECKING:
    from .tools import ToolRegistry
    from .logging import FlowLogger

logger = logging.getLogger(__name__)

# Global flow logger reference (set by Flow during execution)
_flow_logger: Optional["FlowLogger"] = None

def set_task_flow_logger(flow_logger: "FlowLogger") -> None:
    """Set the flow logger for task-level logging."""
    global _flow_logger
    _flow_logger = flow_logger

def get_task_flow_logger() -> Optional["FlowLogger"]:
    """Get the current flow logger."""
    return _flow_logger


class TaskStatus(Enum):
    """Enumeration of possible task states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


@dataclass
class TaskResult:
    """Container for task execution results."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retries_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class Task:
    """
    Base Task abstraction for the AI Agent Framework.
    
    Features:
    - Configurable retries with exponential backoff
    - Timeout handling
    - Status tracking
    - Pre/post execution hooks
    - Input/output validation
    """
    
    def __init__(
        self,
        name: str,
        task_type: str = "generic",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: Optional[float] = None,
        description: str = "",
        tags: Optional[List[str]] = None
    ):
        self.name = name
        self.task_type = task_type
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.description = description
        self.tags = tags or []
        
        # Execution state
        self.status = TaskStatus.PENDING
        self.result: Optional[TaskResult] = None
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        
        # DAG dependencies
        self.dependencies: List[str] = []
        self.dependents: List[str] = []
        
        # Hooks
        self._pre_hooks: List[Callable] = []
        self._post_hooks: List[Callable] = []
    
    def add_dependency(self, task_name: str) -> "Task":
        """Add a task dependency (this task will wait for the dependency)."""
        if task_name == self.name:
            raise ValueError(f"Task '{self.name}' cannot depend on itself")
        if task_name not in self.dependencies:
            self.dependencies.append(task_name)
        return self
    
    def add_dependent(self, task_name: str) -> "Task":
        """Add a dependent task (will run after this task)."""
        if task_name not in self.dependents:
            self.dependents.append(task_name)
        return self
    
    def add_pre_hook(self, hook: Callable) -> "Task":
        """Add a pre-execution hook."""
        self._pre_hooks.append(hook)
        return self
    
    def add_post_hook(self, hook: Callable) -> "Task":
        """Add a post-execution hook."""
        self._post_hooks.append(hook)
        return self
    
    def execute(self, context: Dict[str, Any]) -> TaskResult:
        """
        Execute the task with retry logic.
        
        Args:
            context: Execution context containing inputs and shared state
            
        Returns:
            TaskResult containing execution outcome
        """
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()
        
        retries = 0
        last_error = None
        
        # Run pre-hooks
        for hook in self._pre_hooks:
            try:
                hook(self, context)
            except Exception as e:
                logger.warning(f"Pre-hook failed for task {self.name}: {e}")
        
        while retries <= self.max_retries:
            try:
                start_time = time.time()
                
                # Actual task execution
                output = self._run(context)
                
                execution_time = time.time() - start_time
                
                self.result = TaskResult(
                    success=True,
                    output=output,
                    execution_time=execution_time,
                    retries_used=retries
                )
                self.status = TaskStatus.COMPLETED
                self.completed_at = datetime.now()
                
                logger.info(f"Task '{self.name}' completed successfully in {execution_time:.2f}s")
                
                # Run post-hooks
                for hook in self._post_hooks:
                    try:
                        hook(self, context, self.result)
                    except Exception as e:
                        logger.warning(f"Post-hook failed for task {self.name}: {e}")
                
                return self.result
                
            except Exception as e:
                last_error = str(e)
                retries += 1
                
                if retries <= self.max_retries:
                    self.status = TaskStatus.RETRYING
                    delay = self.retry_delay * (2 ** (retries - 1))  # Exponential backoff
                    
                    # Log retry with FlowLogger if available
                    flow_log = get_task_flow_logger()
                    if flow_log:
                        flow_log.task_retry(
                            task_name=self.name,
                            attempt=retries,
                            max_attempts=self.max_retries + 1,
                            error=last_error,
                            delay=delay,
                            flow_id=context.get('flow_id'),
                            flow_name=context.get('flow_name')
                        )
                    else:
                        logger.warning(
                            f"Task '{self.name}' failed (attempt {retries}/{self.max_retries + 1}). "
                            f"Retrying in {delay:.1f}s... Error: {e}"
                        )
                    time.sleep(delay)
                else:
                    logger.error(f"Task '{self.name}' failed after {retries} attempts: {e}")
                    logger.debug(traceback.format_exc())
        
        # All retries exhausted
        self.result = TaskResult(
            success=False,
            error=last_error,
            retries_used=retries - 1
        )
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        
        return self.result
    
    def _run(self, context: Dict[str, Any]) -> Any:
        """
        Internal execution method to be overridden by subclasses.
        
        Args:
            context: Execution context
            
        Returns:
            Task output
        """
        raise NotImplementedError("Subclasses must implement _run method")
    
    def reset(self) -> None:
        """Reset task to initial state for re-execution."""
        self.status = TaskStatus.PENDING
        self.result = None
        self.started_at = None
        self.completed_at = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "name": self.name,
            "task_type": self.task_type,
            "status": self.status.value,
            "description": self.description,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": {
                "success": self.result.success,
                "output": str(self.result.output)[:200] if self.result else None,
                "error": self.result.error if self.result else None,
                "execution_time": self.result.execution_time if self.result else None,
                "retries_used": self.result.retries_used if self.result else None
            } if self.result else None
        }
    
    def __repr__(self) -> str:
        return f"Task(name={self.name}, type={self.task_type}, status={self.status.value})"


class FunctionTask(Task):
    """Task that wraps a callable function."""
    
    def __init__(
        self,
        name: str,
        func: Callable,
        **kwargs
    ):
        super().__init__(name, task_type="function", **kwargs)
        self.func = func
    
    def _run(self, context: Dict[str, Any]) -> Any:
        return self.func(context)


class LLMTask(Task):
    """Task for LLM-based processing."""
    
    def __init__(
        self,
        name: str,
        prompt_template: str,
        llm_handler: Optional[Callable] = None,
        **kwargs
    ):
        super().__init__(name, task_type="llm", **kwargs)
        self.prompt_template = prompt_template
        self.llm_handler = llm_handler
    
    def _run(self, context: Dict[str, Any]) -> Any:
        # Format the prompt with context
        prompt = self.prompt_template.format(**context)
        
        if self.llm_handler:
            return self.llm_handler(prompt)
        
        # If no handler, return the formatted prompt (for external processing)
        return {"prompt": prompt, "requires_llm": True}


class ToolTask(Task):
    """Task that invokes a registered tool."""
    
    def __init__(
        self,
        name: str,
        tool_name: str,
        tool_registry: Optional["ToolRegistry"] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        pass_context: bool = False,
        **kwargs
    ):
        super().__init__(name, task_type="tool", **kwargs)
        self.tool_name = tool_name
        self.tool_registry = tool_registry
        self.tool_args = tool_args or {}
        self.pass_context = pass_context  # Whether to pass full context to tool
    
    def set_registry(self, registry: "ToolRegistry") -> "ToolTask":
        """Set the tool registry for this task."""
        self.tool_registry = registry
        return self
    
    def _run(self, context: Dict[str, Any]) -> Any:
        if not self.tool_registry:
            raise ValueError(f"No tool registry set for task '{self.name}'")
        
        # Build tool arguments
        if self.pass_context:
            # Pass full context merged with explicit args
            merged_args = {**context, **self.tool_args}
        else:
            # Only pass explicit tool args, with template substitution from context
            merged_args = {}
            for key, value in self.tool_args.items():
                if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                    # Template substitution: "{var_result}" -> context["var_result"]
                    ctx_key = value[1:-1]
                    merged_args[key] = context.get(ctx_key, value)
                else:
                    merged_args[key] = value
        
        return self.tool_registry.execute(self.tool_name, merged_args)


class ConditionalTask(Task):
    """Task that branches based on a condition."""
    
    def __init__(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        true_task: Optional[str] = None,
        false_task: Optional[str] = None,
        **kwargs
    ):
        super().__init__(name, task_type="conditional", **kwargs)
        self.condition = condition
        self.true_task = true_task
        self.false_task = false_task
    
    def _run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        result = self.condition(context)
        return {
            "condition_result": result,
            "next_task": self.true_task if result else self.false_task
        }
