import json
import logging
from abc import ABC, abstractmethod

import httpx

from app.schemas import AIClassification

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — AI-ассистент BookmarkBrain для глубокой обработки сохранённого контента.
Пользователь присылает статьи, заметки, мысли, задачи — твоя работа вытащить из этого СУТЬ,
чтобы он потом быстро находил нужное и возвращался к главным идеям.

Проанализируй текст и верни ТОЛЬКО валидный JSON без markdown и пояснений.

Формат ответа:
{
  "summary": "1-2 предложения на русском: что это и зачем это могли сохранить.",
  "tags": ["тег1", "тег2", "тег3"],
  "category": "article",
  "language": "ru",
  "item_type": "content",
  "takeaway": "Одна фраза-суть на русском — главный вывод или идея.",
  "key_ideas": ["Идея 1 одним предложением", "Идея 2", "..."],
  "entities": ["Имя или продукт 1", "..."],
  "open_questions": ["Вопрос, который остаётся после прочтения", "..."]
}

Правила:

summary
  1-2 предложения на русском. Что это и зачем могли сохранить. ВСЕГДА русский.

tags
  3-5 тегов, lowercase, на русском. Примеры: дизайн, продуктивность, стартап, инструмент.

category
  Ровно одно из: article, course, idea, event, tool, video, other.

language
  Код языка оригинала: ru, en, и т.п.

item_type — ЗАЧЕМ пользователь это сохранил:
  - "action"    — это задача или намерение что-то сделать (включая свои заметки вида "попробовать X")
  - "thought"   — своя мысль/идея/инсайт, не внешний контент
  - "content"   — внешний материал для потребления (статья, видео, курс, пост)
  - "reference" — справочник, который хочется иметь под рукой (док, API, cheatsheet)
  Если сомневаешься — "content".

takeaway
  Одно предложение на русском: главный вывод/суть. То, что останется в голове через год.
  Не пересказ — именно суть. Если это мысль пользователя — переформулируй её чётко.

key_ideas
  3-7 ключевых идей из текста, каждая одним предложением на русском.
  Если текст короткий (<500 симв) или это просто мысль — можно 1-2 или [] пустой.

entities
  Имена людей, продуктов, компаний, мест, упомянутых в тексте. До 10. На языке оригинала.
  Если ничего нет — [] пустой массив.

open_questions
  Вопросы, которые текст поднимает, но не отвечает; или вопросы, которые пользователю
  стоило бы задать себе после прочтения. 0-3 шт на русском.
  Если текст чисто справочный — [] пустой.

