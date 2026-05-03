"""
Tool Registry Module
Provides a centralized registry for tools that tasks can invoke.
Includes Tool base class with schema validation and example tools.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type, Union
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# Schema Validation
# =============================================================================

@dataclass
class SchemaField:
    """Definition of a field in an input/output schema."""
    type: str  # "string", "integer", "float", "boolean", "list", "dict", "any"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None  # Allowed values
    
    def validate(self, value: Any, field_name: str) -> Any:
        """Validate a value against this schema field."""
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{field_name}' is required")
            return self.default
        
        # Type validation
        type_map = {
            "string": str,
            "integer": int,
            "float": (int, float),
            "boolean": bool,
            "list": list,
            "dict": dict,
            "any": object
        }
        
        expected_type = type_map.get(self.type)
        if expected_type and not isinstance(value, expected_type):
            raise TypeError(
                f"Field '{field_name}' expected {self.type}, got {type(value).__name__}"
            )
        
        # Enum validation
        if self.enum is not None and value not in self.enum:
            raise ValueError(
                f"Field '{field_name}' must be one of {self.enum}, got {value}"
            )
        
        return value


@dataclass
class Schema:
    """Input or output schema for a tool."""
    fields: Dict[str, SchemaField] = field(default_factory=dict)
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate data against the schema.
        
        Returns validated/transformed data with defaults applied.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}")
        
        result = {}
        
        # Validate each defined field
        for name, schema_field in self.fields.items():
            value = data.get(name)
            result[name] = schema_field.validate(value, name)
        
        # Check for extra fields
        extra_fields = set(data.keys()) - set(self.fields.keys())
        if extra_fields:
            logger.warning(f"Extra fields in input will be ignored: {extra_fields}")
        
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary representation."""
        return {
            name: {
                "type": f.type,
                "description": f.description,
                "required": f.required,
                "default": f.default,
                "enum": f.enum
            }
            for name, f in self.fields.items()
        }


# =============================================================================
# Tool Base Class
# =============================================================================

