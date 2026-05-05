import logging
import uuid
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class RetryableEmbeddingError(Exception):
    pass


# ──────────────────── Base ────────────────────


class BaseEmbeddingService(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> list[float]:
        ...

    @abstractmethod
    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ──────────────────── GigaChat Embeddings ────────────────────


class GigaChatEmbeddingService(BaseEmbeddingService):
    """Embeddings через GigaChat API. Модель Embeddings, 1024 dims."""

    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API_URL = "https://gigachat.devices.sberbank.ru/api/v1/embeddings"

    def __init__(self, auth_key: str, model: str = "Embeddings", ca_bundle: str = ""):
        self.auth_key = auth_key
        self.model = model
        self._token: str | None = None
        # Sber certs are NOT in standard CA bundles.
        if ca_bundle:
            ssl_verify: str | bool = ca_bundle
        else:
            logger.warning(
                "GIGACHAT_CA_BUNDLE not set — TLS verification disabled for GigaChat embeddings."
            )
            ssl_verify = False
        self._client = httpx.AsyncClient(verify=ssl_verify, timeout=30.0)

    async def _get_token(self) -> str:
        response = await self._client.post(
            self.OAUTH_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self.auth_key}",
            },
            data={"scope": "GIGACHAT_API_PERS"},
        )
        response.raise_for_status()
        self._token = response.json()["access_token"]
        return self._token

    async def _ensure_token(self) -> None:
        if not self._token:
            await self._get_token()

    async def get_embedding(self, text: str) -> list[float]:
        result = await self.get_embeddings_batch([text[:8000]])
        return result[0]

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        await self._ensure_token()

        all_embeddings: list[list[float]] = []

        # GigaChat принимает до 64 текстов за раз
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = [t[:8000] for t in texts[i : i + batch_size]]
            embeddings = await self._request_embeddings(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(2):
            try:
                response = await self._client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"model": self.model, "input": texts},
                )
                if response.status_code == 401:
                    await self._get_token()
                    continue

                response.raise_for_status()
                data = response.json()["data"]
                # Сортируем по index на всякий случай
                data.sort(key=lambda x: x["index"])
                return [item["embedding"] for item in data]
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RetryableEmbeddingError(f"GigaChat rate limit: {e}")
                raise EmbeddingError(f"GigaChat HTTP error: {e}")
            except httpx.HTTPError as e:
                raise EmbeddingError(f"GigaChat connection error: {e}")

        raise EmbeddingError("GigaChat embeddings: max retries exceeded")

    async def close(self) -> None:
        await self._client.aclose()


# ──────────────────── Voyage Embeddings ────────────────────


class VoyageEmbeddingService(BaseEmbeddingService):
    """Embeddings через Voyage AI API. Модель voyage-3, 1024 dims."""

    def __init__(self, api_key: str, model: str = "voyage-3"):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def get_embedding(self, text: str) -> list[float]:
        result = await self.get_embeddings_batch([text[:8000]])
        return result[0]

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []

        # Voyage поддерживает до 128 текстов за раз
        batch_size = 128
        for i in range(0, len(texts), batch_size):
            batch = [t[:8000] for t in texts[i : i + batch_size]]
            embeddings = await self._request_embeddings(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                "/embeddings",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [item["embedding"] for item in data]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RetryableEmbeddingError(f"Voyage rate limit: {e}")
            raise EmbeddingError(f"Voyage HTTP error: {e}")
        except httpx.HTTPError as e:
            raise EmbeddingError(f"Voyage connection error: {e}")

    async def close(self) -> None:
        await self._client.aclose()


# ──────────────────── Factory ────────────────────


def create_embedding_service(provider: str, **kwargs) -> BaseEmbeddingService:
    """Создаёт embedding сервис.

    provider: "gigachat" или "voyage"
    """
    if provider == "gigachat":
        return GigaChatEmbeddingService(
            auth_key=kwargs["auth_key"],
            model=kwargs.get("model", "Embeddings"),
            ca_bundle=kwargs.get("ca_bundle", ""),
        )
    elif provider == "voyage":
        return VoyageEmbeddingService(
            api_key=kwargs["api_key"],
            model=kwargs.get("model", "voyage-3"),
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
