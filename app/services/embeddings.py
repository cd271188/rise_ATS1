"""Local text embeddings (fastembed / ONNX). No per-call cost and no data leaves the server."""
import threading

import numpy as np


class EmbeddingError(RuntimeError):
    pass


class FastEmbedder:
    def __init__(self, model: str, cache_dir: str):
        self.model_name = model
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
            except Exception as e:
                raise EmbeddingError("the embedding model could not be loaded") from e
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 vectors, one row per text."""
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with self._lock:
            model = self._load()
            try:
                rows = list(model.embed([t[:4000] for t in texts]))
            except Exception as e:
                raise EmbeddingError("embedding failed") from e
            m = np.asarray(rows, dtype=np.float32)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            return m / np.where(norms == 0, 1, norms)

                
def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    if isinstance(blob, (bytes, bytearray, memoryview)):
        return np.frombuffer(blob, dtype=np.float32).copy()
    return np.asarray(blob, dtype=np.float32).reshape(-1)


def read_row(row, db) -> np.ndarray | None:
    """Read the native vector on PostgreSQL, falling back to the legacy blob during rollout."""
    if db.get_bind().dialect.name == "postgresql":
        vector = getattr(row, "embedding_vector", None)
        if vector is not None:
            return from_bytes(vector)
    blob = getattr(row, "embedding", None)
    return from_bytes(blob) if blob is not None else None


def write_row(row, vec: np.ndarray | None, db) -> None:
    if db.get_bind().dialect.name == "postgresql":
        row.embedding_vector = None if vec is None else np.asarray(vec, dtype=np.float32).reshape(-1)
        row.embedding = None
    else:
        row.embedding = to_bytes(vec) if vec is not None else None


def storage_values(vec: np.ndarray | None, db) -> dict:
    if db.get_bind().dialect.name == "postgresql":
        return {"embedding": None, "embedding_vector": None if vec is None else np.asarray(vec, dtype=np.float32).reshape(-1)}
    return {"embedding": to_bytes(vec) if vec is not None else None}


def has_row(row, db) -> bool:
    if db.get_bind().dialect.name == "postgresql" and getattr(row, "embedding_vector", None) is not None:
        return True
    return getattr(row, "embedding", None) is not None
