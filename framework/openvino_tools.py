"""
OpenVINO ML Tools Module
Provides ML inference tools optimized with Intel OpenVINO.

Includes:
- OpenVINOTextClassifier: Text classification with OpenVINO optimization
- OpenVINOEmbedding: Text embedding generation with OpenVINO
- Benchmark utilities for comparing PyTorch vs OpenVINO latency
"""

import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from a latency benchmark."""
    model_name: str
    backend: str  # "pytorch" or "openvino"
    num_iterations: int
    total_time: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_per_sec: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "backend": self.backend,
            "num_iterations": self.num_iterations,
            "total_time_sec": round(self.total_time, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "min_latency_ms": round(self.min_latency_ms, 3),
            "max_latency_ms": round(self.max_latency_ms, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "p99_latency_ms": round(self.p99_latency_ms, 3),
            "throughput_per_sec": round(self.throughput_per_sec, 2)
        }


def calculate_percentile(latencies: List[float], percentile: float) -> float:
    """Calculate percentile from latency list."""
    sorted_latencies = sorted(latencies)
    idx = int(len(sorted_latencies) * percentile / 100)
    return sorted_latencies[min(idx, len(sorted_latencies) - 1)]


class OpenVINOTextClassifier:
    """
    Text classification using OpenVINO-optimized transformer models.
    
    Supports:
    - Sentiment analysis
    - Topic classification
    - Custom classification tasks
    
    Provides both PyTorch and OpenVINO backends for comparison.
    """
    
    def __init__(
        self,
        model_name: str = "distilbert-base-uncased-finetuned-sst-2-english",
        use_openvino: bool = True,
        device: str = "CPU",
        cache_dir: Optional[str] = None
    ):
        """
        Initialize the text classifier.
        
        Args:
            model_name: HuggingFace model ID for classification
            use_openvino: Whether to use OpenVINO optimization
            device: Device to run on ("CPU", "GPU")
            cache_dir: Directory to cache models
        """
        self.model_name = model_name
        self.use_openvino = use_openvino
        self.device = device
        self.cache_dir = cache_dir
        
        self._model = None
        self._tokenizer = None
        self._pipeline = None
        self._is_loaded = False
    
    def load(self) -> None:
        """Load the model (lazy loading)."""
        if self._is_loaded:
            return
        
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            
            logger.info(f"Loading tokenizer: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=self.cache_dir
            )
            
            if self.use_openvino:
                try:
                    from optimum.intel import OVModelForSequenceClassification
                    
                    logger.info(f"Loading OpenVINO model: {self.model_name}")
                    self._model = OVModelForSequenceClassification.from_pretrained(
                        self.model_name,
                        export=True,
                        cache_dir=self.cache_dir
                    )
                    logger.info(f"OpenVINO model loaded on {self.device}")
                    
                except ImportError:
                    logger.warning("OpenVINO not available, falling back to PyTorch")
                    self.use_openvino = False
            
            if not self.use_openvino:
                logger.info(f"Loading PyTorch model: {self.model_name}")
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_name,
                    cache_dir=self.cache_dir
                )
            
            self._is_loaded = True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
    
    def classify(self, text: str) -> Dict[str, Any]:
        """
        Classify a single text input.
        
        Args:
            text: Text to classify
            
        Returns:
            Dict with label and confidence score
        """
        if not self._is_loaded:
            self.load()
        
        assert self._tokenizer is not None, "Tokenizer not loaded"
        assert self._model is not None, "Model not loaded"
        
        import torch
        
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        )
        
        with torch.no_grad():
            outputs = self._model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)
            
        predicted_class = torch.argmax(probs, dim=-1).item()
        confidence = probs[0][int(predicted_class)].item()
        
        # Get label name if available
        label = self._model.config.id2label.get(int(predicted_class), str(predicted_class))
        
        return {
            "label": label,
            "confidence": confidence,
            "class_id": predicted_class,
            "probabilities": probs[0].tolist()
        }
    
    def classify_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """Classify multiple texts."""
        return [self.classify(text) for text in texts]
    
    def benchmark(
        self,
        test_texts: List[str],
        num_iterations: int = 100,
        warmup_iterations: int = 10
    ) -> BenchmarkResult:
        """
        Benchmark inference latency.
        
        Args:
            test_texts: List of texts to use for benchmarking
            num_iterations: Number of inference iterations
            warmup_iterations: Number of warmup iterations (not counted)
            
        Returns:
            BenchmarkResult with latency statistics
        """
        if not self._is_loaded:
            self.load()
        
        # Warmup
        logger.info(f"Running {warmup_iterations} warmup iterations...")
        for i in range(warmup_iterations):
            text = test_texts[i % len(test_texts)]
            _ = self.classify(text)
        
        # Benchmark
        if not test_texts:
            logger.warning("No test texts provided for benchmark")
            return BenchmarkResult(
                model_name=self.model_name,
                backend="openvino" if self.use_openvino else "pytorch",
                num_iterations=0,
                total_time=0,
                avg_latency_ms=0,
                min_latency_ms=0,
                max_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                throughput_per_sec=0
            )

        logger.info(f"Running {num_iterations} benchmark iterations...")
        latencies = []
        
        start_total = time.perf_counter()
        for i in range(num_iterations):
            text = test_texts[i % len(test_texts)]
            
            start = time.perf_counter()
            _ = self.classify(text)
            end = time.perf_counter()
            
            latencies.append((end - start) * 1000)  # Convert to ms
        
        total_time = time.perf_counter() - start_total
        
        return BenchmarkResult(
            model_name=self.model_name,
            backend="openvino" if self.use_openvino else "pytorch",
            num_iterations=num_iterations,
            total_time=total_time,
            avg_latency_ms=sum(latencies) / len(latencies),
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            p50_latency_ms=calculate_percentile(latencies, 50),
            p95_latency_ms=calculate_percentile(latencies, 95),
            p99_latency_ms=calculate_percentile(latencies, 99),
            throughput_per_sec=num_iterations / total_time
        )


class OpenVINOEmbedding:
    """
    Text embedding generation using OpenVINO-optimized models.
    
    Useful for:
    - Semantic search
    - Similarity comparison
    - RAG applications
    """
    
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        use_openvino: bool = True,
        device: str = "CPU",
        cache_dir: Optional[str] = None
    ):
        self.model_name = model_name
        self.use_openvino = use_openvino
        self.device = device
        self.cache_dir = cache_dir
        
        self._model = None
        self._tokenizer = None
        self._is_loaded = False
    
    def load(self) -> None:
        """Load the model."""
        if self._is_loaded:
            return
        
        try:
            from transformers import AutoTokenizer, AutoModel
            
            logger.info(f"Loading tokenizer: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=self.cache_dir
            )
            
            if self.use_openvino:
                try:
                    from optimum.intel import OVModelForFeatureExtraction
                    
                    logger.info(f"Loading OpenVINO model: {self.model_name}")
                    self._model = OVModelForFeatureExtraction.from_pretrained(
                        self.model_name,
                        export=True,
                        cache_dir=self.cache_dir
                    )
                    logger.info(f"OpenVINO embedding model loaded")
                    
                except ImportError:
                    logger.warning("OpenVINO not available, falling back to PyTorch")
                    self.use_openvino = False
            
            if not self.use_openvino:
                logger.info(f"Loading PyTorch model: {self.model_name}")
                self._model = AutoModel.from_pretrained(
                    self.model_name,
                    cache_dir=self.cache_dir
                )
            
            self._is_loaded = True
            
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
    def embed(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Numpy array with embedding vector
        """
        if not self._is_loaded:
            self.load()
        
        assert self._tokenizer is not None, "Tokenizer not loaded"
        assert self._model is not None, "Model not loaded"
        
        import torch
        
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        )
        
        with torch.no_grad():
            outputs = self._model(**inputs)
            
            # Mean pooling
            attention_mask = inputs['attention_mask']
            token_embeddings = outputs.last_hidden_state
            
            input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
            sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
            sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
            embeddings = sum_embeddings / sum_mask
        
        return embeddings[0].numpy()
    
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts."""
        embeddings = [self.embed(text) for text in texts]
        return np.stack(embeddings)
    
    def similarity(self, text1: str, text2: str) -> float:
        """Calculate cosine similarity between two texts."""
        emb1 = self.embed(text1)
        emb2 = self.embed(text2)
        
        # Cosine similarity
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        
        return float(dot_product / (norm1 * norm2))
    
    def benchmark(
        self,
        test_texts: List[str],
        num_iterations: int = 100,
        warmup_iterations: int = 10
    ) -> BenchmarkResult:
        """Benchmark embedding generation latency."""
        if not self._is_loaded:
            self.load()
        
        # Warmup
        for i in range(warmup_iterations):
            text = test_texts[i % len(test_texts)]
            _ = self.embed(text)
        
        # Benchmark
        if not test_texts:
            logger.warning("No test texts provided for benchmark")
            return BenchmarkResult(
                model_name=self.model_name,
                backend="openvino" if self.use_openvino else "pytorch",
                num_iterations=0,
                total_time=0,
                avg_latency_ms=0,
                min_latency_ms=0,
                max_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                throughput_per_sec=0
            )

        latencies = []
        
        start_total = time.perf_counter()
        for i in range(num_iterations):
            text = test_texts[i % len(test_texts)]
            
            start = time.perf_counter()
            _ = self.embed(text)
            end = time.perf_counter()
            
            latencies.append((end - start) * 1000)
        
        total_time = time.perf_counter() - start_total
        
        return BenchmarkResult(
            model_name=self.model_name,
            backend="openvino" if self.use_openvino else "pytorch",
            num_iterations=num_iterations,
            total_time=total_time,
            avg_latency_ms=sum(latencies) / len(latencies),
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            p50_latency_ms=calculate_percentile(latencies, 50),
            p95_latency_ms=calculate_percentile(latencies, 95),
            p99_latency_ms=calculate_percentile(latencies, 99),
            throughput_per_sec=num_iterations / total_time
        )


def compare_backends(
    model_class,
    model_name: str,
    test_texts: List[str],
    num_iterations: int = 50,
    warmup_iterations: int = 5
) -> Tuple[BenchmarkResult, BenchmarkResult, Dict[str, Any]]:
    """
    Compare PyTorch vs OpenVINO backend performance.
    
    Args:
        model_class: Model class to benchmark (OpenVINOTextClassifier or OpenVINOEmbedding)
        model_name: HuggingFace model ID
        test_texts: Test texts for benchmarking
        num_iterations: Number of benchmark iterations
        warmup_iterations: Warmup iterations
        
    Returns:
        Tuple of (pytorch_result, openvino_result, comparison_summary)
    """
    print(f"\n{'='*60}")
    print(f"  Benchmark: {model_name}")
    print(f"{'='*60}")
    
    # PyTorch benchmark
    print("\n[1/2] Benchmarking PyTorch backend...")
    pytorch_model = model_class(model_name=model_name, use_openvino=False)
    pytorch_model.load()
    pytorch_result = pytorch_model.benchmark(test_texts, num_iterations, warmup_iterations)
    print(f"  PyTorch Avg Latency: {pytorch_result.avg_latency_ms:.2f} ms")
    
    # OpenVINO benchmark
    print("\n[2/2] Benchmarking OpenVINO backend...")
    openvino_model = model_class(model_name=model_name, use_openvino=True)
    openvino_model.load()
    openvino_result = openvino_model.benchmark(test_texts, num_iterations, warmup_iterations)
    print(f"  OpenVINO Avg Latency: {openvino_result.avg_latency_ms:.2f} ms")
    
    # Calculate speedup
    speedup = pytorch_result.avg_latency_ms / openvino_result.avg_latency_ms
    latency_reduction = (1 - openvino_result.avg_latency_ms / pytorch_result.avg_latency_ms) * 100
    throughput_improvement = (openvino_result.throughput_per_sec / pytorch_result.throughput_per_sec - 1) * 100
    
    comparison = {
        "model_name": model_name,
        "speedup_factor": round(speedup, 2),
        "latency_reduction_percent": round(latency_reduction, 1),
        "throughput_improvement_percent": round(throughput_improvement, 1),
        "pytorch": pytorch_result.to_dict(),
        "openvino": openvino_result.to_dict()
    }
    
    return pytorch_result, openvino_result, comparison


def print_benchmark_comparison(comparison: Dict[str, Any]) -> None:
    """Print a formatted benchmark comparison."""
    print(f"\n{'='*60}")
    print(f"  BENCHMARK RESULTS: {comparison['model_name']}")
    print(f"{'='*60}")
    
    pytorch = comparison['pytorch']
    openvino = comparison['openvino']
    
    print(f"\n{'Metric':<25} {'PyTorch':>15} {'OpenVINO':>15} {'Improvement':>15}")
    print("-" * 70)
    print(f"{'Avg Latency (ms)':<25} {pytorch['avg_latency_ms']:>15.2f} {openvino['avg_latency_ms']:>15.2f} {comparison['latency_reduction_percent']:>14.1f}%")
    print(f"{'Min Latency (ms)':<25} {pytorch['min_latency_ms']:>15.2f} {openvino['min_latency_ms']:>15.2f}")
    print(f"{'Max Latency (ms)':<25} {pytorch['max_latency_ms']:>15.2f} {openvino['max_latency_ms']:>15.2f}")
    print(f"{'P50 Latency (ms)':<25} {pytorch['p50_latency_ms']:>15.2f} {openvino['p50_latency_ms']:>15.2f}")
    print(f"{'P95 Latency (ms)':<25} {pytorch['p95_latency_ms']:>15.2f} {openvino['p95_latency_ms']:>15.2f}")
    print(f"{'P99 Latency (ms)':<25} {pytorch['p99_latency_ms']:>15.2f} {openvino['p99_latency_ms']:>15.2f}")
    print(f"{'Throughput (req/sec)':<25} {pytorch['throughput_per_sec']:>15.2f} {openvino['throughput_per_sec']:>15.2f} {comparison['throughput_improvement_percent']:>14.1f}%")
    print("-" * 70)
    print(f"{'SPEEDUP FACTOR':<25} {comparison['speedup_factor']:>15.2f}x")
    print()


# =============================================================================
# Tool Integration - Wrap OpenVINO models as framework Tools
# =============================================================================

try:
    from .tools import Tool, Schema, SchemaField
    
    class TextClassifierTool(Tool):
        """
        Tool wrapper for OpenVINO text classification.
        
        Integrates with the framework's Tool system for use in flows.
        """
        
        name = "text_classifier"
        description = "Classify text using OpenVINO-optimized transformer model"
        tags = ["ml", "classification", "openvino", "nlp"]
        
        def __init__(
            self,
            model_name: str = "distilbert-base-uncased-finetuned-sst-2-english",
            use_openvino: bool = True
        ):
            super().__init__()
            self._classifier = OpenVINOTextClassifier(
                model_name=model_name,
                use_openvino=use_openvino
            )
        
        @property
        def input_schema(self) -> Schema:
            return Schema(fields={
                "text": SchemaField(
                    type="string",
                    description="Text to classify",
                    required=True
                )
            })
        
        @property
        def output_schema(self) -> Schema:
            return Schema(fields={
                "label": SchemaField(
                    type="string",
                    description="Classification label"
                ),
                "confidence": SchemaField(
                    type="float",
                    description="Confidence score (0-1)"
                ),
                "class_id": SchemaField(
                    type="integer",
                    description="Numeric class ID"
                )
            })
        
        def _execute(
            self,
            validated_input: Dict[str, Any],
            memory: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
            result = self._classifier.classify(validated_input["text"])
            return {
                "label": result["label"],
                "confidence": result["confidence"],
                "class_id": result["class_id"]
            }
    
    
    class TextEmbeddingTool(Tool):
        """
        Tool wrapper for OpenVINO text embeddings.
        
        Generates vector embeddings for semantic search and RAG.
        """
        
        name = "text_embedding"
        description = "Generate text embeddings using OpenVINO-optimized model"
        tags = ["ml", "embedding", "openvino", "nlp", "rag"]
        
        def __init__(
            self,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            use_openvino: bool = True
        ):
            super().__init__()
            self._embedder = OpenVINOEmbedding(
                model_name=model_name,
                use_openvino=use_openvino
            )
        
        @property
        def input_schema(self) -> Schema:
            return Schema(fields={
                "text": SchemaField(
                    type="string",
                    description="Text to embed",
                    required=True
                )
            })
        
        @property
        def output_schema(self) -> Schema:
            return Schema(fields={
                "embedding": SchemaField(
                    type="list",
                    description="Embedding vector as list of floats"
                ),
                "dimensions": SchemaField(
                    type="integer",
                    description="Number of embedding dimensions"
                )
            })
        
        def _execute(
            self,
            validated_input: Dict[str, Any],
            memory: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
            embedding = self._embedder.embed(validated_input["text"])
            return {
                "embedding": embedding.tolist(),
                "dimensions": len(embedding)
            }
    
    
    class SimilarityTool(Tool):
        """
        Tool for computing text similarity using OpenVINO embeddings.
        """
        
        name = "text_similarity"
        description = "Compute semantic similarity between two texts"
        tags = ["ml", "similarity", "openvino", "nlp"]
        
        def __init__(
            self,
            model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
            use_openvino: bool = True
        ):
            super().__init__()
            self._embedder = OpenVINOEmbedding(
                model_name=model_name,
                use_openvino=use_openvino
            )
        
        @property
        def input_schema(self) -> Schema:
            return Schema(fields={
                "text1": SchemaField(
                    type="string",
                    description="First text",
                    required=True
                ),
                "text2": SchemaField(
                    type="string",
                    description="Second text",
                    required=True
                )
            })
        
        @property
        def output_schema(self) -> Schema:
            return Schema(fields={
                "similarity": SchemaField(
                    type="float",
                    description="Cosine similarity score (-1 to 1)"
                ),
                "is_similar": SchemaField(
                    type="boolean",
                    description="Whether texts are similar (>0.7)"
                )
            })
        
        def _execute(
            self,
            validated_input: Dict[str, Any],
            memory: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
            similarity = self._embedder.similarity(
                validated_input["text1"],
                validated_input["text2"]
            )
            return {
                "similarity": similarity,
                "is_similar": similarity > 0.7
            }

except ImportError:
    # Tools module not available, skip Tool wrappers
    pass
