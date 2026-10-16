import json
import logging
from queue import Empty, Queue
from threading import Thread
import time
from typing import Any, Dict

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from optimum.intel import OVModelForCausalLM
from transformers import AutoTokenizer

# Standardized logging pattern
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LLM Worker] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Constants and Configuration
MODEL_ID = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
DEVICE = "CPU"
BOOTSTRAP_SERVERS = ["localhost:9092"]
CONSUMER_TOPIC = "task_llm"
PRODUCER_TOPIC = "agent_ingress"

# Safe pipeline string tokens
PIPE = "|"
SYSTEM_PROMPT = f"<{PIPE}system{PIPE}>You are a helpful assistant.</{PIPE}s{PIPE}>"


def initialize_llm():
    """Loads and compiles the OpenVINO model target safely."""
    logger.info(f"Loading Intel OpenVINO Model: {MODEL_ID} on {DEVICE}...")
    try:
        # export=True is great for first run, but compiles model statically
        model = OVModelForCausalLM.from_pretrained(MODEL_ID, export=True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        model.to(DEVICE)
        
        # Warmup/Compile step to prevent first-request latency spikes
        logger.info("Compiling model graph execution structures...")
        warmup_inputs = tokenizer(f"{SYSTEM_PROMPT}<{PIPE}user{PIPE}>Hi</{PIPE}s{PIPE}>", return_tensors="pt")
        _ = model.generate(**warmup_inputs, max_new_tokens=5)
        
        logger.info("Model loaded and warmed up successfully.")
        return model, tokenizer
    except Exception as err:
        logger.critical(f"Failed to load or compile OpenVINO model backend: {err}")
        raise SystemExit(1)


def process_inference_queue(queue: Queue, model: OVModelForCausalLM, tokenizer: AutoTokenizer, producer: KafkaProducer):
    """
    Dedicated background worker thread for heavy CPU execution.
    Keeps inference isolated away from the Kafka consumer event loop.
    """
    while True:
        task_data = queue.get()
        if task_data is None:  # Shutdown signal matching
            queue.task_done()
            break

        data, task_name, workflow_id = task_data
        logger.info(f"Starting background inference for task: {task_name}")

        try:
            # Defensive validation matching upstream schemas
            definition = data.get("definition", {})
            prompt_template = definition.get("prompt")
            user_input = data.get("context")

            if not prompt_template or user_input is None:
                raise ValueError("Message body structure is missing mandatory 'definition.prompt' or 'context' keys.")

            # Linear formatting to prevent broken escaping strings
            full_prompt = (
                f"{SYSTEM_PROMPT}"
                f"<{PIPE}user{PIPE}>{prompt_template.format(input=user_input)}</{PIPE}s{PIPE}>"
                f"<{PIPE}assistant{PIPE}>"
            )

            # Execution block with automated cleanup
            inputs = tokenizer(full_prompt, return_tensors="pt")
            outputs = model.generate(**inputs, max_new_tokens=128, do_sample=False)
            response = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Clean response extraction bypassing system context echo tokens
            final_output = response.split(f"<{PIPE}assistant{PIPE}>")[-1].strip()

            payload = {
                "workflow_id": workflow_id,
                "task_name": task_name,
                "result": final_output,
                "status": "success"
            }
            logger.info(f"Task '{task_name}' token generation completed successfully.")

        except (ValueError, KeyError) as err:
            logger.error(f"Validation error encountered on payload schema: {err}")
            payload = {"workflow_id": workflow_id, "task_name": task_name, "error": str(err), "status": "failed"}
        except MemoryError:
            logger.error(f"Inference processing aborted: Engine hardware ran out of RAM capacity bounds.")
            payload = {"workflow_id": workflow_id, "task_name": task_name, "error": "Out of memory error during hardware execution", "status": "failed"}
        except Exception as err:
            logger.error(f"Unexpected execution pipeline failure: {err}", exc_info=True)
            payload = {"workflow_id": workflow_id, "task_name": task_name, "error": f"Internal Runtime Error: {str(err)}", "status": "failed"}

        # Dispatch results back asynchronously
        try:
            producer.send(PRODUCER_TOPIC, value=payload)
        except Exception as err:
            logger.error(f"Failed to submit execution response back to Kafka outbound wire: {err}")
        
        queue.task_done()


def main():
    # Phase 1: Initialize Local Model Infrastructure
    model, tokenizer = initialize_llm()

    # Phase 2: Establish Resilient Messaging Layer Connections
    try:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks=1,
            retries=3
        )
        consumer = KafkaConsumer(
            CONSUMER_TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id="llm_inference_workers",
            value_deserializer=lambda x: json.loads(x.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
            max_poll_interval_ms=300000  # 5 Minutes safety buffer
        )
        logger.info("Kafka consumer and producer channels mounted.")
    except KafkaError as err:
        logger.critical(f"Aborting worker startup. Messaging network broker is unreachable: {err}")
        return

    # Phase 3: Spin Up Thread Isolation Topologies
    inference_queue = Queue(maxsize=50)
    worker_thread = Thread(
        target=process_inference_queue, 
        args=(inference_queue, model, tokenizer, producer),
        daemon=True
    )
    worker_thread.start()

    logger.info("LLM Kafka Engine operational. Intercepting input tasks...")

    # Main Consumer Loop (Kept light, fast, and highly responsive to heartbeat cycles)
    try:
        for msg in consumer:
            if not msg.value or not isinstance(msg.value, dict):
                logger.warning("Dropped malformed structural data block from stream topic.")
                continue

            data = msg.value
            task_name = data.get("task_name", "unnamed_task")
            workflow_id = data.get("workflow_id", "anonymous_flow")

            logger.info(f"Enqueuing incoming task to work queue: {task_name}")
            
            # Submits back to processing loop without waiting for generation to finish
            inference_queue.put((data, task_name, workflow_id))

    except KeyboardInterrupt:
        logger.info("Shutdown trap received. Flushing execution nodes clean...")
    finally:
        # Graceful cleanup steps
        inference_queue.put(None)  # Poison pill to kill the background thread
        worker_thread.join(timeout=10.0)
        
        consumer.close()
        producer.flush()
        producer.close()
        logger.info("LLM Worker process offline cleanly.")


if __name__ == "__main__":
    main()
