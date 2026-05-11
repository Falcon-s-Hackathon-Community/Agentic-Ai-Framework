from unittest.mock import MagicMock, patch
from framework.openvino_tools import OpenVINOEmbedding

def test_openvino_embedding_benchmark_empty_list():
    """Test that benchmark handles empty test_texts without crashing."""
    
    # Mocking the load and embed methods to avoid requiring actual ML models/OpenVINO
    with patch.object(OpenVINOEmbedding, 'load', return_value=None), \
         patch.object(OpenVINOEmbedding, 'embed', return_value=None):
        
        embedder = OpenVINOEmbedding(model_name="test-model")
        embedder._is_loaded = True # Pretend it's loaded
        
        print("Testing benchmark with empty list...")
        # This should NOT raise ZeroDivisionError
        result = embedder.benchmark(test_texts=[], num_iterations=10, warmup_iterations=5)
        
        assert result.num_iterations == 0
        assert result.avg_latency_ms == 0
        print("Test PASSED: Empty list handled correctly.")

def test_openvino_classifier_benchmark_empty_list():
    """Test that classifier benchmark handles empty test_texts without crashing."""
    from framework.openvino_tools import OpenVINOTextClassifier
    
    with patch.object(OpenVINOTextClassifier, 'load', return_value=None), \
         patch.object(OpenVINOTextClassifier, 'classify', return_value=None):
        
        classifier = OpenVINOTextClassifier(model_name="test-model")
        classifier._is_loaded = True
        
        print("Testing classifier benchmark with empty list...")
        result = classifier.benchmark(test_texts=[], num_iterations=10, warmup_iterations=5)
        
        assert result.num_iterations == 0
        assert result.avg_latency_ms == 0
        print("Classifier Test PASSED.")

if __name__ == "__main__":
    try:
        test_openvino_embedding_benchmark_empty_list()
        test_openvino_classifier_benchmark_empty_list()
    except ZeroDivisionError:
        print("Test FAILED: Caught ZeroDivisionError!")
    except Exception as e:
        print(f"Test FAILED: Caught unexpected exception: {type(e).__name__}: {e}")