class Tool(ABC):
    """
    Abstract base class for all tools.
    
    Provides:
    - Input/output schema validation
    - Memory and context access during execution
    - Metrics tracking
    - Error handling
    
    Subclasses must implement:
    - name: Tool identifier
    - description: What the tool does
    - input_schema: Expected input format
    - output_schema: Expected output format
    - _execute(): Core tool logic
    """
    
    name: str = "base_tool"
    description: str = "Base tool class"
    version: str = "1.0.0"
    tags: List[str] = []
    
    def __init__(self):
        self._call_count = 0
        self._total_execution_time = 0.0
        self._last_error: Optional[str] = None
    
    @property
    @abstractmethod
    def input_schema(self) -> Schema:
        """Define the input schema for this tool."""
        pass
    
    @property
    @abstractmethod
    def output_schema(self) -> Schema:
        """Define the output schema for this tool."""
        pass
    
    @abstractmethod
    def _execute(
        self,
        validated_input: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute the tool logic.
        
        Args:
            validated_input: Input data that has passed schema validation
            memory: Memory store instance (optional)
            context: Execution context with runtime information
            
        Returns:
            Output data matching output_schema
        """
        pass
    
    def execute(
        self,
        input_data: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute the tool with schema validation.
        
        Args:
            input_data: Raw input data
            memory: Memory store for persistent state
            context: Execution context (task info, workflow state, etc.)
            
        Returns:
            Validated output data
        """
        import time
        start_time = time.time()
        context = context or {}
        
        try:
            # Validate input
            logger.debug(f"Tool '{self.name}': Validating input")
            validated_input = self.input_schema.validate(input_data)
            
            # Execute
            logger.info(f"Tool '{self.name}': Executing with input keys: {list(validated_input.keys())}")
            raw_output = self._execute(validated_input, memory, context)
            
            # Validate output
            logger.debug(f"Tool '{self.name}': Validating output")
            validated_output = self.output_schema.validate(raw_output)
            
            # Update metrics
            execution_time = time.time() - start_time
            self._call_count += 1
            self._total_execution_time += execution_time
            self._last_error = None
            
            logger.info(f"Tool '{self.name}': Completed in {execution_time:.3f}s")
            return validated_output
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Tool '{self.name}': Execution failed - {e}")
            raise
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get tool execution metrics."""
        return {
            "name": self.name,
            "call_count": self._call_count,
            "total_execution_time": self._total_execution_time,
            "avg_execution_time": self._total_execution_time / max(self._call_count, 1),
            "last_error": self._last_error
        }
    
    def to_definition(self) -> "ToolDefinition":
        """Convert to ToolDefinition for registry compatibility."""
        # Create a wrapper that converts kwargs to input_data dict
        tool_instance = self
        def wrapper(**kwargs):
            return tool_instance.execute(input_data=kwargs)
        
        return ToolDefinition(
            name=self.name,
            func=wrapper,
            description=self.description,
            parameters=self.input_schema.to_dict(),
            tags=self.tags,
            version=self.version
        )
    
    def __repr__(self) -> str:
        return f"<Tool:{self.name} v{self.version}>"


# =============================================================================
# Example Tools
# =============================================================================

class LLMTool(Tool):
    """
    Tool for invoking LLM inference.
    
    Supports multiple backends via the 'backend' config.
    Default implementation uses a mock response for testing.
    """
    
    name = "llm"
    description = "Invoke LLM for text generation, summarization, or analysis"
    tags = ["ai", "llm", "generation"]
    
    def __init__(
        self,
        backend: str = "mock",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ):
        super().__init__()
        self.backend = backend
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
    
    @property
    def input_schema(self) -> Schema:
        return Schema(fields={
            "prompt": SchemaField(
                type="string",
                description="The prompt to send to the LLM",
                required=True
            ),
            "system_prompt": SchemaField(
                type="string",
                description="System prompt for context",
                required=False,
                default="You are a helpful assistant."
            ),
            "max_tokens": SchemaField(
                type="integer",
                description="Maximum tokens to generate",
                required=False,
                default=None
            ),
            "temperature": SchemaField(
                type="float",
                description="Sampling temperature (0-2)",
                required=False,
                default=None
            )
        })
    
    @property
    def output_schema(self) -> Schema:
        return Schema(fields={
            "response": SchemaField(
                type="string",
                description="Generated text response"
            ),
            "model": SchemaField(
                type="string",
                description="Model used for generation"
            ),
            "usage": SchemaField(
                type="dict",
                description="Token usage statistics",
                required=False,
                default={}
            )
        })
    
    def _execute(
        self,
        validated_input: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        prompt = validated_input["prompt"]
        system_prompt = validated_input.get("system_prompt", "You are a helpful assistant.")
        max_tokens = validated_input.get("max_tokens") or self.max_tokens
        temperature = validated_input.get("temperature") or self.temperature
        
        # Store prompt in memory if available
        if memory is not None:
            try:
                memory.set("last_llm_prompt", prompt)
            except Exception:
                pass
        
        if self.backend == "mock":
            # Mock response for testing
            return {
                "response": f"[Mock LLM Response] Processed: {prompt[:100]}...",
                "model": self.model,
                "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": 50}
            }
        
        elif self.backend == "openai":
            # Real OpenAI API call
            try:
                import openai
                client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
                
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                
                return {
                    "response": response.choices[0].message.content,
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens
                    }
                }
            except ImportError:
                raise RuntimeError("openai package not installed. Install with: pip install openai")
        
        else:
            raise ValueError(f"Unknown LLM backend: {self.backend}")


class FileWriteTool(Tool):
    """
    Tool for writing content to files.
    
    Supports text and JSON formats with optional backup creation.
    """
    
    name = "file_write"
    description = "Write content to a file on disk"
    tags = ["io", "file", "write"]
    
    def __init__(
        self,
        base_dir: Optional[str] = None,
        create_dirs: bool = True,
        create_backup: bool = False
    ):
        super().__init__()
        self.base_dir = Path(base_dir) if base_dir else None
        self.create_dirs = create_dirs
        self.create_backup = create_backup
    
    @property
    def input_schema(self) -> Schema:
        return Schema(fields={
            "path": SchemaField(
                type="string",
                description="File path to write to",
                required=True
            ),
            "content": SchemaField(
                type="any",
                description="Content to write (string or dict for JSON)",
                required=True
            ),
            "mode": SchemaField(
                type="string",
                description="Write mode",
                required=False,
                default="write",
                enum=["write", "append"]
            ),
            "format": SchemaField(
                type="string",
                description="Output format",
                required=False,
                default="text",
                enum=["text", "json"]
            ),
            "encoding": SchemaField(
                type="string",
                description="File encoding",
                required=False,
                default="utf-8"
            )
        })
    
    @property
    def output_schema(self) -> Schema:
        return Schema(fields={
            "path": SchemaField(
                type="string",
                description="Absolute path to written file"
            ),
            "bytes_written": SchemaField(
                type="integer",
                description="Number of bytes written"
            ),
            "success": SchemaField(
                type="boolean",
                description="Whether write was successful"
            )
        })
    
    def _execute(
        self,
        validated_input: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        path = Path(validated_input["path"])
        content = validated_input["content"]
        mode = validated_input.get("mode", "write")
        fmt = validated_input.get("format", "text")
        encoding = validated_input.get("encoding", "utf-8")
        
        # Apply base directory if set
        if self.base_dir and not path.is_absolute():
            path = self.base_dir / path
        
        # Create directories if needed
        if self.create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create backup if file exists
        if self.create_backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            import shutil
            shutil.copy2(path, backup_path)
            logger.info(f"Created backup: {backup_path}")
        
        # Format content
        if fmt == "json":
            if isinstance(content, str):
                # Validate it's valid JSON
                content = json.loads(content)
            content_str = json.dumps(content, indent=2, ensure_ascii=False)
        else:
            content_str = str(content)
        
        # Write file
        file_mode = "a" if mode == "append" else "w"
        if mode == "append" and not content_str.endswith("\n"):
            content_str += "\n"
        with open(path, file_mode, encoding=encoding) as f:
            bytes_written = f.write(content_str)
        
        # Store in memory if available
        if memory is not None:
            try:
                memory.set("last_file_written", str(path.absolute()))
            except Exception:
                pass
        
        logger.info(f"Wrote {bytes_written} bytes to {path}")
        
        return {
            "path": str(path.absolute()),
            "bytes_written": bytes_written,
            "success": True
        }


class FileReadTool(Tool):
    """
    Tool for reading content from files.
    """
    
    name = "file_read"
    description = "Read content from a file on disk"
    tags = ["io", "file", "read"]
    
    def __init__(self, base_dir: Optional[str] = None):
        super().__init__()
        self.base_dir = Path(base_dir) if base_dir else None
    
    @property
    def input_schema(self) -> Schema:
        return Schema(fields={
            "path": SchemaField(
                type="string",
                description="File path to read from",
                required=True
            ),
            "format": SchemaField(
                type="string",
                description="Parse format",
                required=False,
                default="text",
                enum=["text", "json"]
            ),
            "encoding": SchemaField(
                type="string",
                description="File encoding",
                required=False,
                default="utf-8"
            )
        })
    
    @property
    def output_schema(self) -> Schema:
        return Schema(fields={
            "content": SchemaField(
                type="any",
                description="File content (string or parsed JSON)"
            ),
            "path": SchemaField(
                type="string",
                description="Absolute path to file"
            ),
            "size": SchemaField(
                type="integer",
                description="File size in bytes"
            )
        })
    
    def _execute(
        self,
        validated_input: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        path = Path(validated_input["path"])
        fmt = validated_input.get("format", "text")
        encoding = validated_input.get("encoding", "utf-8")
        
        # Apply base directory if set
        if self.base_dir and not path.is_absolute():
            path = self.base_dir / path
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Read file
        with open(path, "r", encoding=encoding) as f:
            content = f.read()
        
        # Parse if JSON
        if fmt == "json":
            content = json.loads(content)
        
        return {
            "content": content,
            "path": str(path.absolute()),
            "size": path.stat().st_size
        }


class HTTPTool(Tool):
    """
    Tool for making HTTP requests.
    """
    
    name = "http"
    description = "Make HTTP requests to external APIs"
    tags = ["network", "http", "api"]
    
    def __init__(self, timeout: int = 30, verify_ssl: bool = True):
        super().__init__()
        self.timeout = timeout
        self.verify_ssl = verify_ssl
    
    @property
    def input_schema(self) -> Schema:
        return Schema(fields={
            "url": SchemaField(
                type="string",
                description="URL to request",
                required=True
            ),
            "method": SchemaField(
                type="string",
                description="HTTP method",
                required=False,
                default="GET",
                enum=["GET", "POST", "PUT", "DELETE", "PATCH"]
            ),
            "headers": SchemaField(
                type="dict",
                description="Request headers",
                required=False,
                default={}
            ),
            "body": SchemaField(
                type="any",
                description="Request body (dict for JSON, string for raw)",
                required=False,
                default=None
            ),
            "params": SchemaField(
                type="dict",
                description="Query parameters",
                required=False,
                default={}
            )
        })
    
    @property
    def output_schema(self) -> Schema:
        return Schema(fields={
            "status_code": SchemaField(
                type="integer",
                description="HTTP status code"
            ),
            "body": SchemaField(
                type="any",
                description="Response body"
            ),
            "headers": SchemaField(
                type="dict",
                description="Response headers"
            )
        })
    
    def _execute(
        self,
        validated_input: Dict[str, Any],
        memory: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        try:
            import urllib.request
            import urllib.parse
            import urllib.error
        except ImportError:
            raise RuntimeError("urllib not available")
        
        url = validated_input["url"]
        method = validated_input.get("method", "GET")
        headers = validated_input.get("headers", {})
        body = validated_input.get("body")
        params = validated_input.get("params", {})
        
        # Add query params
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        
        # Prepare body
        data = None
        if body is not None:
            if isinstance(body, dict):
                data = json.dumps(body).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                data = str(body).encode("utf-8")
        
        # Create request
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
                response_headers = dict(response.getheaders())
                
                # Try to parse JSON
                try:
                    response_body = json.loads(response_body)
                except json.JSONDecodeError:
                    pass
                
                return {
                    "status_code": response.status,
                    "body": response_body,
                    "headers": response_headers
                }
        except urllib.error.URLError as e:
            if hasattr(e, 'read'):
                return {
                    "status_code": getattr(e, 'code', 500),
                    "body": e.read().decode("utf-8", errors="replace"),
                    "headers": dict(getattr(e, 'headers', {}))
                }
            return {
                "status_code": 500,
                "body": str(getattr(e, 'reason', e)),
                "headers": {}
            }


@dataclass
class ToolDefinition:
    """Definition of a registered tool."""
    name: str
    func: Callable
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=datetime.now)
    call_count: int = 0
    total_execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize tool definition to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "tags": self.tags,
            "version": self.version,
            "call_count": self.call_count,
            "avg_execution_time": self.total_execution_time / max(self.call_count, 1)
        }


class ToolRegistry:
    """
    Centralized registry for tools available to agent tasks.
    
    Features:
    - Tool registration with metadata
    - Tool discovery and listing
    - Execution tracking and metrics
    - Validation of tool inputs
    """
    
    _instance: Optional["ToolRegistry"] = None
    
    def __new__(cls):
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._tools: Dict[str, ToolDefinition] = {}
        self._initialized = True
        logger.info("Tool Registry initialized")
    
    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """Get the singleton registry instance."""
        return cls()
    
    @classmethod
    def reset(cls) -> None:
        """Reset the registry (mainly for testing)."""
        cls._instance = None
    
    def register(
        self,
        name: Optional[str] = None,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        version: str = "1.0.0"
    ) -> Callable:
        """
        Decorator to register a tool function.
        
        Usage:
            @registry.register(name="search", description="Search the web")
            def search_tool(query: str) -> str:
                return f"Results for: {query}"
        """
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            
            tool_def = ToolDefinition(
                name=tool_name,
                func=func,
                description=description or func.__doc__ or "",
                parameters=parameters or {},
                tags=tags or [],
                version=version
            )
            
            self._tools[tool_name] = tool_def
            logger.info(f"Registered tool: {tool_name}")
            
            @wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            
            return wrapper
        
        return decorator
    
    def register_tool(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        version: str = "1.0.0"
    ) -> None:
        """
        Register a tool function directly (non-decorator style).
        
        Args:
            func: The tool function to register
            name: Tool name (defaults to function name)
            description: Tool description
            parameters: Parameter schema
            tags: Tool tags for categorization
            version: Tool version
        """
        tool_name = name or func.__name__
        
        tool_def = ToolDefinition(
            name=tool_name,
            func=func,
            description=description or func.__doc__ or "",
            parameters=parameters or {},
            tags=tags or [],
            version=version
        )
        
        self._tools[tool_name] = tool_def
        logger.info(f"Registered tool: {tool_name}")
    
    def register_class(self, tool_instance: Tool) -> None:
        """
        Register a Tool class instance.
        
        Args:
            tool_instance: Instance of a Tool subclass
        """
        if not isinstance(tool_instance, Tool):
            raise TypeError(f"Expected Tool instance, got {type(tool_instance).__name__}")
        
        tool_def = tool_instance.to_definition()
        self._tools[tool_def.name] = tool_def
        logger.info(f"Registered Tool class: {tool_def.name}")
    
    def unregister(self, name: str) -> bool:
        """
        Unregister a tool by name.
        
        Returns:
            True if tool was removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Unregistered tool: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)
    
    def exists(self, name: str) -> bool:
        """Check if a tool exists in the registry."""
        return name in self._tools
    
    def execute(self, name: str, args: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute a registered tool.
        
        Args:
            name: Tool name
            args: Arguments to pass to the tool
            
        Returns:
            Tool execution result
            
        Raises:
            KeyError: If tool not found
        """
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found in registry")
        
        tool = self._tools[name]
        args = args or {}
        
        import time
        start_time = time.time()
        
        try:
            logger.debug(f"Executing tool: {name} with args: {args}")
            result = tool.func(**args)
            
            execution_time = time.time() - start_time
            tool.call_count += 1
            tool.total_execution_time += execution_time
            
            logger.info(f"Tool '{name}' executed in {execution_time:.3f}s")
            return result
            
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            raise
    
    def list_tools(self, tags: Optional[List[str]] = None) -> List[ToolDefinition]:
        """
        List all registered tools, optionally filtered by tags.
        
        Args:
            tags: Filter by these tags (OR logic)
            
        Returns:
            List of tool definitions
        """
        if tags is None:
            return list(self._tools.values())
        
        return [
            tool for tool in self._tools.values()
            if any(tag in tool.tags for tag in tags)
        ]
    
    def get_tool_names(self) -> List[str]:
        """Get list of all registered tool names."""
        return list(self._tools.keys())
    
    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible function schema for all tools.
        Useful for LLM function calling.
        """
        schemas = []
        for tool in self._tools.values():
            schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.parameters,
                        "required": list(tool.parameters.keys())
                    }
                }
            }
            schemas.append(schema)
        return schemas
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get registry metrics and statistics."""
        return {
            "total_tools": len(self._tools),
            "tools": {
                name: {
                    "call_count": tool.call_count,
                    "total_execution_time": tool.total_execution_time,
                    "avg_execution_time": tool.total_execution_time / max(tool.call_count, 1)
                }
                for name, tool in self._tools.items()
            }
        }
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools


# Global registry instance
tool_registry = ToolRegistry.get_instance()


def tool(
    name: Optional[str] = None,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None
) -> Callable:
    """
    Convenience decorator for registering tools to the global registry.
    
    Usage:
        @tool(name="calculator", description="Perform calculations")
        def calculate(expression: str) -> float:
            return eval(expression)
    """
    return tool_registry.register(
        name=name,
        description=description,
        parameters=parameters,
        tags=tags
    )


# Built-in tools
@tool(
    name="echo",
    description="Echo back the input",
    parameters={"message": {"type": "string", "description": "Message to echo"}},
    tags=["utility", "debug"]
)
def echo_tool(message: str) -> str:
    """Simple echo tool for testing."""
    return f"Echo: {message}"


@tool(
    name="noop",
    description="No operation - does nothing",
    parameters={},
    tags=["utility", "debug"]
)
def noop_tool() -> None:
    """No-op tool for testing."""
    pass
