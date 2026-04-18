"""
Logging and Observability Module
Provides comprehensive logging, metrics, and tracing for the framework.
"""

import logging
import json
import time
import os
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from enum import Enum
import threading
import sys


# =============================================================================
# Default log directory
# =============================================================================
DEFAULT_LOG_DIR = Path("./logs")


class LogLevel(Enum):
    """Log level enumeration."""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: datetime
    level: str
    message: str
    component: str = ""
    flow_id: Optional[str] = None
    task_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "message": self.message,
            "component": self.component,
            "flow_id": self.flow_id,
            "task_name": self.task_name,
            **self.extra
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class StructuredFormatter(logging.Formatter):
    """JSON-based structured log formatter."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields
        if hasattr(record, 'flow_id'):
            log_data['flow_id'] = record.flow_id  # type: ignore[attr-defined]
        if hasattr(record, 'task_name'):
            log_data['task_name'] = record.task_name  # type: ignore[attr-defined]
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)  # type: ignore[attr-defined]
        
        # Add exception info
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class PrettyFormatter(logging.Formatter):
    """Human-readable colored log formatter."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, '')
        
        # Build prefix with context
        prefix_parts = []
        if hasattr(record, 'flow_id'):
            prefix_parts.append(f"flow:{record.flow_id[:8]}")  # type: ignore[attr-defined]
        if hasattr(record, 'task_name'):
            prefix_parts.append(f"task:{record.task_name}")  # type: ignore[attr-defined]
        
        prefix = f"[{' | '.join(prefix_parts)}] " if prefix_parts else ""
        
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
        
        return (
            f"{color}{timestamp} [{record.levelname:8}]{self.RESET} "
            f"{record.name:20} - {prefix}{record.getMessage()}"
        )


