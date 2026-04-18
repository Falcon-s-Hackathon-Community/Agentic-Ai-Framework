<div align="center">

# AI Agent Framework
### Intel® Unnati Industrial Training Program 2025
**A Pure Python AI Agent Framework with Intel® OpenVINO™ Optimization**





[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenVINO](https://img.shields.io/badge/Intel-OpenVINO™-0071C5.svg)](https://docs.openvino.ai/)

![](https://i.giphy.com/EC5kEeJ4qz8ipD1S4R.webp)

</div>

---

## 📋 TL;DR (Too Long, Didn't Read) short Overview

> **Built from scratch** — A complete AI Agent Framework for orchestrating agentic workflows **without** using CrewAI, AutoGen, LangGraph, or n8n.

| What | Description |
|------|-------------|
| **What is it?** | A Python framework SDK for building AI agents with DAG workflows, tools, memory, and observability |
| **Why?** | Intel Unnati Problem Statement #2: Build-Your-Own AI Agent Framework |
| **Key Features** | Flow DAG execution, YAML orchestration, **Workflow Resume**, Tool registry, Memory store, Intel® OpenVINO™ optimization |
| **Compatibility** | Fully cross-platform (Linux & **Windows Optimized**) |
| **Demo Time** | < 30 seconds to run all demos |
| **New Features** | See [NEW_FEATURES.md](NEW_FEATURES.md) for recent robustness updates |
| **Lines of Code** | ~4,500 lines of pure Python (no agent framework dependencies) |

---

## 🎯 Problem Statement → Implementation Mapping

| Problem Statement Requirement | Implementation | Location |
|------------------------------|----------------|----------|
| **Define and execute task flows (DAG)** | ✅ `Flow` class with topological sort, parallel execution | `framework/flow.py` |
| **Support input handlers, tools/actions** | ✅ `ToolRegistry`, `BaseTool` with schema validation | `framework/tools.py` |
| **Output actions** | ✅ `FileWriteTool`, `HTTPTool`, task outputs | `framework/tools.py` |
| **Include memory** | ✅ `MemoryStore` with namespaces, TTL, persistence | `framework/memory.py` |
| **Guardrails** | ✅ Schema validation, retries, timeouts, error handling | `framework/tools.py`, `task.py` |
| **Observability (logs, metrics)** | ✅ `FlowLogger`, `MetricsCollector`, `AuditLog` | `framework/logging.py` |
| **Orchestrator** | ✅ YAML-based `Orchestrator` with **Stateful Resume** | `framework/orchestrator.PY` |
| **Apache components** | ✅ Ready for Kafka/Airflow integration (REST API included) | `api/server.py` |
| **Intel® OpenVINO™ optimization** | ✅ `OpenVINOTextClassifier`, `OpenVINOEmbedding` | `framework/openvino_tools.py` |
| **Framework SDK with APIs** | ✅ `Agent` class, decorators, builders | `framework/sdk.py` |
| **Two reference agents** | ✅ Research Agent, Data Processing Agent | `examples/agents_demo.py` |
| **Performance benchmarks** | ✅ Before/after OpenVINO comparison | `examples/openvino_benchmark.py` |
| **Retries and timeouts** | ✅ Exponential backoff, configurable timeouts | `framework/task.py` |

---

## 🏗️ Architecture
![ARCHITECTURE](architecture.jpeg)

---

## 🚀 Quick Start (< 2 minutes)

### 1. Install Dependencies

```bash
git clone https://github.com/Precise-Goals/Intel-Ai-Unnati-Program---Internship.git
cd Intel-Ai-Unnati-Program---Internship
pip install -r requirements.txt
```

### 2. Run All Demos

```bash
# Step 1: Set PYTHONPATH (required before running demos)

# Linux/macOS:
export PYTHONPATH=$(pwd)

# Windows PowerShell:
$env:PYTHONPATH = (Get-Location).Path

# Windows CMD:
set PYTHONPATH=%cd%

# Step 2: Run the demos
python examples/agents_demo.py       # Reference Agents (Research + Data Processing)
python examples/tools_demo.py        # Tool System with Schema Validation
python examples/orchestrator_demo.py # YAML Orchestrator with State Persistence
python examples/logging_demo.py      # Structured Logging Demo
python examples/openvino_benchmark.py # OpenVINO Benchmark
```

> 💡 **Tip**: On Windows, you can also run `run_demos.bat` which sets PYTHONPATH automatically.

### 3. Quick Code Example

```python
from framework import Agent, FunctionTask, tool

# Define a tool with schema validation
@tool(name="analyze", description="Analyze text sentiment")
def analyze(text: str) -> dict:
    return {"sentiment": "positive", "confidence": 0.95}

# Create an agent and workflow
agent = Agent("demo_agent")
flow = agent.create_flow("analysis_flow")

flow.add_task(FunctionTask("fetch", lambda ctx: {"text": "Great product!"}))
flow.add_task(FunctionTask("analyze", lambda ctx: analyze(ctx["fetch_result"]["text"])))
flow.add_dependency("analyze", "fetch")

# Execute
result = agent.run_flow("analysis_flow", {})
print(f"Success: {result.success}")  # True
```

---

## 📊 Benchmark Results: OpenVINO Optimization

### Text Classification (Sentiment Analysis)

| Metric | PyTorch (Baseline) | Intel® OpenVINO™ | Improvement |
|--------|-------------------|------------------|-------------|
| **Avg Latency** | 45.23 ms | 28.41 ms | **37.2% faster** |
| **Min Latency** | 42.18 ms | 26.54 ms | - |
| **Max Latency** | 51.87 ms | 32.19 ms | - |
| **P95 Latency** | 49.31 ms | 30.87 ms | - |
| **Throughput** | 22.11 req/s | 35.21 req/s | **59.2% higher** |
| **Speedup** | 1.0x | **1.59x** | - |

*Model: distilbert-base-uncased-finetuned-sst-2-english*

### Text Embeddings (RAG/Search)

| Metric | PyTorch (Baseline) | Intel® OpenVINO™ | Improvement |
|--------|-------------------|------------------|-------------|
| **Avg Latency** | 12.87 ms | 7.94 ms | **38.3% faster** |
| **Min Latency** | 11.92 ms | 7.21 ms | - |
| **Max Latency** | 15.43 ms | 9.18 ms | - |
| **P95 Latency** | 14.21 ms | 8.76 ms | - |
| **Throughput** | 77.73 req/s | 125.94 req/s | **62.0% higher** |
| **Speedup** | 1.0x | **1.62x** | - |

*Model: sentence-transformers/all-MiniLM-L6-v2*

> 💡 **Note**: Results measured on Intel CPU. OpenVINO provides best optimization on Intel® processors (CPU, iGPU, VPU).

---

## 📝 Sample Agent Outputs

### Research Agent Demo

```
🚀 [20:09:42] FLOW_START: research_workflow (b8e59490...) - 5 tasks
  ▶ [20:09:42] TASK_START: search (function)
  ✓ [20:09:42] TASK_END: search - completed in 0.101s
  ▶ [20:09:42] TASK_START: extract_entities (function)
  ▶ [20:09:42] TASK_START: summarize (function)        ← Parallel execution!
  ✓ [20:09:42] TASK_END: extract_entities - completed in 0.051s
  ✓ [20:09:42] TASK_END: summarize - completed in 0.101s
  ▶ [20:09:42] TASK_START: analyze_sentiment (function)
  ✓ [20:09:42] TASK_END: analyze_sentiment - completed in 0.051s
  ▶ [20:09:42] TASK_START: generate_report (function)
  ✓ [20:09:42] TASK_END: generate_report - completed in 0.000s
✅ [20:09:42] FLOW_END: research_workflow - completed in 0.26s (5 completed, 0 failed)

--- Research Report ---
  query: artificial intelligence applications in healthcare
  entities: {'persons': ['John Doe'], 'organizations': ['Tech Inc'], ...}
  sentiment: {'score': -0.10, 'label': 'neutral', 'confidence': 0.72}
```

### Orchestrator Demo (YAML Workflow)

```
============================================================
PARALLEL WORKFLOW DEMO
============================================================

Workflow: parallel_processing
Status: completed
Duration: 0.01s

Task States:
  start: completed
  branch_a: completed   ← Parallel branches
  branch_b: completed   ← 
  merge: completed

Merge Result: {'merged': True, 'total': 300}

State persisted to: workflow_states.json
```

### Structured Logging Output (JSONL)

```json
{"timestamp": "2026-01-01T20:09:42", "event_type": "FLOW_START", "flow_id": "b8e59490", "task_count": 5}
{"timestamp": "2026-01-01T20:09:42", "event_type": "TASK_END", "task_name": "search", "duration_seconds": 0.101}
{"timestamp": "2026-01-01T20:09:42", "event_type": "TASK_RETRY", "task_name": "flaky_task", "attempt": 1, "max_attempts": 3}
{"timestamp": "2026-01-01T20:09:42", "event_type": "FLOW_END", "status": "completed", "duration_seconds": 0.26}
```

---

## 📁 Project Structure

```
intel/
├── framework/                    # Core Framework SDK
│   ├── __init__.py              # Package exports
│   ├── sdk.py                   # Agent class, high-level API
│   ├── task.py                  # Task abstraction (Function, LLM, Tool, Conditional)
│   ├── flow.py                  # DAG execution engine with parallel support
│   ├── tools.py                 # Tool registry, BaseTool, schema validation
│   ├── memory.py                # Memory store with namespaces & TTL
│   ├── logging.py               # FlowLogger, MetricsCollector, AuditLog
│   ├── orchestrator.PY          # YAML-based workflow orchestrator
│   └── openvino_tools.py        # OpenVINO ML optimized tools
│
├── examples/                     # Demo & Reference Implementations
│   ├── agents_demo.py           # Research Agent + Data Processing Agent
│   ├── tools_demo.py            # Tool system demonstration
│   ├── orchestrator_demo.py     # YAML orchestration demo
│   ├── logging_demo.py          # Structured logging demo
│   ├── openvino_benchmark.py    # OpenVINO performance benchmark
│   └── workflows/               # YAML workflow definitions
│       ├── research.yaml
│       └── data_pipeline.yaml
│
├── api/
│   └── server.py                # REST API server (FastAPI)
│
├── dashboard/
│   └── ui.py                    # Streamlit monitoring dashboard
│
├── logs/flows/                  # Persisted flow logs (JSONL)
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## ✅ Compliance Checklist

### ❌ Forbidden Frameworks (NOT USED)

| Framework | Status | Verification |
|-----------|--------|--------------|
| CrewAI | ❌ Not Used | `grep -r "crewai" .` returns nothing |
| AutoGen | ❌ Not Used | `grep -r "autogen" .` returns nothing |
| LangGraph | ❌ Not Used | `grep -r "langgraph" .` returns nothing |
| n8n | ❌ Not Used | `grep -r "n8n" .` returns nothing |

### ✅ Allowed Technologies (USED)

| Technology | Usage | Location |
|------------|-------|----------|
| **Intel® OpenVINO™** | ML model optimization (1.5x-1.6x speedup) | `framework/openvino_tools.py` |
| **Apache-compatible** | REST API ready for Kafka/Airflow integration | `api/server.py` |
| **Pure Python** | All core logic (~4,500 lines) | `framework/*.py` |
| **pydantic** | Data validation | `requirements.txt` |
| **PyYAML** | YAML workflow parsing | `framework/orchestrator.PY` |

### ✅ Deliverables Completed

| Deliverable | Status | Evidence |
|-------------|--------|----------|
| Framework SDK with APIs | ✅ | `framework/sdk.py`, `framework/__init__.py` |
| Flow/DAG execution | ✅ | `framework/flow.py` (topological sort, parallel execution) |
| Tool registry | ✅ | `framework/tools.py` (BaseTool, schema validation) |
| Memory store | ✅ | `framework/memory.py` (namespaces, TTL, persistence) |
| Observability | ✅ | `framework/logging.py` (JSONL logs, metrics, audit) |
| YAML orchestrator | ✅ | `framework/orchestrator.PY` (state persistence) |
| Reference Agent #1 | ✅ | Research Agent in `examples/agents_demo.py` |
| Reference Agent #2 | ✅ | Data Processing Agent in `examples/agents_demo.py` |
| OpenVINO optimization | ✅ | `framework/openvino_tools.py` with benchmarks |
| Performance benchmarks | ✅ | `examples/openvino_benchmark.py` |
| Retries & timeouts | ✅ | `framework/task.py` (exponential backoff) |

### ✅ This is a FRAMEWORK, Not Just an App

| Framework Characteristic | Evidence |
|-------------------------|----------|
| **Extensible SDK** | `Agent`, `Task`, `Flow`, `Tool` base classes for users to extend |
| **Pluggable components** | Tool registry, memory backends, custom task types |
| **Decorators for DX** | `@tool`, `@log_execution` decorators |
| **Configuration-driven** | YAML workflow definitions |
| **APIs for integration** | REST API, programmatic flow builder |
| **Reusable abstractions** | `BaseTool`, `Task`, `MemoryStore` abstract patterns |

---

## 🔧 Advanced Usage

### Define a YAML Workflow

```yaml
# workflows/my_workflow.yaml
name: my_workflow
version: "1.0"

tasks:
  - id: fetch_data
    type: function
    config:
      function: mymodule.fetch

  - id: process
    type: tool
    depends_on: [fetch_data]
    config:
      tool_name: text_processor
      tool_args:
        operation: uppercase

  - id: save
    type: function
    depends_on: [process]
    config:
      function: mymodule.save
```

### Run with Orchestrator

```python
from framework.orchestrator import Orchestrator

orch = Orchestrator(state_dir="./states")
result = orch.load_and_run("workflows/my_workflow.yaml")
print(f"Status: {result.status}")  # completed
```

### Use OpenVINO-Optimized Tools

```python
from framework.openvino_tools import OpenVINOTextClassifier

classifier = OpenVINOTextClassifier(
    model_name="distilbert-base-uncased-finetuned-sst-2-english",
    use_openvino=True  # Enable Intel optimization
)

result = classifier.classify("This product is amazing!")
# {'label': 'POSITIVE', 'confidence': 0.98}
```

---

## 👥 Team Falcons

| Name | Role | Email | Contact | CGPA |
|------|------|-------|---------|------|
| **Sarthak Tulsidas Patil** | Developer (CSE) | sarthak.patil@nmiet.edu.in | 7387303695 | 9.57 |
| **Prathamesh Santosh Kolhe** | Developer (CSE) | prathameshkolhe6099@gmail.com | 9975668077 | 9.18 |
| **Dhiraj Takale** | Developer (CSE) | dhirajtakale17@gmail.com | 8668945438 | 9.27 |

### Mentor

| Name | Role | Email | Contact |
|------|------|-------|---------|
| **Prof. Jordan Choudhari** | Assistant Professor | jordan.choudhari@nmiet.edu.in | 7709754570 |

---

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

<div align="center">

![alt text](https://i.giphy.com/Eg02gyLrv9ZiUvemFZ.webp)

**Built with ❤️ by Team Falcons for Intel® Unnati Industrial Training Program 2025**

*No forbidden frameworks. Pure Python. Intel® Optimized.*

</div>
