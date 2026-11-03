"""Where CV files live. The database keeps only a key; the bytes go to a directory or an S3-compatible bucket.
With no store configured (storage_backend=db) the file stays in cv_documents.file, as in small installs."""
import os
import re
from pathlib import Path
import uuid

from ..config import Settings


class StorageError(Exception):
    pass


class BlobStore:
    def put(self, org_id: int, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def new_key(self, org_id: int) -> str:
        return f"cv/{int(org_id)}/{uuid.uuid4().hex}"


class DiskStore(BlobStore):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"cv/\d+/[0-9a-f]{32}", key):
            raise StorageError("bad storage key")
        return self.root / key

    def put(self, org_id: int, data, content_type: str) -> str:
        key = self.new_key(org_id)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise StorageError("the stored file is missing")

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass


class S3Store(BlobStore):
    def __init__(self, bucket: str, client):
        self.bucket, self.s3 = bucket, client

    def put(self, org_id: int, data, content_type: str) -> str:
        key = self.new_key(org_id)
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as e:
            raise StorageError(f"could not store the file: {e}") from e
        return key

    def get(self, key: str) -> bytes:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            raise StorageError(f"could not read the stored file: {e}") from e

    def delete(self, key: str) -> None:
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            raise StorageError(f"could not delete the stored file: {e}") from e


def build(settings: Settings) -> BlobStore | None:
    backend = settings.storage_backend.lower()
    if backend == "db":
        return None
    if backend == "disk":
        return DiskStore(settings.storage_dir)
    if backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("ATS_S3_BUCKET is required when ATS_STORAGE_BACKEND=s3")
        import boto3
        client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, region_name=settings.s3_region or None,
                              aws_access_key_id=settings.s3_access_key or None, aws_secret_access_key=settings.s3_secret_key or None)
        return S3Store(settings.s3_bucket, client)
    raise RuntimeError(f"unknown ATS_STORAGE_BACKEND '{settings.storage_backend}' (use db, disk or s3)")