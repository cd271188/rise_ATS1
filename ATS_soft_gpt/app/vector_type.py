"""Database type for normalized float32 embeddings.

PostgreSQL stores embeddings as pgvector vectors. SQLite and older databases keep the
legacy float32 byte representation so local development remains dependency-light.
"""
from sqlalchemy.types import LargeBinary, TypeDecorator


class EmbeddingVector(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector
            except ImportError as exc:
                raise RuntimeError("install the pgvector Python package to use PostgreSQL embeddings") from exc
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        import numpy as np

        if isinstance(value, (bytes, bytearray, memoryview)):
            vector = np.frombuffer(value, dtype=np.float32)
        else:
            vector = np.asarray(value, dtype=np.float32).reshape(-1)
        if vector.size != self.dimensions:
            raise ValueError(f"embedding must have {self.dimensions} dimensions; got {vector.size}")
        if not np.isfinite(vector).all():
            raise ValueError("embedding contains a non-finite value")
        if dialect.name == "postgresql":
            return vector.tolist()
        return vector.tobytes()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        import numpy as np

        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            if len(raw) % 4:
                raise ValueError("stored embedding has an invalid float32 byte length")
            return np.frombuffer(raw, dtype=np.float32).copy()
        return np.asarray(value, dtype=np.float32).reshape(-1)