ВАЖНО:
- Верни ТОЛЬКО JSON. Никакого текста до или после.
- Все строковые поля на русском, кроме entities.
- Массивы всегда присутствуют (пустые [] если нечего класть)."""


class ClassificationError(Exception):
    pass


class RetryableError(Exception):
    pass


def _parse_json_response(text: str) -> dict:
    """Извлекает JSON из ответа модели, даже если обёрнут в markdown."""
    text = text.strip()
    # Убираем ```json ... ``` если есть
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


# ──────────────────── Base ────────────────────


class BaseClassifier(ABC):
    @abstractmethod
    async def classify(self, text: str, url: str | None = None) -> AIClassification:
        ...

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> str:
        """Универсальный chat-completion для случаев, когда нужен НЕ JSON-классификатор.

        Используется, например, для генерации саммари по результатам поиска.
        Возвращает сырой текст ответа модели.
        """
        ...

    # Ограничение на текст для LLM-prompt.
    # Выжимаем до 12k симв (~3k токенов) — хватает для качественного анализа,
    # не раздувает стоимость. full_text уже обрезан trafilatura до MAX_ARTICLE_CHARS (20k).
    MAX_PROMPT_TEXT = 12_000

    def _build_user_prompt(self, text: str, url: str | None) -> str:
        parts = []
        if url:
            parts.append(f"URL: {url}")
        parts.append(f"Текст:\n{text[:self.MAX_PROMPT_TEXT]}")
        return "\n\n".join(parts)


# ──────────────────── GigaChat ────────────────────


class GigaChatClassifier(BaseClassifier):
    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self, auth_key: str, model: str = "GigaChat", ca_bundle: str = ""):
        self.auth_key = auth_key
        self.model = model
        self._token: str | None = None
        # Sber certs are NOT in standard CA bundles.
        # Use custom CA bundle if provided; otherwise disable verification
        # with a warning (Sber root CA must be installed separately).
        if ca_bundle:
            ssl_verify: str | bool = ca_bundle
        else:
            logger.warning(
                "GIGACHAT_CA_BUNDLE not set — TLS verification disabled for GigaChat. "
                "Set GIGACHAT_CA_BUNDLE to Sber CA cert path for secure connections."
            )
            ssl_verify = False
        self._client = httpx.AsyncClient(verify=ssl_verify, timeout=30.0)

    async def _get_token(self) -> str:
        """Получает OAuth-токен через Authorization Key."""
        import uuid
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

    async def classify(self, text: str, url: str | None = None) -> AIClassification:
        user_prompt = self._build_user_prompt(text, url)

        # Получаем токен если нет
        if not self._token:
            await self._get_token()

        content = ""
        for attempt in range(2):
            try:
                response = await self._client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1500,
                    },
                )
                # Если токен протух — обновляем и ретраим
                if response.status_code == 401:
                    await self._get_token()
                    continue

                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                data = _parse_json_response(content)
                return AIClassification(**data)
            except json.JSONDecodeError:
                if attempt == 0:
                    logger.warning("GigaChat returned non-JSON, retrying...")
                    continue
                raise ClassificationError(
                    f"GigaChat returned invalid JSON after 2 attempts: {content[:200]}"
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RetryableError(f"GigaChat rate limit: {e}")
                raise ClassificationError(f"GigaChat HTTP error: {e}")
            except httpx.HTTPError as e:
                raise ClassificationError(f"GigaChat connection error: {e}")

        raise ClassificationError("GigaChat: max retries exceeded")

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> str:
        if not self._token:
            await self._get_token()
        for attempt in range(2):
            response = await self._client.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code == 401 and attempt == 0:
                await self._get_token()
                continue
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        raise ClassificationError("GigaChat complete: max retries exceeded")


# ──────────────────── DeepSeek (OpenAI-compatible) ────────────────────


class DeepSeekClassifier(BaseClassifier):
    """DeepSeek V3 через OpenAI-совместимый endpoint.

    Дешевле GigaChat Pro, стабильнее в JSON-формате, контекст 128k.
    Использует httpx напрямую, без SDK — чтобы не тянуть лишние зависимости.
    """

    API_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def classify(self, text: str, url: str | None = None) -> AIClassification:
        user_prompt = self._build_user_prompt(text, url)

        content = ""
        for attempt in range(2):
            try:
                response = await self._client.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1500,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                data = _parse_json_response(content)
                return AIClassification(**data)
            except json.JSONDecodeError:
                if attempt == 0:
                    logger.warning("DeepSeek returned non-JSON, retrying...")
                    continue
                raise ClassificationError(
                    f"DeepSeek returned invalid JSON after 2 attempts: {content[:200]}"
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RetryableError(f"DeepSeek rate limit: {e}")
                raise ClassificationError(f"DeepSeek HTTP error: {e} — {e.response.text[:200]}")
            except httpx.HTTPError as e:
                raise ClassificationError(f"DeepSeek connection error: {e}")

        raise ClassificationError("DeepSeek: max retries exceeded")

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> str:
        response = await self._client.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


# ──────────────────── Claude ────────────────────


class ClaudeClassifier(BaseClassifier):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def classify(self, text: str, url: str | None = None) -> AIClassification:
        import anthropic

        user_prompt = self._build_user_prompt(text, url)

        for attempt in range(2):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    temperature=0.3,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = response.content[0].text
                data = _parse_json_response(content)
                return AIClassification(**data)
            except json.JSONDecodeError:
                if attempt == 0:
                    logger.warning("Claude returned non-JSON, retrying...")
                    continue
                raise ClassificationError(
                    f"Claude returned invalid JSON after 2 attempts: {content[:200]}"
                )
            except anthropic.RateLimitError as e:
                raise RetryableError(f"Claude rate limit: {e}")
            except anthropic.APIError as e:
                raise ClassificationError(f"Claude API error: {e}")

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


# ──────────────────── Factory ────────────────────


def create_classifier(provider: str, **kwargs) -> BaseClassifier:
    """Создаёт классификатор по имени провайдера.

    provider: "gigachat" | "deepseek" | "claude"
    kwargs: auth_key/api_key и опционально model
    """
    if provider == "gigachat":
        return GigaChatClassifier(
            auth_key=kwargs["auth_key"],
            model=kwargs.get("model", "GigaChat"),
            ca_bundle=kwargs.get("ca_bundle", ""),
        )
    elif provider == "deepseek":
        return DeepSeekClassifier(
            api_key=kwargs["api_key"],
            model=kwargs.get("model", "deepseek-chat"),
        )
    elif provider == "claude":
        return ClaudeClassifier(
            api_key=kwargs["api_key"],
            model=kwargs.get("model", "claude-sonnet-4-20250514"),
        )
    else:
        raise ValueError(f"Unknown AI provider: {provider}")
