
import sys
import os
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from framework.orchestrator import create_orchestrator
from framework.logging import setup_logging, LogLevel

# Setup logging
setup_logging(level=LogLevel.INFO)
logger = logging.getLogger(__name__)

def initial_research(ctx):
    """Simulate initial research gathering."""
    topic = ctx.get("topic", "AI Frameworks")
    logger.info(f"Performing initial research on: {topic}")
    
    # Simulate some low-quality results sometimes to trigger refinement
    quality_score = ctx.get("forced_quality", 0.6) 
    
    return {
        "finding": f"Basic info about {topic}",
        "quality_score": quality_score
    }

def evaluate_research_quality(ctx):
    """Condition function: check if quality is high enough (> 0.7)."""
    research_data = ctx.get("initial_research_result", {})
    quality = research_data.get("quality_score", 0)
    logger.info(f"Evaluating quality: {quality}")
    return quality >= 0.8

def refine_research(ctx):
    """Refine the research if quality was low."""
    previous_finding = ctx.get("initial_research_result", {}).get("finding")
    logger.info(f"Refining previous research: {previous_finding}")
    return {
        "finding": f"Deeply researched and refined info about {previous_finding}",
        "refined": True
    }

def generate_final_report(ctx):
    """Generate final report for high-quality research."""
    research_data = ctx.get("initial_research_result", {})
    logger.info(f"Summarizing high-quality research: {research_data}")
    return {
        "report": f"Official Report: {research_data['finding']}",
        "status": "Verified"
    }

def finish_workflow(ctx):
    """Final task that consolidates the output."""
    # Check which branch was taken
    if "refine_research_result" in ctx:
        final_info = ctx["refine_research_result"]
    else:
        final_info = ctx["generate_final_report_result"]
    
    logger.info(f"Workflow finished with content: {final_info}")
    return {"final_output": final_info}

def run_demo(topic, quality):
    print("\n" + "="*50)
    print(f"RUNNING DEMO: Topic='{topic}', Forced Quality={quality}")
    print("="*50)
    
    # Initialize orchestrator
    orch = create_orchestrator()
    
    # Register functions
    orch.register_function("initial_research", initial_research)
    orch.register_function("evaluate_research_quality", evaluate_research_quality)
    orch.register_function("refine_research", refine_research)
    orch.register_function("generate_final_report", generate_final_report)
    orch.register_function("finish_workflow", finish_workflow)
    
    # Execute workflow
    workflow_path = Path(__file__).parent / "workflows" / "self_correcting_research.yaml"
    context = {"topic": topic, "forced_quality": quality}
    
    state = orch.execute_yaml(workflow_path, context=context, parallel=True)
    
    print("\nWorkflow Execution Summary:")
    print(f"Status: {state.status.value}")
    for task_name, task_state in state.task_states.items():
        print(f"  - {task_name}: {task_state['status']}")
    
    if state.errors:
        print("\nErrors:")
        for err in state.errors:
            print(f"  - {err}")

if __name__ == "__main__":
    # Case 1: Low Quality -> Should trigger Refinement
    run_demo("Quantum Computing", 0.5)
    
    # Case 2: High Quality -> Should skip Refinement and go to Final Report
    run_demo("Intel OpenVINO", 0.9)
