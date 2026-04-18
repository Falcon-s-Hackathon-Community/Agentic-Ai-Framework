# New Features & Enhancements (April 2025)

This document highlights the major improvements and new features added to the AI Agent Framework to improve execution robustness, observability, and cross-platform compatibility.

## 🔄 Workflow Resumption
The `Orchestrator` now supports **stateful resumption**. If a workflow fails due to an external error (e.g., API timeout), you can resume it from the point of failure without re-running successful tasks.

- **How to use**: `orchestrator.resume(workflow_id, yaml_source="path/to/flow.yaml")`
- **Intelligent Skipping**: Automatically detects tasks with `status: completed` and injects their stored results into the context for downstream tasks.
- **Retry Support**: Previously failed tasks are automatically added back to the execution queue.

## 💎 High-Fidelity State Persistence
We have upgraded the `StateStore` to preserve raw Python objects (dictionaries, lists, numbers) in task results.
- **Previous**: Results were stringified upon saving, breaking type consistency.
- **Current**: Results are stored in their native serializable format, ensuring that resumed workflows receive the exact data structures they expect.

## 🪟 Windows Stability & Unicode Support
To ensure the framework remains truly cross-platform, we implemented a **Safe Printing Mechanism** in the `FlowLogger`.
- **Automatic Sanitization**: On Windows systems, emojis and non-standard Unicode characters are gracefully substituted or handled to prevent `UnicodeEncodeError` in the console.
- **Consistent UI**: All demo scripts have been sanitized to provide a clean, crash-free experience on Windows CMD and PowerShell.

## 🕸️ Advanced DAG Propagation
The `Flow` execution engine has been refined for better failure handling:
- **Instant Propagation**: When a task fails, the engine recursively marks all downstream dependents as `skipped`.
- **Parallel Robustness**: The parallel execution loop now includes stalling detection and better thread management during multi-task failures.

## 🧠 OpenVINO Robustness
The Intel® OpenVINO™ optimization tools now include automated guardrails:
- **Zero-Division Protection**: Benchmarking methods now validate input data before starting, preventing crashes if classification or embedding lists are empty.

## 📝 New Self-Correcting Workflow
We've added a new high-level example in `examples/workflows/self_correcting_research.yaml`.
- **Conditional Logic**: Demonstrates using `ConditionalTask` to evaluate research quality and automatically trigger refinement loops if quality thresholds are not met.
- **Real-world Pattern**: Shows how to build resilient, quality-aware agents using pure YAML orchestration.

---
*Refer to the main [README.md](README.md) for full architecture and installation instructions.*
