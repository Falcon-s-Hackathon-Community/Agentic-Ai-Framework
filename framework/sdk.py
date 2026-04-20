"""
AI Agent Framework SDK
Main entry point for using the framework.

Usage:
    from framework import Agent, Flow, Task, tool

    @tool(name="search")
    def search_web(query: str) -> str:
        return f"Results for: {query}"

    agent = Agent("my_agent")
    flow = agent.create_flow("research_flow")
    
    flow.add_task(FunctionTask("search", lambda ctx: search_web(ctx['query'])))
    
    result = flow.execute({"query": "AI agents"})
"""

from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass
import uuid

from .task import (
    Task,
    TaskStatus,
    TaskResult,
    FunctionTask,
    LLMTask,
    ToolTask,
    ConditionalTask
)
from .tools import (
    ToolRegistry,
    ToolDefinition,
    tool,
    tool_registry,
    # Tool base class and schema
    Tool as BaseTool,
    Schema,
    SchemaField,
    # Example tools
    LLMTool,
    FileWriteTool,
    FileReadTool,
    HTTPTool
)
from .memory import (
    MemoryStore,
    MemoryBackend,
    InMemoryBackend,
    FileBackend,
    get_memory_store,
    create_memory_store
)
from .flow import (
    Flow,
    FlowStatus,
    FlowResult,
    FlowBuilder
)
from .logging import (
    FrameworkLogger,
    MetricsCollector,
    AuditLog,
    LogLevel,
    setup_logging,
    metrics,
    audit,
    log_execution,
    FlowLogger,
    flow_logger,
    get_flow_logger
)
from .orchestrator import (
    Orchestrator,
    WorkflowState,
    WorkflowStatus,
    StateStore,
    FlowParser,
    create_orchestrator
)
from .rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitPresets,
    get_global_rate_limiter,
    set_global_rate_limiter,
    disable_global_rate_limiter
)

# Optional OpenVINO tools (only if dependencies available)
try:
    from .openvino_tools import (
        OpenVINOTextClassifier,
        OpenVINOEmbedding,
        BenchmarkResult,
        compare_backends,
        print_benchmark_comparison
    )
    OPENVINO_AVAILABLE = True
except ImportError:
    OPENVINO_AVAILABLE = False
    OpenVINOTextClassifier = None
    OpenVINOEmbedding = None
    BenchmarkResult = None


