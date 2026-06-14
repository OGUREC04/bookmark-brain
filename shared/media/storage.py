"""Object storage for media uploads from the Mini App (3sr).

Thin async wrapper over an S3-compatible bucket (Yandex Object Storage) used to
hand a freshly-uploaded file from the API container to the worker container —
they share no local volume. The API ``put_bytes`` the upload; the worker
``download_to_path`` it, processes, then ``delete`` it.

Config (endpoint / bucket / keys) is injected by the caller — this module never
reads a project settings object, so ``shared`` stays a dependency leaf (guarded
by tests/test_shared_is_leaf.py). boto3 is imported lazily and the sync client
runs inside ``asyncio.to_thread``, mirroring ``YandexAsyncSTTService`` in
``stt.py``.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "ru-central1"


class UploadStorage:
    """Put / download / delete bytes on an S3-compatible bucket (async)."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = _DEFAULT_REGION,
    ) -> None:
        if not bucket:
            raise ValueError("UploadStorage: bucket is not set")
        if not access_key or not secret_key:
            raise ValueError("UploadStorage: access_key / secret_key are not set")
        self._endpoint = endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region

        # Lazy-init: boto3 import is heavy, hold until first use. Lock guards the
        # race when parallel uploads reach _get_client via asyncio.to_thread
        # (two threads could otherwise both see None). Same pattern as stt.py.
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        # Double-checked locking: fast path skips the lock once initialised.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import boto3

                    self._client = boto3.client(
                        "s3",
                        endpoint_url=self._endpoint,
                        aws_access_key_id=self._access_key,
                        aws_secret_access_key=self._secret_key,
                        region_name=self._region,
                    )
        return self._client

    async def put_bytes(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None:
        await asyncio.to_thread(self._put_bytes_sync, key, data, content_type)

    async def download_to_path(self, key: str, dest: Path) -> None:
        await asyncio.to_thread(self._download_sync, key, dest)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, key)

    # ── sync bodies (run in a worker thread) ──────────────────────────────

    def _put_bytes_sync(self, key: str, data: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._get_client().put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def _download_sync(self, key: str, dest: Path) -> None:
        self._get_client().download_file(self._bucket, key, str(dest))

    def _delete_sync(self, key: str) -> None:
        self._get_client().delete_object(Bucket=self._bucket, Key=key)
