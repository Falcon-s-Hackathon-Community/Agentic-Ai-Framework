"""
Demo: Tool Base Class with Schema Validation

Demonstrates:
1. Tool base class with execute(input, memory, context)
2. Input/output schema validation
3. Example tools: LLMTool, FileWriteTool, FileReadTool, HTTPTool
4. Custom tool creation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from framework import (
    BaseTool,
    Schema,
    SchemaField,
    LLMTool,
    FileWriteTool,
    FileReadTool,
    HTTPTool,
    tool_registry,
    get_memory_store
)


def divider(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# =============================================================================
# 1. Using Built-in LLMTool
# =============================================================================
divider("1. LLMTool (Mock Backend)")

llm = LLMTool(backend="mock", model="gpt-4")

# Execute with schema-validated input
result = llm.execute(
    input_data={
        "prompt": "Explain quantum computing in simple terms",
        "system_prompt": "You are a science educator"
    }
)

print(f"LLM Response: {result['response'][:80]}...")
print(f"Model: {result['model']}")
print(f"Usage: {result['usage']}")


# =============================================================================
# 2. Using FileWriteTool
# =============================================================================
divider("2. FileWriteTool")

import tempfile
import os

# Create a file writer tool with a temp directory
temp_dir = tempfile.mkdtemp()
file_writer = FileWriteTool(base_dir=temp_dir, create_dirs=True)

# Write text content
result = file_writer.execute(
    input_data={
        "path": "test_output.txt",
        "content": "Hello from FileWriteTool!\nThis is line 2.",
        "mode": "write",
        "format": "text"
    }
)
print(f"Written to: {result['path']}")
print(f"Bytes written: {result['bytes_written']}")

# Write JSON content
result = file_writer.execute(
    input_data={
        "path": "data/config.json",
        "content": {"name": "MyApp", "version": "1.0", "debug": True},
        "format": "json"
    }
)
print(f"JSON written to: {result['path']}")


# =============================================================================
# 3. Using FileReadTool
# =============================================================================
divider("3. FileReadTool")

file_reader = FileReadTool(base_dir=temp_dir)

# Read text file
result = file_reader.execute(
    input_data={
        "path": "test_output.txt",
        "format": "text"
    }
)
print(f"Text content:\n{result['content']}")
print(f"File size: {result['size']} bytes")

# Read JSON file
result = file_reader.execute(
    input_data={
        "path": "data/config.json",
        "format": "json"
    }
)
print(f"\nJSON content: {result['content']}")


# =============================================================================
# 4. Schema Validation Demo
# =============================================================================
divider("4. Schema Validation")

# Test valid input
print("Testing valid input...")
try:
    result = file_writer.execute({
        "path": "valid.txt",
        "content": "Valid content"
    })
    print(f"[OK] Valid input accepted")
except Exception as e:
    print(f"[ERROR] Unexpected error: {e}")

# Test missing required field
print("\nTesting missing required field...")
try:
    result = file_writer.execute({
        "content": "Missing path!"  # 'path' is required
    })
    print(f"[ERROR] Should have raised error")
except ValueError as e:
    print(f"[OK] Correctly caught: {e}")

# Test invalid enum value
print("\nTesting invalid enum value...")
try:
    result = file_writer.execute({
        "path": "test.txt",
        "content": "Test",
        "mode": "invalid_mode"  # Must be "write" or "append"
    })
    print(f"[ERROR] Should have raised error")
except ValueError as e:
    print(f"[OK] Correctly caught: {e}")


# =============================================================================
# 5. Custom Tool Creation
# =============================================================================
divider("5. Custom Tool Creation")


class TextProcessorTool(BaseTool):
    """Custom tool for text processing operations."""
    
    name = "text_processor"
    description = "Process text with various operations"
    tags = ["text", "utility"]
    
    @property
    def input_schema(self) -> Schema:
        return Schema(fields={
            "text": SchemaField(
                type="string",
                description="Text to process",
                required=True
            ),
            "operation": SchemaField(
                type="string",
                description="Operation to perform",
                required=True,
                enum=["uppercase", "lowercase", "reverse", "word_count"]
            )
        })
    
    @property
    def output_schema(self) -> Schema:
        return Schema(fields={
            "result": SchemaField(
                type="any",
                description="Processing result"
            ),
            "operation": SchemaField(
                type="string",
                description="Operation performed"
            )
        })
    
    def _execute(self, validated_input, memory=None, context=None):
        text = validated_input["text"]
        operation = validated_input["operation"]
        
        if operation == "uppercase":
            result = text.upper()
        elif operation == "lowercase":
            result = text.lower()
        elif operation == "reverse":
            result = text[::-1]
        elif operation == "word_count":
            result = len(text.split())
        
        # Store in memory if available
        if memory:
            memory.set("last_processed_text", text)
        
        return {
            "result": result,
            "operation": operation
        }


# Create and use the custom tool
text_processor = TextProcessorTool()

print(f"Tool: {text_processor.name}")
print(f"Description: {text_processor.description}")

# Test operations
for op in ["uppercase", "lowercase", "reverse", "word_count"]:
    result = text_processor.execute({
        "text": "Hello World",
        "operation": op
    })
    print(f"  {op}: {result['result']}")


# =============================================================================
# 6. Tool with Memory Integration
# =============================================================================
divider("6. Tool with Memory Integration")

# Create memory store
memory = get_memory_store()

# Execute tool with memory
llm = LLMTool(backend="mock")
result = llm.execute(
    input_data={"prompt": "Remember this prompt!"},
    memory=memory,
    context={"task_id": "demo_task"}
)

# Check if prompt was stored in memory
last_prompt = memory.get("last_llm_prompt")
print(f"Stored in memory - last_llm_prompt: {last_prompt}")


# =============================================================================
# 7. Tool Metrics
# =============================================================================
divider("7. Tool Metrics")

# Get metrics from tools
print(f"LLMTool metrics: {llm.get_metrics()}")
print(f"FileWriteTool metrics: {file_writer.get_metrics()}")
print(f"TextProcessorTool metrics: {text_processor.get_metrics()}")


# =============================================================================
# 8. Register Tool Class with Registry
# =============================================================================
divider("8. Register Tool Class with Registry")

# Register the custom tool with the global registry
tool_registry.register_class(text_processor)

# Now it can be called via the registry
result = tool_registry.execute(
    "text_processor",
    {"text": "Registry Test", "operation": "uppercase"}
)
print(f"Registry execution result: {result}")

# List all registered tools
print(f"\nAll registered tools: {tool_registry.get_tool_names()}")


# =============================================================================
# Cleanup
# =============================================================================
divider("Cleanup")

import shutil
shutil.rmtree(temp_dir)
print(f"Cleaned up temp directory: {temp_dir}")

print("\n[OK] All Tool demos completed successfully!")
