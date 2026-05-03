"""
Memory Store Module
Provides persistent memory storage for agent state and context.
"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod
from collections import OrderedDict

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    ttl: Optional[float] = None  # Time-to-live in seconds
    
    def is_expired(self) -> bool:
        """Check if entry has expired based on TTL."""
        if self.ttl is None:
            return False
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.ttl
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize entry to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "tags": self.tags,
            "ttl": self.ttl
        }


class MemoryBackend(ABC):
    """Abstract base class for memory backends."""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, **kwargs) -> None:
        """Set a value by key."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key."""
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all entries."""
        pass
    
    @abstractmethod
    def keys(self) -> List[str]:
        """Get all keys."""
        pass


class InMemoryBackend(MemoryBackend):
    """In-memory storage backend using OrderedDict."""
    
    def __init__(self, max_size: int = 10000):
        self._store: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._lock = threading.RLock()
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            entry = self._store.get(key)
            if entry and entry.is_expired():
                del self._store[key]
                return None
            if entry:
                entry.access_count += 1
                # Move to end for LRU
                self._store.move_to_end(key)
            return entry
    
    def set(self, key: str, value: Any, tags: Optional[List[str]] = None, ttl: Optional[float] = None) -> None:
        with self._lock:
            if key in self._store:
                entry = self._store[key]
                entry.value = value
                entry.updated_at = datetime.now()
                if tags:
                    entry.tags = tags
                if ttl:
                    entry.ttl = ttl
            else:
                # Check max size and evict LRU if needed
                if len(self._store) >= self.max_size:
                    self._store.popitem(last=False)
                
                self._store[key] = MemoryEntry(
                    key=key,
                    value=value,
                    tags=tags or [],
                    ttl=ttl
                )
            self._store.move_to_end(key)
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False
    
    def exists(self, key: str) -> bool:
        with self._lock:
            entry = self._store.get(key)
            if entry and entry.is_expired():
                del self._store[key]
                return False
            return entry is not None
    
    def clear(self) -> None:
        with self._lock:
            self._store.clear()
    
    def keys(self) -> List[str]:
        with self._lock:
            # Clean expired entries
            expired = [k for k, v in self._store.items() if v.is_expired()]
            for k in expired:
                del self._store[k]
            return list(self._store.keys())
    
    def get_all_entries(self) -> List[MemoryEntry]:
        with self._lock:
            expired = [k for k, v in self._store.items() if v.is_expired()]
            for k in expired:
                del self._store[k]
            return list(self._store.values())


class FileBackend(MemoryBackend):
    """File-based storage backend for persistence."""
    
    def __init__(self, filepath: Union[str, Path]):
        self.filepath = Path(filepath)
        self._lock = threading.RLock()
        self._cache: Dict[str, MemoryEntry] = {}
        self._load()
    
    def _load(self) -> None:
        """Load data from file."""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    for key, entry_dict in data.items():
                        self._cache[key] = MemoryEntry(
                            key=entry_dict['key'],
                            value=entry_dict['value'],
                            created_at=datetime.fromisoformat(entry_dict['created_at']),
                            updated_at=datetime.fromisoformat(entry_dict['updated_at']),
                            access_count=entry_dict['access_count'],
                            tags=entry_dict.get('tags', []),
                            ttl=entry_dict.get('ttl')
                        )
                logger.info(f"Loaded {len(self._cache)} entries from {self.filepath}")
            except Exception as e:
                logger.error(f"Failed to load memory from {self.filepath}: {e}")
                self._cache = {}
    
    def _save(self) -> None:
        """Save data to file."""
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, 'w') as f:
                data = {k: v.to_dict() for k, v in self._cache.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory to {self.filepath}: {e}")
    
    def get(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.is_expired():
                del self._cache[key]
                self._save()
                return None
            if entry:
                entry.access_count += 1
            return entry
    
    def set(self, key: str, value: Any, tags: Optional[List[str]] = None, ttl: Optional[float] = None) -> None:
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                entry.value = value
                entry.updated_at = datetime.now()
                if tags:
                    entry.tags = tags
                if ttl:
                    entry.ttl = ttl
            else:
                self._cache[key] = MemoryEntry(
                    key=key,
                    value=value,
                    tags=tags or [],
                    ttl=ttl
                )
            self._save()
    
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._save()
                return True
            return False
    
    def exists(self, key: str) -> bool:
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.is_expired():
                del self._cache[key]
                self._save()
                return False
            return entry is not None
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._save()
    
    def keys(self) -> List[str]:
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired()]
            for k in expired:
                del self._cache[k]
            if expired:
                self._save()
            return list(self._cache.keys())


class MemoryStore:
    """
    High-level memory store for agent state and context.
    
    Features:
    - Multiple namespaces for organization
    - Conversation history tracking
    - Working memory for task context
    - Long-term memory for persistence
    - Search by tags
    """
    
    def __init__(self, backend: Optional[MemoryBackend] = None):
        self.backend = backend or InMemoryBackend()
        self._namespaces: Dict[str, str] = {}  # namespace -> prefix mapping
        
        # Pre-defined namespaces
        self.register_namespace("working", "wm:")
        self.register_namespace("conversation", "conv:")
        self.register_namespace("context", "ctx:")
        self.register_namespace("results", "res:")
    
    def register_namespace(self, name: str, prefix: str) -> None:
        """Register a namespace with a key prefix."""
        self._namespaces[name] = prefix
    
    def _get_key(self, namespace: str, key: str) -> str:
        """Get full key with namespace prefix."""
        prefix = self._namespaces.get(namespace, "")
        return f"{prefix}{key}"
    
    # Working Memory - Short-term task context
    def set_working(self, key: str, value: Any, ttl: float = 3600) -> None:
        """Set working memory (auto-expires in 1 hour by default)."""
        full_key = self._get_key("working", key)
        self.backend.set(full_key, value, ttl=ttl)
        logger.debug(f"Set working memory: {key}")
    
    def get_working(self, key: str) -> Optional[Any]:
        """Get working memory value."""
        full_key = self._get_key("working", key)
        entry = self.backend.get(full_key)
        return entry.value if entry else None
    
    # Conversation History
    def add_message(self, role: str, content: str, session_id: str = "default") -> None:
        """Add a message to conversation history."""
        history_key = self._get_key("conversation", f"history:{session_id}")
        entry = self.backend.get(history_key)
        
        messages = entry.value if entry else []
        messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        self.backend.set(history_key, messages)
        logger.debug(f"Added {role} message to session {session_id}")
    
    def get_conversation(self, session_id: str = "default", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get conversation history."""
        history_key = self._get_key("conversation", f"history:{session_id}")
        entry = self.backend.get(history_key)
        
        messages = entry.value if entry else []
        if limit:
            messages = messages[-limit:]
        return messages
    
    def clear_conversation(self, session_id: str = "default") -> None:
        """Clear conversation history."""
        history_key = self._get_key("conversation", f"history:{session_id}")
        self.backend.delete(history_key)
    
    # Context Storage
    def set_context(self, key: str, value: Any, tags: Optional[List[str]] = None) -> None:
        """Set persistent context value."""
        full_key = self._get_key("context", key)
        self.backend.set(full_key, value, tags=tags)
    
    def get_context(self, key: str) -> Optional[Any]:
        """Get persistent context value."""
        full_key = self._get_key("context", key)
        entry = self.backend.get(full_key)
        return entry.value if entry else None
    
    # Task Results
    def store_result(self, task_name: str, result: Any, workflow_id: str = "default") -> None:
        """Store task execution result."""
        result_key = self._get_key("results", f"{workflow_id}:{task_name}")
        self.backend.set(result_key, {
            "task_name": task_name,
            "workflow_id": workflow_id,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_result(self, task_name: str, workflow_id: str = "default") -> Optional[Any]:
        """Get task execution result."""
        result_key = self._get_key("results", f"{workflow_id}:{task_name}")
        entry = self.backend.get(result_key)
        return entry.value.get("result") if entry else None
    
    def get_all_results(self, workflow_id: str = "default") -> Dict[str, Any]:
        """Get all results for a workflow."""
        prefix = self._get_key("results", f"{workflow_id}:")
        results = {}
        
        for key in self.backend.keys():
            if key.startswith(prefix):
                entry = self.backend.get(key)
                if entry:
                    task_name = key[len(prefix):]
                    results[task_name] = entry.value.get("result")
        
        return results
    
    # Generic operations
    def set(self, key: str, value: Any, namespace: str = "context", **kwargs) -> None:
        """Generic set operation."""
        full_key = self._get_key(namespace, key)
        self.backend.set(full_key, value, **kwargs)
    
    def get(self, key: str, namespace: str = "context") -> Optional[Any]:
        """Generic get operation."""
        full_key = self._get_key(namespace, key)
        entry = self.backend.get(full_key)
        return entry.value if entry else None
    
    def delete(self, key: str, namespace: str = "context") -> bool:
        """Generic delete operation."""
        full_key = self._get_key(namespace, key)
        return self.backend.delete(full_key)
    
    def clear_namespace(self, namespace: str) -> None:
        """Clear all entries in a namespace."""
        prefix = self._namespaces.get(namespace, "")
        keys_to_delete = [k for k in self.backend.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            self.backend.delete(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory store statistics."""
        all_keys = self.backend.keys()
        stats = {
            "total_entries": len(all_keys),
            "namespaces": {}
        }
        
        for ns_name, prefix in self._namespaces.items():
            count = sum(1 for k in all_keys if k.startswith(prefix))
            stats["namespaces"][ns_name] = count
        
        return stats


# Global memory store instance
memory_store = MemoryStore()


def get_memory_store() -> MemoryStore:
    """Get the global memory store instance."""
    return memory_store


def create_memory_store(backend: Optional[MemoryBackend] = None) -> MemoryStore:
    """Create a new memory store instance."""
    return MemoryStore(backend)