class Agent:
    """
    High-level Agent class that orchestrates flows and tasks.
    
    An Agent is the primary interface for creating and executing
    agentic workflows in the framework.
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        memory: Optional[MemoryStore] = None,
        tools: Optional[ToolRegistry] = None,
        logger: Optional[FrameworkLogger] = None
    ):
        self.name = name
        self.description = description
        self.agent_id = str(uuid.uuid4())
        
        # Core components
        self.memory = memory or get_memory_store()
        self.tools = tools or ToolRegistry.get_instance()
        self.logger = logger or setup_logging()
        
        # Flow management
        self._flows: Dict[str, Flow] = {}
        
        # Context
        self._global_context: Dict[str, Any] = {}
        
        self.logger.info(f"Agent '{name}' initialized (ID: {self.agent_id})")
    
    def create_flow(
        self,
        name: str,
        description: str = "",
        max_workers: int = 4
    ) -> Flow:
        """
        Create a new flow for this agent.
        
        Args:
            name: Flow name
            description: Flow description
            max_workers: Max parallel workers
            
        Returns:
            New Flow instance
        """
        flow = Flow(
            name=name,
            description=description,
            max_workers=max_workers,
            memory_store=self.memory,
            tool_registry=self.tools
        )
        
        self._flows[name] = flow
        self.logger.debug(f"Created flow: {name}")
        
        return flow
    
    def get_flow(self, name: str) -> Optional[Flow]:
        """Get a flow by name."""
        return self._flows.get(name)
    
    def list_flows(self) -> List[str]:
        """List all flow names."""
        return list(self._flows.keys())
    
    def set_context(self, key: str, value: Any) -> "Agent":
        """Set a global context value available to all flows."""
        self._global_context[key] = value
        self.memory.set_context(key, value)
        return self
    
    def get_context(self, key: str) -> Optional[Any]:
        """Get a global context value."""
        return self._global_context.get(key)
    
    def register_tool(
        self,
        func: Callable,
        name: str = None,
        description: str = ""
    ) -> "Agent":
        """Register a tool for use in tasks."""
        self.tools.register_tool(func, name=name, description=description)
        return self
    
    def run_flow(
        self,
        flow_name: str,
        context: Dict[str, Any] = None,
        parallel: bool = True
    ) -> FlowResult:
        """
        Execute a named flow.
        
        Args:
            flow_name: Name of the flow to execute
            context: Execution context
            parallel: Enable parallel execution
            
        Returns:
            FlowResult containing execution outcome
        """
        flow = self._flows.get(flow_name)
        if not flow:
            raise KeyError(f"Flow '{flow_name}' not found")
        
        # Merge global context with provided context
        merged_context = {**self._global_context, **(context or {})}
        merged_context['agent_id'] = self.agent_id
        merged_context['agent_name'] = self.name
        
        self.logger.flow_started(flow_name, flow.flow_id)
        
        result = flow.execute(merged_context, parallel=parallel)
        
        if result.success:
            self.logger.flow_completed(flow_name, flow.flow_id, result.execution_time)
        else:
            self.logger.error(
                f"Flow '{flow_name}' failed",
                flow_id=flow.flow_id,
                errors=result.errors
            )
        
        return result
    
    def add_conversation_message(self, role: str, content: str, session_id: str = "default") -> None:
        """Add a message to the agent's conversation history."""
        self.memory.add_message(role, content, session_id)
    
    def get_conversation_history(self, session_id: str = "default", limit: int = None) -> List[Dict]:
        """Get conversation history."""
        return self.memory.get_conversation(session_id, limit)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get agent metrics."""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "flows": len(self._flows),
            "tools": len(self.tools),
            "metrics": metrics.export(),
            "memory_stats": self.memory.get_stats()
        }
    
    def reset(self) -> None:
        """Reset agent state."""
        for flow in self._flows.values():
            flow.reset()
        self._global_context.clear()
        self.logger.info(f"Agent '{self.name}' reset")
    
    def __repr__(self) -> str:
        return f"Agent(name={self.name}, flows={len(self._flows)}, tools={len(self.tools)})"


@dataclass
class AgentConfig:
    """Configuration for Agent creation."""
    name: str
    description: str = ""
    memory_backend: Optional[MemoryBackend] = None
    log_level: LogLevel = LogLevel.INFO
    log_file: Optional[str] = None
    structured_logging: bool = False
    max_workers: int = 4


def create_agent(config: AgentConfig) -> Agent:
    """
    Factory function to create an Agent from configuration.
    
    Args:
        config: Agent configuration
        
    Returns:
        Configured Agent instance
    """
    memory = create_memory_store(config.memory_backend)
    logger = setup_logging(
        level=config.log_level,
        structured=config.structured_logging,
        log_file=config.log_file
    )
    
    return Agent(
        name=config.name,
        description=config.description,
        memory=memory,
        logger=logger
    )


# Convenience functions for quick workflow creation
def quick_flow(tasks: List[Task], sequential: bool = True) -> Flow:
    """
    Create a quick flow from a list of tasks.
    
    Args:
        tasks: List of tasks to add
        sequential: If True, tasks run in sequence; else parallel
        
    Returns:
        Configured Flow
    """
    flow = Flow(f"quick_flow_{uuid.uuid4().hex[:8]}")
    
    for task in tasks:
        flow.add_task(task)
    
    if sequential and len(tasks) > 1:
        task_names = [t.name for t in tasks]
        flow.chain(*task_names)
    
    return flow


def run_task(task: Task, context: Dict[str, Any] = None) -> TaskResult:
    """
    Execute a single task.
    
    Args:
        task: Task to execute
        context: Execution context
        
    Returns:
        TaskResult
    """
    return task.execute(context or {})


# Export all public symbols
__all__ = [
    # Core classes
    "Agent",
    "AgentConfig",
    "create_agent",
    
    # Task classes
    "Task",
    "TaskStatus",
    "TaskResult",
    "FunctionTask",
    "LLMTask",
    "ToolTask",
    "ConditionalTask",
    
    # Flow classes
    "Flow",
    "FlowStatus",
    "FlowResult",
    "FlowBuilder",
    
    # Tool classes
    "ToolRegistry",
    "ToolDefinition",
    "tool",
    "tool_registry",
    
    # Memory classes
    "MemoryStore",
    "MemoryBackend",
    "InMemoryBackend",
    "FileBackend",
    "get_memory_store",
    "create_memory_store",
    
    # Logging classes
    "FrameworkLogger",
    "MetricsCollector",
    "AuditLog",
    "LogLevel",
    "setup_logging",
    "metrics",
    "audit",
    "log_execution",
    
    # Orchestrator classes
    "Orchestrator",
    "WorkflowState",
    "WorkflowStatus",
    "StateStore",
    "FlowParser",
    "create_orchestrator",
    
    # Utility functions
    "quick_flow",
    "run_task",
    
    # Rate limiting
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitPresets",
    "get_global_rate_limiter",
    "set_global_rate_limiter",
    "disable_global_rate_limiter",
]