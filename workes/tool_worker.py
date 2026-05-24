import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

# Configure structured logging instead of print statements
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("ToolWorker")

# Configuration Constants
BOOTSTRAP_SERVERS = ["localhost:9092"]
CONSUMER_TOPIC = "task_tool"
PRODUCER_TOPIC = "agent_ingress"
MAX_WORKERS = 4  # Adjust based on I/O heavy tasks


def process_task(data: Dict[str, Any], producer: KafkaProducer) -> None:
    """Processes a single task safely inside a thread pool worker."""
    task_name = data.get("task_name", "unknown_task")
    workflow_id = data.get("workflow_id")

    try:
        logger.info(f"Executing task: {task_name} for workflow: {workflow_id}")

        # Core Tool Business Logic
        input_context = data.get("context", "")
        result = f"Analyzed data for: {input_context}. Status: VALID."

        payload = {
            "workflow_id": workflow_id,
            "task_name": task_name,
            "result": result,
        }

        # Asynchronous send with callback handling
        future = producer.send(PRODUCER_TOPIC, value=payload)
        future.add_callback(
            lambda metadata: logger.debug(f"Sent success: {metadata.topic}")
        )
        future.add_errback(
            lambda exc: logger.error(f"Kafka publish failed: {exc}")
        )

    except KeyError as err:
        logger.error(f"Invalid message format schema. Missing key: {err}")
    except Exception as err:
        logger.error(f"Unexpected processing error on {task_name}: {err}")


def main():
    logger.info("Initializing Kafka Tool Worker...")

    # Initialize components safely with explicit error handling
    try:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",  # Ensures data safety
            retries=3,  # Handles transient network drops
        )

        consumer = KafkaConsumer(
            CONSUMER_TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id="tool_worker_group",  # Explicit consumer group id
            value_deserializer=lambda x: json.loads(x.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
    except KafkaError as err:
        logger.critical(f"Failed to connect to Kafka brokers: {err}")
        return

    logger.info(f"Worker listening on topic: '{CONSUMER_TOPIC}'...")

    # Use a ThreadPool to process tasks without blocking the main event consumer
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        try:
            for msg in consumer:
                if msg.value and isinstance(msg.value, dict):
                    executor.submit(process_task, msg.value, producer)
                else:
                    logger.warning("Received blank or invalid non-dict message.")
        except KeyboardInterrupt:
            logger.info("Shutdown signal received. Closing worker connections...")
        finally:
            consumer.close()
            producer.flush()
            producer.close()
            logger.info("Worker gracefully stopped.")


if __name__ == "__main__":
    main()
