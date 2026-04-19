import json
import logging
from kafka import KafkaConsumer, KafkaProducer
from optimum.intel import OVModelForCausalLM
from transformers import AutoTokenizer, pipeline

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LLM Worker] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
DEVICE = "CPU"  # Change to "GPU" if you have Intel Iris Xe

logger.info(f"Loading Intel OpenVINO Model: {MODEL_ID} on {DEVICE}...")

try:
    model = OVModelForCausalLM.from_pretrained(MODEL_ID, export=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model.to(DEVICE)
    logger.info("Model loaded successfully.")
except Exception as e:
    logger.critical(f"Failed to load model: {e}")
    raise SystemExit(1)

# Kafka Setup
try:
    producer = KafkaProducer(
        bootstrap_servers='localhost:9092',
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    consumer = KafkaConsumer(
        'task_llm',
        bootstrap_servers='localhost:9092',
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )
    logger.info("Kafka producer and consumer initialized.")
except Exception as e:
    logger.critical(f"Failed to connect to Kafka: {e}")
    raise SystemExit(1)

logger.info("LLM Worker started. Waiting for messages...")

for msg in consumer:
    data = msg.value
    task_name = data.get('task_name', 'unknown')
    workflow_id = data.get('workflow_id', 'unknown')

    logger.info(f"Processing task: {task_name} (workflow: {workflow_id})")

    try:
        # Validate required fields
        if 'definition' not in data or 'prompt' not in data['definition']:
            raise ValueError("Message missing required field: definition.prompt")
        if 'context' not in data:
            raise ValueError("Message missing required field: context")

        # Construct prompt
        prompt_template = data['definition']['prompt']
        user_input = data['context']
        PIPE = chr(124)
        full_prompt = (
            f"<{PIPE}system{PIPE}>You are a helpful assistant.</{PIPE}s{PIPE}>"
            f"<{PIPE}user{PIPE}>{prompt_template.format(input=user_input)}</{PIPE}s{PIPE}>"
            f"<{PIPE}assistant{PIPE}>"
        )

        # Run inference
        inputs = tokenizer(full_prompt, return_tensors="pt")
        outputs = model.generate(**inputs, max_new_tokens=128)
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Clean response — remove prompt echo
        final_output = response.split(f'<{PIPE}assistant{PIPE}>')[-1].strip()

        logger.info(f"Task '{task_name}' inference complete.")

        # Send success result back to orchestrator
        producer.send('agent_ingress', {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "result": final_output,
            "status": "success"
        })

        # Flush to ensure message is delivered
        producer.flush()
        logger.info(f"Task '{task_name}' result sent and flushed successfully.")

    except ValueError as e:
        logger.error(f"Task '{task_name}' validation error: {e}")
        producer.send('agent_ingress', {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "error": str(e),
            "status": "failed"
        })
        producer.flush()

    except MemoryError as e:
        logger.error(f"Task '{task_name}' ran out of memory: {e}")
        producer.send('agent_ingress', {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "error": "Out of memory during inference",
            "status": "failed"
        })
        producer.flush()

    except Exception as e:
        logger.error(f"Task '{task_name}' failed unexpectedly: {e}", exc_info=True)
        producer.send('agent_ingress', {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "error": str(e),
            "status": "failed"
        })
        producer.flush()
