"""The job-description file attached to a job: checked, its text extracted, the original kept in the database or the blob store."""
import logging
import os
import re

from . import blobstore, cv_text
from .common import NotFound, ValidationError
from .runtime import Runtime

log = logging.getLogger("ats.jd")
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def clean_name(filename: str) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    return re.sub(r"[\x00-\x1f]", "", name).strip()[:255] or "job-description"


def read(rt: Runtime, data: bytes) -> tuple[str, str]:
    """(mime, text) of an uploaded JD. Raises ValidationError({'file': ...}) when it cannot be used."""
    if len(data) > rt.settings.max_cv_bytes:
        raise ValidationError({"file": f"the file is larger than {rt.settings.max_cv_bytes // (1024 * 1024)} MB"})
    kind, text = cv_text.extract(data)
    return MIME[kind], text


def keep(ctx, rt: Runtime, data: bytes, mime: str) -> tuple[bytes, str | None]:
    """value for jobs.jd_file, storage_key). With a blob store the row keeps only the key."""
    if rt.blobs is None:
        return data, None
    try:
        return b"", rt.blobs.put(ctx.data_org_id, data, mime)
    except blobstore.StorageError as e:
        log.error("%s", e)
        raise ValidationError({"file": "the file could not be stored right now; please try again"})


def fetch(rt: Runtime, job) -> bytes:
    if not job.jd_storage_key:
        return job.jd_file or b""
    if rt.blobs is None:
        raise NotFound("this file is in file storage that is not configured on this server")
    try:
        return rt.blobs.get(job.jd_storage_key)
    except blobstore.StorageError as e:
        log.error("%s", e)
        raise NotFound("the stored file could not be read; try again shortly")


def drop(rt: Runtime, key):
    if key and rt.blobs:
        try:
            rt.blobs.delete(key)
        except blobstore.StorageError as e:
            log.warning("could not delete %s: %s", key, e)
