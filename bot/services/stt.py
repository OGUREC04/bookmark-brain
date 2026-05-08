"""Speech-to-Text service — multi-provider.

Supported providers:
- openai: OpenAI Whisper API (blocked from Russia)
- groq:   Groq Whisper API (blocked from Russia)
- yandex: Yandex SpeechKit (works in Russia/CIS)
  - sync API:  до 30 сек / 1 МБ
  - async API: до 4 часов, требует Object Storage (YandexAsyncSTTService)
  - Hybrid (YandexHybridSTTService) выбирает между sync/async по длительности

Uses raw httpx for HTTP, boto3 (sync, через asyncio.to_thread) для Object Storage.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_WHISPER_PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3",
    },
}

# Whisper limits: 25 MB, Yandex: 1 MB
_MAX_FILE_SIZE_WHISPER = 25 * 1024 * 1024
_MAX_FILE_SIZE_YANDEX = 1 * 1024 * 1024

_YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
_YANDEX_LONG_RUN_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
_YANDEX_OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{op_id}"

# Sync API: 30 sec / 1 MB. Use 28 as routing cutoff to avoid edge cases.
_YANDEX_SYNC_DURATION_LIMIT = 28
# Async API: theoretically up to 4 hours. We cap at 60 min for cost/UX safety.
_YANDEX_ASYNC_DURATION_LIMIT = 60 * 60
# Async polling: every N seconds, max M attempts.
_ASYNC_POLL_INTERVAL_SEC = 3
_ASYNC_POLL_MAX_ATTEMPTS = 200  # = ~10 min wait at 3-sec interval
# Presigned URL TTL (long enough to cover polling).
_S3_PRESIGN_TTL_SEC = 30 * 60


class STTError(Exception):
    """Raised when transcription fails."""


class WhisperSTTService:
    """Transcribe audio files using OpenAI-compatible Whisper API via raw httpx."""

    def __init__(self, api_key: str, provider: str = "openai"):
        if not api_key:
            raise ValueError("WHISPER_API_KEY is not set")
        self._api_key = api_key
        cfg = _WHISPER_PROVIDERS.get(provider, _WHISPER_PROVIDERS["openai"])
        self._url = cfg["url"]
        self._model = cfg["model"]
        logger.info("STT provider: %s (%s)", provider, self._url)

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        _validate_file(audio_path, _MAX_FILE_SIZE_WHISPER)
        mime_type = _get_mime_type(audio_path)
        file_size = audio_path.stat().st_size

        data = {
            "model": self._model,
            "response_format": "text",
        }
        if language:
            data["language"] = language

        logger.info(
            "Transcribing %s (%.1f KB, %s)",
            audio_path.name, file_size / 1024, mime_type,
        )

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(audio_path, "rb") as f:
                    response = await client.post(
                        self._url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data=data,
                        files={"file": (audio_path.name, f, mime_type)},
                    )

                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error(
                        "Whisper API error %d: %s",
                        response.status_code, error_text,
                    )
                    raise STTError(
                        f"Не удалось распознать речь (ошибка {response.status_code})"
                    )

                text = response.text.strip()
                if not text:
                    raise STTError("Whisper returned empty transcription")

                logger.info("Transcription complete: %d chars", len(text))
                return text

        except STTError:
            raise
        except httpx.TimeoutException:
            raise STTError("Whisper API timeout (120s)")
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error during transcription: {e}")


class YandexSTTService:
    """Transcribe audio via Yandex SpeechKit (works in Russia/CIS).

    API: POST https://stt.api.cloud.yandex.net/speech/v1/stt:recognize
    Auth: Api-Key header
    Body: raw binary audio (OGG Opus natively supported)
    Limits: 1 MB, 30 seconds
    """

    def __init__(self, api_key: str, folder_id: str):
        if not api_key:
            raise ValueError("YANDEX_CLOUD_API_KEY is not set")
        if not folder_id:
            raise ValueError("YANDEX_CLOUD_FOLDER_ID is not set")
        self._api_key = api_key
        self._folder_id = folder_id
        logger.info("STT provider: yandex (SpeechKit)")

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        _validate_file(audio_path, _MAX_FILE_SIZE_YANDEX)
        file_size = audio_path.stat().st_size
        lang = language or "ru-RU"

        logger.info(
            "Transcribing %s (%.1f KB) via Yandex SpeechKit",
            audio_path.name, file_size / 1024,
        )

        params = {
            "folderId": self._folder_id,
            "lang": lang,
            "format": "oggopus",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(audio_path, "rb") as f:
                    audio_data = f.read()

                response = await client.post(
                    _YANDEX_STT_URL,
                    params=params,
                    headers={
                        "Authorization": f"Api-Key {self._api_key}",
                        "Content-Type": "application/octet-stream",
                    },
                    content=audio_data,
                )

                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error(
                        "Yandex STT error %d: %s",
                        response.status_code, error_text,
                    )
                    raise STTError(
                        f"Не удалось распознать речь (ошибка {response.status_code})"
                    )

                # Response: {"result": "распознанный текст"}
                body = response.json()
                text = body.get("result", "").strip()

                if not text:
                    raise STTError("Yandex SpeechKit returned empty transcription")

                logger.info("Transcription complete: %d chars", len(text))
                return text

        except STTError:
            raise
        except json.JSONDecodeError as e:
            logger.error("Yandex STT invalid JSON: %s", e)
            raise STTError("Yandex SpeechKit вернул некорректный ответ")
        except httpx.TimeoutException:
            raise STTError("Yandex SpeechKit timeout (120s)")
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error during transcription: {e}")


class YandexAsyncSTTService:
    """Long-form Yandex SpeechKit (>30 sec audio).

    Flow:
    1. Upload audio to Yandex Object Storage (S3-compatible)
    2. POST longRunningRecognize with presigned URL of the uploaded file
    3. Poll the returned operation until done
    4. Concatenate `chunks[].alternatives[0].text` into final transcription
    5. Delete the uploaded file from Object Storage

    Uses boto3 (sync) inside `asyncio.to_thread` for S3 — single upload,
    cheaper than adding aioboto3 dependency.

    docs: https://yandex.cloud/ru/docs/speechkit/stt/transcribation
    """

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        s3_endpoint: str,
        s3_bucket: str,
        s3_access_key: str,
        s3_secret_key: str,
    ):
        if not api_key:
            raise ValueError("YANDEX_CLOUD_API_KEY is not set")
        if not folder_id:
            raise ValueError("YANDEX_CLOUD_FOLDER_ID is not set")
        if not s3_bucket:
            raise ValueError("YANDEX_S3_BUCKET is not set")
        if not s3_access_key or not s3_secret_key:
            raise ValueError("YANDEX_S3_ACCESS_KEY / YANDEX_S3_SECRET_KEY are not set")

        self._api_key = api_key
        self._folder_id = folder_id
        self._s3_endpoint = s3_endpoint
        self._s3_bucket = s3_bucket
        self._s3_access_key = s3_access_key
        self._s3_secret_key = s3_secret_key

        # Lazy-init boto3 client — heavy import, hold until first use
        self._s3_client = None
        logger.info(
            "STT provider: yandex async (bucket=%s, endpoint=%s)",
            s3_bucket, s3_endpoint,
        )

    def _get_s3(self):
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self._s3_endpoint,
                aws_access_key_id=self._s3_access_key,
                aws_secret_access_key=self._s3_secret_key,
                region_name="ru-central1",
            )
        return self._s3_client

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        if not audio_path.exists():
            raise STTError(f"Audio file not found: {audio_path}")
        if audio_path.stat().st_size == 0:
            raise STTError("Audio file is empty")

        # Уникальный ключ — чтобы параллельные запросы не конфликтовали
        object_key = f"stt-tmp/{uuid.uuid4()}{audio_path.suffix}"

        try:
            await asyncio.to_thread(self._upload, audio_path, object_key)
            # Plain URL без подписи — Yandex SpeechKit не понимает presigned URLs.
            # Объект загружен с ACL=public-read, имя — random uuid, удаляется сразу.
            audio_url = f"{self._s3_endpoint}/{self._s3_bucket}/{object_key}"
            logger.info("Yandex async STT: uploaded to s3://%s/%s", self._s3_bucket, object_key)

            operation_id = await self._start_recognition(audio_url, language)
            logger.info("Yandex async STT: operation_id=%s", operation_id)

            text = await self._poll_until_done(operation_id)
            logger.info("Yandex async STT: transcription complete (%d chars)", len(text))
            return text
        finally:
            # Cleanup даже если упало — иначе бакет засрётся
            try:
                await asyncio.to_thread(self._delete_object, object_key)
            except Exception as e:
                logger.warning("Yandex async STT: failed to delete %s: %s", object_key, e)

    # ── private ──

    def _upload(self, audio_path: Path, object_key: str) -> None:
        # ACL=public-read — Yandex SpeechKit не поддерживает presigned URLs,
        # требует прямой доступ к URL. Object key — random uuid, удаляется сразу.
        s3 = self._get_s3()
        s3.upload_file(
            str(audio_path),
            self._s3_bucket,
            object_key,
            ExtraArgs={"ACL": "public-read"},
        )

    def _delete_object(self, object_key: str) -> None:
        s3 = self._get_s3()
        s3.delete_object(Bucket=self._s3_bucket, Key=object_key)

    async def _start_recognition(self, audio_uri: str, language: str | None) -> str:
        body = {
            "config": {
                "specification": {
                    "languageCode": language or "ru-RU",
                    "audioEncoding": "OGG_OPUS",
                    "profanityFilter": False,
                    "literature_text": True,
                }
            },
            "audio": {"uri": audio_uri},
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _YANDEX_LONG_RUN_URL,
                    headers={
                        "Authorization": f"Api-Key {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error("Yandex async start error %d: %s", response.status_code, error_text)
                    raise STTError(
                        f"Не удалось запустить распознавание (ошибка {response.status_code})"
                    )
                data = response.json()
                operation_id = data.get("id")
                if not operation_id:
                    raise STTError("Yandex async API не вернул operation id")
                return operation_id
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error starting async recognition: {e}")

    async def _poll_until_done(self, operation_id: str) -> str:
        url = _YANDEX_OPERATION_URL.format(op_id=operation_id)
        headers = {"Authorization": f"Api-Key {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for attempt in range(_ASYNC_POLL_MAX_ATTEMPTS):
                    await asyncio.sleep(_ASYNC_POLL_INTERVAL_SEC)
                    response = await client.get(url, headers=headers)

                    if response.status_code != 200:
                        error_text = response.text[:300]
                        logger.error(
                            "Yandex async poll %d error %d: %s",
                            attempt, response.status_code, error_text,
                        )
                        raise STTError(
                            f"Ошибка проверки статуса распознавания ({response.status_code})"
                        )

                    data = response.json()
                    if not data.get("done"):
                        continue

                    if "error" in data:
                        err = data["error"]
                        message = err.get("message", "unknown")
                        logger.error("Yandex async operation failed: %s", err)
                        raise STTError(f"Yandex async распознавание не удалось: {message}")

                    # Готово — собираем текст из chunks с реальными таймкодами.
                    # Каждый chunk содержит words[].startTime в формате "12.345s".
                    # Префиксуем чанк маркером [mm:ss] от первого слова чанка.
                    chunks = data.get("response", {}).get("chunks", [])
                    return _format_chunks_with_timestamps(chunks)

                # Превышен лимит попыток
                logger.error("Yandex async timeout after %d polls", _ASYNC_POLL_MAX_ATTEMPTS)
                raise STTError(
                    f"Распознавание заняло слишком много времени "
                    f"(>{_ASYNC_POLL_INTERVAL_SEC * _ASYNC_POLL_MAX_ATTEMPTS} сек). Попробуй короче."
                )
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error polling async operation: {e}")


class YandexHybridSTTService:
    """Маршрутизатор между sync (≤30с) и async (>30с) Yandex SpeechKit.

    Принимает `duration` в `transcribe`. Если передан и > 28 сек — идёт async,
    иначе — sync. Если duration не известен — пытается sync (если упадёт по
    лимиту 1 МБ — ошибка вернётся пользователю).
    """

    def __init__(self, sync: YandexSTTService, async_: YandexAsyncSTTService | None):
        self._sync = sync
        self._async = async_

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        *,
        duration: float | None = None,
    ) -> str:
        if (
            duration is not None
            and duration > _YANDEX_SYNC_DURATION_LIMIT
            and self._async is not None
        ):
            if duration > _YANDEX_ASYNC_DURATION_LIMIT:
                raise STTError(
                    f"Слишком длинная запись ({int(duration)} сек). "
                    f"Максимум {_YANDEX_ASYNC_DURATION_LIMIT // 60} минут."
                )
            return await self._async.transcribe(audio_path, language)
        return await self._sync.transcribe(audio_path, language)


def create_stt_service(
    provider: str,
    *,
    whisper_api_key: str = "",
    yandex_api_key: str = "",
    yandex_folder_id: str = "",
    yandex_s3_endpoint: str = "",
    yandex_s3_bucket: str = "",
    yandex_s3_access_key: str = "",
    yandex_s3_secret_key: str = "",
) -> WhisperSTTService | YandexSTTService | YandexHybridSTTService:
    """Factory: create the right STT service based on provider name.

    `yandex` provider returns a HYBRID service if S3 credentials are configured —
    sync для коротких голосовых, async для длинных (>30с). Если S3 credentials
    пусты — возвращает только sync, длинные голосовые упадут с понятной ошибкой
    в media handler.
    """
    if provider == "yandex":
        sync = YandexSTTService(api_key=yandex_api_key, folder_id=yandex_folder_id)
        async_service: YandexAsyncSTTService | None = None
        if yandex_s3_bucket and yandex_s3_access_key and yandex_s3_secret_key:
            async_service = YandexAsyncSTTService(
                api_key=yandex_api_key,
                folder_id=yandex_folder_id,
                s3_endpoint=yandex_s3_endpoint or "https://storage.yandexcloud.net",
                s3_bucket=yandex_s3_bucket,
                s3_access_key=yandex_s3_access_key,
                s3_secret_key=yandex_s3_secret_key,
            )
        return YandexHybridSTTService(sync, async_service)
    return WhisperSTTService(api_key=whisper_api_key, provider=provider)


# ── Helpers ──────────────────────────────────────────────────


def _parse_yandex_duration(value: str | None) -> float | None:
    """Yandex API возвращает duration в форматах "12.345s" или "12s".

    Возвращает float секунд или None если не удалось распарсить.
    """
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().rstrip("s")
    try:
        return float(s)
    except ValueError:
        return None


def _format_chunks_with_timestamps(chunks: list) -> str:
    """Собирает текст из Yandex async chunks с реальными [mm:ss] маркерами.

    Каждый chunk = смысловой блок, разделённый паузой в речи. Берём startTime
    первого слова чанка. Если только 1 чанк или таймкоды не parseable —
    возвращаем plain concat без маркеров (короткое или сбой парсера).
    """
    if not chunks:
        raise STTError("Yandex async вернул пустую транскрипцию")

    # Сначала собираем (start_sec, text) кортежи по каждому chunk
    items: list[tuple[float | None, str]] = []
    for chunk in chunks:
        alternatives = chunk.get("alternatives", [])
        if not alternatives:
            continue
        alt = alternatives[0]
        text = (alt.get("text") or "").strip()
        if not text:
            continue
        # Время начала чанка = startTime первого слова
        start_sec: float | None = None
        words = alt.get("words") or []
        if words:
            start_sec = _parse_yandex_duration(words[0].get("startTime"))
        items.append((start_sec, text))

    if not items:
        raise STTError("Yandex async вернул пустую транскрипцию")

    # Если меньше 2 чанков или все startTime отсутствуют — без маркеров
    has_times = sum(1 for s, _ in items if s is not None) >= 2
    if len(items) < 2 or not has_times:
        return " ".join(t for _, t in items).strip()

    # Форматируем с маркерами [mm:ss] перед каждым чанком
    parts: list[str] = []
    for start_sec, text in items:
        if start_sec is not None:
            mm = int(start_sec // 60)
            ss = int(start_sec % 60)
            parts.append(f"[{mm:02d}:{ss:02d}] {text}")
        else:
            parts.append(text)
    return "\n".join(parts).strip()


def _validate_file(audio_path: Path, max_size: int) -> None:
    """Check file exists, not empty, within size limit."""
    if not audio_path.exists():
        raise STTError(f"Audio file not found: {audio_path}")
    file_size = audio_path.stat().st_size
    if file_size == 0:
        raise STTError("Audio file is empty")
    if file_size > max_size:
        raise STTError(
            f"Audio file too large: {file_size / 1024 / 1024:.1f} MB "
            f"(max {max_size / 1024 / 1024:.0f} MB)"
        )


def _get_mime_type(audio_path: Path) -> str:
    """Determine MIME type from file extension."""
    return {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".webm": "audio/webm",
        ".mp4": "video/mp4",
    }.get(audio_path.suffix.lower(), "application/octet-stream")
