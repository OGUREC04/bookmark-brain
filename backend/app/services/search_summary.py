"""LLM-генерация суммари по результатам поиска (а-ля Google one-box).

Берёт top-N результатов поиска, отдаёт их выжимки в LLM,
получает 2-3 предложения суммари с цитированием [1], [2], ...

Никогда не бросает наружу — если LLM упал, summary = None,
поиск возвращается без саммари.
"""
import logging
import re

from app.models import Bookmark
from app.services.ai_classifier import BaseClassifier

logger = logging.getLogger(__name__)

# Сколько верхних результатов скармливаем модели.
# 5 — баланс между контекстом и релевантностью; ниже плохо,
# выше — модель начнёт цитировать слабые матчи.
TOP_N_FOR_SUMMARY = 5

# Если score лучшего результата ниже порога — не делаем summary вообще,
# потому что нечего суммаризировать (поиск нашёл шум).
MIN_SCORE_FOR_SUMMARY = 0.15

# Минимальная длина запроса в словах. Для односложных ("react", "todo")
# summary бесполезна.
MIN_QUERY_WORDS = 2


SYSTEM_PROMPT = """Ты — поисковый ассистент BookmarkBrain.

Пользователь сделал запрос на естественном языке. Я нашёл закладки и дам тебе их выжимки.
Твоя задача — написать КОРОТКИЙ ответ-саммари (2-4 предложения), который синтезирует
информацию из найденных закладок и отвечает на запрос пользователя.

Правила:
- Цитируй закладки маркерами [1], [2], [3] — это номера в моём списке
- Можно цитировать несколько в одном предложении: "X происходит [1][3], но при этом Y [2]"
- НЕ выдумывай факты, которых нет в выжимках
- Если выжимки не отвечают на запрос — честно скажи "В сохранённых закладках нет ответа на этот запрос"
- Пиши на русском, естественным языком, без канцелярита
- Никаких markdown-заголовков, списков, жирного — только сплошной текст с маркерами [N]
- Не пересказывай каждую закладку — синтезируй общую картину"""


def _format_bookmark_for_prompt(idx: int, b: Bookmark) -> str:
    """Превращает закладку в строчку для prompt'а."""
    title = (b.title or "Без заголовка").strip()
    parts = [f"[{idx}] {title}"]

    if b.takeaway:
        parts.append(f"   Суть: {b.takeaway}")
    elif b.summary:
        parts.append(f"   {b.summary}")

    if b.key_ideas:
        ideas = "; ".join(b.key_ideas[:5])
        parts.append(f"   Идеи: {ideas}")

    return "\n".join(parts)


class SearchSummarizer:
    def __init__(self, classifier: BaseClassifier):
        self.classifier = classifier

    async def summarize(
        self,
        query: str,
        results: list[tuple[Bookmark, float]],
    ) -> str | None:
        """Генерирует суммари по топ-N результатам.

        Возвращает текст с маркерами [1]..[N], или None если:
        - запрос слишком короткий
        - результатов нет / все слабые
        - LLM упал
        """
        if not results:
            return None
        if len(query.split()) < MIN_QUERY_WORDS:
            return None
        if results[0][1] < MIN_SCORE_FOR_SUMMARY:
            return None

        top = results[:TOP_N_FOR_SUMMARY]
        bookmarks_block = "\n\n".join(
            _format_bookmark_for_prompt(i + 1, b) for i, (b, _) in enumerate(top)
        )

        user_prompt = (
            f"Запрос пользователя: {query}\n\n"
            f"Найденные закладки:\n\n{bookmarks_block}\n\n"
            f"Напиши саммари."
        )

        try:
            text = await self.classifier.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=400,
                temperature=0.4,
            )
        except Exception as e:
            logger.warning(f"Search summary failed: {e}")
            return None

        text = text.strip()
        if not text:
            return None

        # Подчищаем возможные markdown-обёртки
        text = re.sub(r"^```.*?\n", "", text)
        text = re.sub(r"\n```$", "", text)

        return text.strip()