class MetricsCollector:
    """
    Collects and aggregates metrics for observability.
    
    Features:
    - Counter metrics
    - Gauge metrics
    - Histogram/timing metrics
    - Metric export
    """
    
    _instance: Optional["MetricsCollector"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = threading.RLock()
        self._initialized = True
    
    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        return cls()
    
    def increment(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
    
    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        key = self._make_key(name, tags)
        with self._lock:
            self._gauges[key] = value
    
    def histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Add a value to a histogram metric."""
        key = self._make_key(name, tags)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
    
    def timer(self, name: str, tags: Optional[Dict[str, str]] = None) -> "Timer":
        """Create a timer context manager."""
        return Timer(self, name, tags)
    
    def _make_key(self, name: str, tags: Optional[Dict[str, str]] = None) -> str:
        """Create a unique key for a metric with tags."""
        if tags:
            tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{name}[{tag_str}]"
        return name
    
    def get_counter(self, name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        key = self._make_key(name, tags)
        return self._counters.get(key, 0)
    
    def get_gauge(self, name: str, tags: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get current gauge value."""
        key = self._make_key(name, tags)
        return self._gauges.get(key)
    
    def get_histogram_stats(self, name: str, tags: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get histogram statistics."""
        key = self._make_key(name, tags)
        values = self._histograms.get(key, [])
        
        if not values:
            return {}
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            "count": n,
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "mean": sum(values) / n,
            "p50": sorted_values[n // 2],
            "p90": sorted_values[int(n * 0.9)],
            "p99": sorted_values[int(n * 0.99)] if n >= 100 else sorted_values[-1]
        }
    
    def export(self) -> Dict[str, Any]:
        """Export all metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: self.get_histogram_stats(k.split('[')[0])
                    for k in self._histograms
                },
                "exported_at": datetime.now().isoformat()
            }
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


class Timer:
    """Context manager for timing operations."""
    
    def __init__(self, collector: MetricsCollector, name: str, tags: Optional[Dict[str, str]] = None):
        self.collector = collector
        self.name = name
        self.tags = tags
        self.start_time: Optional[float] = None
    
    def __enter__(self) -> "Timer":
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.histogram(self.name, duration, self.tags)
        return False


class AuditLog:
    """
    Audit logging for tracking agent actions and decisions.
    
    Features:
    - Immutable audit trail
    - Action attribution
    - Decision tracking
    """
    
    def __init__(self, filepath: Optional[Path] = None):
        self._entries: List[Dict[str, Any]] = []
        self.filepath = filepath
        self._lock = threading.Lock()
    
    def log_action(
        self,
        action: str,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
        flow_id: Optional[str] = None,
        task_name: Optional[str] = None
    ) -> None:
        """Log an action to the audit trail."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "actor": actor,
            "flow_id": flow_id,
            "task_name": task_name,
            "details": details or {}
        }
        
        with self._lock:
            self._entries.append(entry)
            
            if self.filepath:
                self._append_to_file(entry)
    
    def _append_to_file(self, entry: Dict[str, Any]) -> None:
        """Append entry to audit file."""
        if self.filepath is None:
            return
        try:
            with open(self.filepath, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logging.error(f"Failed to write audit log: {e}")
    
    def get_entries(
        self,
        flow_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Query audit entries."""
        entries = self._entries
        
        if flow_id:
            entries = [e for e in entries if e.get('flow_id') == flow_id]
        if action:
            entries = [e for e in entries if e.get('action') == action]
        
        if limit:
            entries = entries[-limit:]
        
        return entries


class FrameworkLogger:
    """
    High-level logger for the AI Agent Framework.
    
    Features:
    - Structured logging
    - Context injection
    - Multiple outputs
    - Metric integration
    """
    
    def __init__(
        self,
        name: str = "agent_framework",
        level: LogLevel = LogLevel.INFO,
        structured: bool = False,
        log_file: Optional[Path] = None
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level.value)
        self.logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level.value)
        
        if structured:
            console_handler.setFormatter(StructuredFormatter())
        else:
            console_handler.setFormatter(PrettyFormatter())
        
        self.logger.addHandler(console_handler)
        
        # File handler
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level.value)
            file_handler.setFormatter(StructuredFormatter())
            self.logger.addHandler(file_handler)
        
        self.metrics = MetricsCollector.get_instance()
        self._context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs) -> None:
        """Set context fields to include in all logs."""
        self._context.update(kwargs)
    
    def clear_context(self) -> None:
        """Clear context fields."""
        self._context.clear()
    
    def _log(self, level: int, message: str, **kwargs) -> None:
        """Internal logging method."""
        extra = {**self._context, **kwargs}
        self.logger.log(level, message, extra={'extra_data': extra})
    
    def debug(self, message: str, **kwargs) -> None:
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        self._log(logging.ERROR, message, **kwargs)
        self.metrics.increment("errors", tags={"type": kwargs.get("error_type", "unknown")})
    
    def critical(self, message: str, **kwargs) -> None:
        self._log(logging.CRITICAL, message, **kwargs)
        self.metrics.increment("critical_errors")
    
    def task_started(self, task_name: str, flow_id: Optional[str] = None) -> None:
        """Log task start event."""
        self.info(f"Task started: {task_name}", task_name=task_name, flow_id=flow_id)
        self.metrics.increment("task_started", tags={"task": task_name})
    
    def task_completed(self, task_name: str, duration: float, flow_id: Optional[str] = None) -> None:
        """Log task completion event."""
        self.info(
            f"Task completed: {task_name} ({duration:.2f}s)",
            task_name=task_name,
            flow_id=flow_id,
            duration=duration
        )
        self.metrics.increment("task_completed", tags={"task": task_name})
        self.metrics.histogram("task_duration", duration, tags={"task": task_name})
    
    def task_failed(self, task_name: str, error: str, flow_id: Optional[str] = None) -> None:
        """Log task failure event."""
        self.error(
            f"Task failed: {task_name} - {error}",
            task_name=task_name,
            flow_id=flow_id,
            error=error
        )
        self.metrics.increment("task_failed", tags={"task": task_name})
    
    def flow_started(self, flow_name: str, flow_id: str) -> None:
        """Log flow start event."""
        self.info(f"Flow started: {flow_name}", flow_name=flow_name, flow_id=flow_id)
        self.metrics.increment("flow_started", tags={"flow": flow_name})
    
    def flow_completed(self, flow_name: str, flow_id: str, duration: float) -> None:
        """Log flow completion event."""
        self.info(
            f"Flow completed: {flow_name} ({duration:.2f}s)",
            flow_name=flow_name,
            flow_id=flow_id,
            duration=duration
        )
        self.metrics.increment("flow_completed", tags={"flow": flow_name})
        self.metrics.histogram("flow_duration", duration, tags={"flow": flow_name})
    
    def tool_called(self, tool_name: str, flow_id: Optional[str] = None) -> None:
        """Log tool invocation."""
        self.debug(f"Tool called: {tool_name}", tool_name=tool_name, flow_id=flow_id)
        self.metrics.increment("tool_calls", tags={"tool": tool_name})
    
    def task_retry(self, task_name: str, attempt: int, max_attempts: int, error: str, delay: float, flow_id: Optional[str] = None) -> None:
        """Log task retry event."""
        self.warning(
            f"Task retry: {task_name} (attempt {attempt}/{max_attempts}) - retrying in {delay:.1f}s",
            task_name=task_name,
            flow_id=flow_id,
            attempt=attempt,
            max_attempts=max_attempts,
            error=error,
            retry_delay=delay
        )
        self.metrics.increment("task_retries", tags={"task": task_name})


