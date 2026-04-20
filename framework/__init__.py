"""
AI Agent Framework
A minimal Python-based framework for building and orchestrating AI agents.

Core Components:
- Task: Base abstraction for executable units of work
- Flow: DAG-based workflow execution engine
- ToolRegistry: Centralized registry for tools
- MemoryStore: Persistent memory storage
- Agent: High-level orchestrator

Usage:
    from framework import Agent, FunctionTask, tool

    # Define a tool
    @tool(name="greet")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    # Create an agent
    agent = Agent("my_agent")

    # Create a flow
    flow = agent.create_flow("greeting_flow")
    flow.add_task(FunctionTask("greet_task", lambda ctx: greet(ctx['name'])))

    # Execute
    result = agent.run_flow("greeting_flow", {"name": "World"})
"""

from .sdk import (
    # Core classes
    Agent,
    AgentConfig,
    create_agent,
    
    # Task classes
    Task,
    TaskStatus,
    TaskResult,
    FunctionTask,
    LLMTask,
    ToolTask,
    ConditionalTask,
    
    # Flow classes
    Flow,
    FlowStatus,
    FlowResult,
    FlowBuilder,
    
    # Tool classes
    ToolRegistry,
    ToolDefinition,
    tool,
    tool_registry,
    
    # Tool base class and schema
    BaseTool,
    Schema,
    SchemaField,
    
    # Example tools
    LLMTool,
    FileWriteTool,
    FileReadTool,
    HTTPTool,
    
    # Memory classes
    MemoryStore,
    MemoryBackend,
    InMemoryBackend,
    FileBackend,
    get_memory_store,
    create_memory_store,
    
    # Logging classes
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
    get_flow_logger,
    
    # Orchestrator classes
    Orchestrator,
    WorkflowState,
    WorkflowStatus,
    StateStore,
    FlowParser,
    create_orchestrator,
    
    # Utility functions
    quick_flow,
    run_task,
    
    # Rate limiting
    RateLimiter,
    RateLimitConfig,
    RateLimitPresets,
    get_global_rate_limiter,
    set_global_rate_limiter,
    disable_global_rate_limiter,
)

__version__ = "0.1.0"
__author__ = "AI Agent Framework Team"

__all__ = [
    # Version
    "__version__",
    "__author__",
    
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
    
    # Tool base class and schema
    "BaseTool",
    "Schema",
    "SchemaField",
    
    # Example tools
    "LLMTool",
    "FileWriteTool",
    "FileReadTool",
    "HTTPTool",
    
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
    "FlowLogger",
    "flow_logger",
    "get_flow_logger",
    
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
