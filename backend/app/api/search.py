from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_session
from app.models import Tag, User
from app.schemas import (
    BookmarkResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    TagResponse,
)
from app.services.ai_classifier import create_classifier
from app.services.embeddings import create_embedding_service
from app.services.search import SearchService
from app.services.search_summary import SearchSummarizer

router = APIRouter(prefix="/api/v1/search", tags=["search"])
settings = get_settings()


def _build_classifier():
    """Собирает classifier по текущему AI_PROVIDER из settings."""
    api_key = {
        "gigachat": settings.GIGACHAT_AUTH_KEY,
        "deepseek": settings.DEEPSEEK_API_KEY,
        "claude": settings.ANTHROPIC_API_KEY,
    }.get(settings.AI_PROVIDER, "")
    return create_classifier(
        provider=settings.AI_PROVIDER,
        auth_key=api_key,
        api_key=api_key,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )


@router.post("/", response_model=SearchResponse)
async def search_bookmarks(
    data: SearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )

    try:
        search_service = SearchService(session, embedding_service)
        results, total = await search_service.search(
            user_id=current_user.id,
            query=data.query,
            limit=data.limit,
            offset=data.offset,
            category=data.category,
            tags=data.tags,
            mode=data.mode,
        )
    finally:
        await embedding_service.close()

    # AI-саммари по топу результатов (как one-box у Google).
    # Делаем после основного поиска, чтобы не задерживать его на случай
    # если LLM тормозит. Если упало — просто вернём результаты без summary.
    summary: str | None = None
    if data.with_summary and results:
        classifier = _build_classifier()
        try:
            summarizer = SearchSummarizer(classifier)
            summary = await summarizer.summarize(data.query, results)
        finally:
            # Закрываем httpx-клиенты у GigaChat/DeepSeek (у Claude SDK свой)
            client = getattr(classifier, "_client", None)
            if client is not None:
                await client.aclose()

    return SearchResponse(
        results=[
            SearchResult(bookmark=BookmarkResponse.model_validate(bookmark), score=score)
            for bookmark, score in results
        ],
        total=total,
        query=data.query,
        summary=summary,
    )


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Tag)
        .where(Tag.user_id == current_user.id)
        .order_by(Tag.bookmarks_count.desc())
    )
    return result.scalars().all()