# =============================================================================
# Flow Logger - Specialized logger for flow execution
# =============================================================================

class FlowLogger:
    """
    Specialized structured logger for flow and task execution.
    
    Features:
    - Automatic file-based log storage
    - Structured JSON logs
    - Flow/task correlation
    - Execution timing
    - Retry tracking
    - Error aggregation
    
    Logs are stored in:
    - logs/flows/<flow_name>/<flow_id>.jsonl  (per-flow logs)
    - logs/flows/all_flows.jsonl              (aggregated logs)
    """
    
    _instance: Optional["FlowLogger"] = None
    
    def __new__(cls, log_dir: Optional[Path] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, log_dir: Optional[Path] = None):
        if self._initialized:
            return
        
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        self._current_flow: Optional[Dict[str, Any]] = None
        self._flow_logs: Dict[str, List[Dict]] = {}
        self._metrics = MetricsCollector.get_instance()
        
        # Aggregated log file
        self._all_flows_log = self.log_dir / "flows" / "all_flows.jsonl"
        self._all_flows_log.parent.mkdir(parents=True, exist_ok=True)
        
        self._initialized = True
    
    @classmethod
    def get_instance(cls, log_dir: Optional[Path] = None) -> "FlowLogger":
        """Get singleton instance."""
        return cls(log_dir)
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
    
    def _safe_print(self, message: str) -> None:
        """Print to console handling potential encoding errors."""
        try:
            print(message)
        except UnicodeEncodeError:
            # Fallback for terminals that don't support certain characters (like emojis)
            try:
                # Try to print after encoding to ascii with replacements
                print(message.encode('ascii', errors='replace').decode('ascii'))
            except Exception:
                # Absolute fallback
                pass

    def _write_log(self, entry: Dict[str, Any], flow_name: Optional[str] = None, flow_id: Optional[str] = None) -> None:
        """Write log entry to file."""
        with self._lock:
            # Write to aggregated log
            with open(self._all_flows_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            
            # Write to flow-specific log
            if flow_name and flow_id:
                flow_dir = self.log_dir / "flows" / flow_name
                flow_dir.mkdir(parents=True, exist_ok=True)
                flow_log = flow_dir / f"{flow_id}.jsonl"
                with open(flow_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
    
    def _create_entry(
        self,
        event_type: str,
        level: str,
        message: str,
        flow_id: Optional[str] = None,
        flow_name: Optional[str] = None,
        task_name: Optional[str] = None,
        **extra
    ) -> Dict[str, Any]:
        """Create a structured log entry."""
        return {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "level": level,
            "message": message,
            "flow_id": flow_id,
            "flow_name": flow_name,
            "task_name": task_name,
            **extra
        }
    
    # -------------------------------------------------------------------------
    # Flow Events
    # -------------------------------------------------------------------------
    
    def flow_start(
        self,
        flow_id: str,
        flow_name: str,
        task_count: int,
        context_keys: Optional[List[str]] = None,
        parallel: bool = True
    ) -> None:
        """Log flow start event."""
        entry = self._create_entry(
            event_type="FLOW_START",
            level="INFO",
            message=f"Flow '{flow_name}' started",
            flow_id=flow_id,
            flow_name=flow_name,
            task_count=task_count,
            context_keys=context_keys or [],
            execution_mode="parallel" if parallel else "sequential"
        )
        self._write_log(entry, flow_name, flow_id)
        self._metrics.increment("flow_started", tags={"flow": flow_name})
        
        # Console output
        self._safe_print(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] FLOW_START: {flow_name} ({flow_id[:8]}...) - {task_count} tasks")
    
    def flow_end(
        self,
        flow_id: str,
        flow_name: str,
        status: str,
        duration: float,
        tasks_completed: int,
        tasks_failed: int,
        errors: Optional[List[str]] = None
    ) -> None:
        """Log flow end event."""
        entry = self._create_entry(
            event_type="FLOW_END",
            level="INFO" if status == "completed" else "ERROR",
            message=f"Flow '{flow_name}' {status}",
            flow_id=flow_id,
            flow_name=flow_name,
            status=status,
            duration_seconds=round(duration, 3),
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            errors=errors or []
        )
        self._write_log(entry, flow_name, flow_id)
        
        self._metrics.increment("flow_completed", tags={"flow": flow_name, "status": status})
        self._metrics.histogram("flow_duration", duration, tags={"flow": flow_name})
        
        # Console output
        icon = "✅" if status == "completed" else "❌"
        self._safe_print(f"{icon} [{datetime.now().strftime('%H:%M:%S')}] FLOW_END: {flow_name} - {status} in {duration:.2f}s ({tasks_completed} completed, {tasks_failed} failed)")
    
    # -------------------------------------------------------------------------
    # Task Events
    # -------------------------------------------------------------------------
    
    def task_start(
        self,
        task_name: str,
        task_type: str,
        flow_id: Optional[str] = None,
        flow_name: Optional[str] = None,
        dependencies: Optional[List[str]] = None
    ) -> None:
        """Log task start event."""
        entry = self._create_entry(
            event_type="TASK_START",
            level="INFO",
            message=f"Task '{task_name}' started",
            flow_id=flow_id,
            flow_name=flow_name,
            task_name=task_name,
            task_type=task_type,
            dependencies=dependencies or []
        )
        self._write_log(entry, flow_name, flow_id)
        self._metrics.increment("task_started", tags={"task": task_name, "type": task_type})
        
        self._safe_print(f"  ▶ [{datetime.now().strftime('%H:%M:%S')}] TASK_START: {task_name} ({task_type})")
    
    def task_end(
        self,
        task_name: str,
        task_type: str,
        status: str,
        duration: float,
        flow_id: Optional[str] = None,
        flow_name: Optional[str] = None,
        retries_used: int = 0,
        output_summary: Optional[str] = None
    ) -> None:
        """Log task completion event."""
        entry = self._create_entry(
            event_type="TASK_END",
            level="INFO" if status == "completed" else "ERROR",
            message=f"Task '{task_name}' {status}",
            flow_id=flow_id,
            flow_name=flow_name,
            task_name=task_name,
            task_type=task_type,
            status=status,
            duration_seconds=round(duration, 3),
            retries_used=retries_used,
            output_summary=output_summary
        )
        self._write_log(entry, flow_name, flow_id)
        
        self._metrics.increment("task_completed", tags={"task": task_name, "status": status})
        self._metrics.histogram("task_duration", duration, tags={"task": task_name})
        
        icon = "  ✓" if status == "completed" else "  ✗"
        retry_info = f" (retries: {retries_used})" if retries_used > 0 else ""
        self._safe_print(f"{icon} [{datetime.now().strftime('%H:%M:%S')}] TASK_END: {task_name} - {status} in {duration:.3f}s{retry_info}")
    
    # -------------------------------------------------------------------------
    # Retry Events
    # -------------------------------------------------------------------------
    
    def task_retry(
        self,
        task_name: str,
        attempt: int,
        max_attempts: int,
        error: str,
        delay: float,
        flow_id: Optional[str] = None,
        flow_name: Optional[str] = None
    ) -> None:
        """Log task retry event."""
        entry = self._create_entry(
            event_type="TASK_RETRY",
            level="WARNING",
            message=f"Task '{task_name}' retry {attempt}/{max_attempts}",
            flow_id=flow_id,
            flow_name=flow_name,
            task_name=task_name,
            attempt=attempt,
            max_attempts=max_attempts,
            error=error,
            retry_delay_seconds=round(delay, 2)
        )
        self._write_log(entry, flow_name, flow_id)
        self._metrics.increment("task_retries", tags={"task": task_name})
        
        self._safe_print(f"  ⟳ [{datetime.now().strftime('%H:%M:%S')}] TASK_RETRY: {task_name} - attempt {attempt}/{max_attempts}, waiting {delay:.1f}s")
        self._safe_print(f"      Error: {error[:100]}{'...' if len(error) > 100 else ''}")
    
    # -------------------------------------------------------------------------
    # Error Events
    # -------------------------------------------------------------------------
    
    def error(
        self,
        message: str,
        error_type: str = "unknown",
        task_name: Optional[str] = None,
        flow_id: Optional[str] = None,
        flow_name: Optional[str] = None,
        stack_trace: Optional[str] = None,
        **extra
    ) -> None:
        """Log error event."""
        entry = self._create_entry(
            event_type="ERROR",
            level="ERROR",
            message=message,
            flow_id=flow_id,
            flow_name=flow_name,
            task_name=task_name,
            error_type=error_type,
            stack_trace=stack_trace,
            **extra
        )
        self._write_log(entry, flow_name, flow_id)
        self._metrics.increment("errors", tags={"type": error_type})
        
        self._safe_print(f"  ❌ [{datetime.now().strftime('%H:%M:%S')}] ERROR: {message}")
    
    # -------------------------------------------------------------------------
    # Query Methods
    # -------------------------------------------------------------------------
    
    def get_flow_logs(self, flow_name: str, flow_id: str) -> List[Dict[str, Any]]:
        """Retrieve logs for a specific flow execution."""
        flow_log = self.log_dir / "flows" / flow_name / f"{flow_id}.jsonl"
        if not flow_log.exists():
            return []
        
        logs = []
        with open(flow_log, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        return logs
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent logs from all flows."""
        if not self._all_flows_log.exists():
            return []
        
        logs = []
        with open(self._all_flows_log, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line))
        
        return logs[-limit:]
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of recent errors."""
        logs = self.get_recent_logs(1000)
        errors = [l for l in logs if l.get("level") == "ERROR"]
        
        error_counts = {}
        for e in errors:
            error_type = e.get("error_type", "unknown")
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return {
            "total_errors": len(errors),
            "by_type": error_counts,
            "recent_errors": errors[-10:]
        }


# =============================================================================
# Global flow logger instance
# =============================================================================
flow_logger = FlowLogger.get_instance()


def get_flow_logger(log_dir: Optional[str] = None) -> FlowLogger:
    """Get the flow logger instance."""
    if log_dir:
        return FlowLogger(Path(log_dir))
    return flow_logger


def log_execution(logger: Optional[FrameworkLogger] = None):
    """Decorator to log function execution."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            log = logger or FrameworkLogger()
            func_name = func.__name__
            
            log.debug(f"Executing: {func_name}")
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                log.debug(f"Completed: {func_name} ({duration:.3f}s)")
                return result
            except Exception as e:
                duration = time.time() - start_time
                log.error(f"Failed: {func_name} after {duration:.3f}s - {e}")
                raise
        
        return wrapper
    return decorator


# Global instances
metrics = MetricsCollector.get_instance()
audit = AuditLog()


def setup_logging(
    level: LogLevel = LogLevel.INFO,
    structured: bool = False,
    log_file: Optional[str] = None
) -> FrameworkLogger:
    """
    Configure framework logging.
    
    Args:
        level: Log level
        structured: Use JSON structured logging
        log_file: Optional log file path
        
    Returns:
        Configured logger instance
    """
    return FrameworkLogger(
        level=level,
        structured=structured,
        log_file=Path(log_file) if log_file else None
    )
