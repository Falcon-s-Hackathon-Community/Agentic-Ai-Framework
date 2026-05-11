from fastapi.testclient import TestClient
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_server_starts_without_kafka():
    """Verify that the API server starts up even if Kafka is unavailable."""
    print("Testing server startup without Kafka...")
    
    # This import would fail before the fix if Kafka was down
    from api.server import app, get_kafka_producer
    
    client = TestClient(app)
    
    # 1. Test health check (should work perfectly)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "IntelAgentCore Gateway Online"}
    print("Health check PASSED without Kafka.")
    
    # 2. Test get_kafka_producer (should return None but not crash)
    producer = get_kafka_producer()
    assert producer is None or hasattr(producer, 'send'), "Producer should be None or a valid producer object"
    print("Lazy-init check PASSED (No crash).")

if __name__ == "__main__":
    try:
        test_server_starts_without_kafka()
        print("\nPR #4 verification successful!")
    except Exception as e:
        print(f"\nPR #4 verification FAILED: {e}")
        sys.exit(1)
