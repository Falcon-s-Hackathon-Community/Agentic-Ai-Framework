from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kafka import KafkaProducer
from framework.sdk import Agent, ToolTask, LLMTask
import json
import uuid

app = FastAPI(title="IntelAgentCore Gateway")

# Kafka Producer setup
producer = KafkaProducer(
    bootstrap_servers='localhost:9092',
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)


class WorkflowRequest(BaseModel):
    agent_name: str
    user_input: str


@app.post("/api/run")
async def run_workflow(request: WorkflowRequest):
    workflow_id = str(uuid.uuid4())

    if request.agent_name == "audit_bot":
        # Create agent and flow using correct framework classes
        agent = Agent("Audit_Bot")
        flow = agent.create_flow("audit_flow")

        # Use correct task subclasses — never instantiate base Task directly
        t1 = ToolTask(
            name="scan_code",
            tool_name="code_scanner"
        )
        t2 = LLMTask(
            name="summarize",
            prompt_template="Summarize this security scan result: {scan_code_result}"
        )

        flow.add_task(t1)
        flow.add_task(t2)

        # Add dependency so summarize runs after scan_code completes
        flow.add_dependency("summarize", depends_on="scan_code")

        # Execute the flow with the user input as context
        result = agent.run_flow(
            "audit_flow",
            context={"input": request.user_input}
        )

        return {
            "status": "completed" if result.success else "failed",
            "workflow_id": workflow_id,
            "errors": result.errors
        }

    else:
        raise HTTPException(status_code=404, detail="Agent not found")


@app.get("/")
def health_check():
    return {"status": "IntelAgentCore Gateway Online"}


# Run with: uvicorn api.server:app --reload --port 8000