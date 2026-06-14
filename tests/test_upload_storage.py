"""TDD for shared.media.storage.UploadStorage (3sr, шаг 2).

Тонкая обёртка над Yandex Object Storage (S3-совместимый) для передачи
загруженного из Mini App файла из API-контейнера в worker-контейнер: API
кладёт байты (put_bytes), worker качает (download_to_path) и удаляет (delete).

Без живого S3: boto3-клиент замокан. Реальный прогон — на деплое. Паттерн
ленивой инициализации с lock зеркалит YandexAsyncSTTService в stt.py.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.media.storage import UploadStorage

_KW = dict(
    endpoint="https://storage.yandexcloud.net",
    bucket="bm-uploads",
    access_key="AK",
    secret_key="SK",
)


def _storage(**overrides):
    return UploadStorage(**{**_KW, **overrides})


# ── construction / validation ─────────────────────────────────────────────

def test_missing_bucket_raises():
    with pytest.raises(ValueError, match="bucket"):
        _storage(bucket="")


def test_missing_credentials_raise():
    with pytest.raises(ValueError, match="ACCESS|SECRET|access|secret"):
        _storage(access_key="")
    with pytest.raises(ValueError, match="ACCESS|SECRET|access|secret"):
        _storage(secret_key="")


# ── operations ────────────────────────────────────────────────────────────

async def test_put_bytes_calls_put_object():
    client = MagicMock()
    with patch("boto3.client", return_value=client) as mk:
        st = _storage()
        await st.put_bytes("uploads/abc.ogg", b"audio-bytes", content_type="audio/ogg")

    # boto3 client построен с нужными кредами/эндпоинтом
    _, kwargs = mk.call_args
    assert kwargs["endpoint_url"] == _KW["endpoint"]
    assert kwargs["aws_access_key_id"] == "AK"
    assert kwargs["aws_secret_access_key"] == "SK"

    client.put_object.assert_called_once()
    _, pkw = client.put_object.call_args
    assert pkw["Bucket"] == "bm-uploads"
    assert pkw["Key"] == "uploads/abc.ogg"
    assert pkw["Body"] == b"audio-bytes"
    assert pkw["ContentType"] == "audio/ogg"


async def test_put_bytes_without_content_type_omits_it():
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        st = _storage()
        await st.put_bytes("uploads/x.bin", b"data")
    _, pkw = client.put_object.call_args
    assert "ContentType" not in pkw


async def test_download_to_path_calls_download_file(tmp_path: Path):
    client = MagicMock()
    dest = tmp_path / "out.ogg"
    with patch("boto3.client", return_value=client):
        st = _storage()
        await st.download_to_path("uploads/abc.ogg", dest)
    client.download_file.assert_called_once_with("bm-uploads", "uploads/abc.ogg", str(dest))


async def test_delete_calls_delete_object():
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        st = _storage()
        await st.delete("uploads/abc.ogg")
    client.delete_object.assert_called_once_with(Bucket="bm-uploads", Key="uploads/abc.ogg")


async def test_client_initialised_lazily_and_once():
    client = MagicMock()
    with patch("boto3.client", return_value=client) as mk:
        st = _storage()
        assert mk.call_count == 0  # ленивая: до первой операции клиента нет
        await st.put_bytes("k1", b"a")
        await st.delete("k1")
        assert mk.call_count == 1  # переиспользуется, не пересоздаётся
