"""Connections API — связи между заметками и граф (Phase 5A).

Эндпоинты:
- GET  /api/v1/bookmarks/{id}/related — связанные заметки (топ-5 + ?all=true)
- (граф — добавляется в задаче 7: /graph/local, /graph/build, /graph)

IDOR: заметка проверяется на принадлежность current_user (404 иначе);
сервисные запросы дополнительно скоупятся по user_id (NFR-4).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_session
from app.models import Bookmark, User
from app.services import connections

router = APIRouter(prefix="/api/v1", tags=["connections"])


class RelatedItem(BaseModel):
    id: UUID
    title: str | None = None
    summary: str | None = None
    item_type: str | None = None
    weight: float
    created_at: datetime | None = None


class RelatedResponse(BaseModel):
    items: list[RelatedItem]
    total: int


@router.get("/bookmarks/{bookmark_id}/related", response_model=RelatedResponse)
async def get_related_bookmarks(
    bookmark_id: UUID,
    show_all: bool = Query(False, alias="all"),
    limit: int = Query(5, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RelatedResponse:
    """Связанные по смыслу заметки. Топ-5 по весу; ?all=true — все связи."""
    # IDOR: заметка должна принадлежать текущему пользователю.
    owner = await session.execute(
        select(Bookmark.id).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == current_user.id,
        )
    )
    if owner.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    items = await connections.get_related(
        session, bookmark_id, current_user.id, limit=limit, include_all=show_all,
    )
    # total — истинное число связей (для кнопки «🔗 Похожие (N)»), не размер топ-5.
    total = (
        len(items)
        if show_all
        else await connections.count_related(session, bookmark_id, current_user.id)
    )
    return RelatedResponse(items=items, total=total)


# ── Граф ──────────────────────────────────────────────────────────────────
# Узлы/рёбра отдаёт сервер; тяжёлую раскладку считает клиент (react-force-graph)
# и присылает координаты на /graph/build (кэш по кнопке «Построить граф»).


class GraphLocalResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    center: str


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    layout: list | None = None  # кэшированные координаты узлов или null
    stale: bool
    node_count: int
    built_at: datetime | None = None


class GraphBuildRequest(BaseModel):
    # Лимит против раздувания graph_layouts/CPU: клиент не шлёт больше узлов,
    # чем сервер отдаёт (GRAPH_NODE_CAP + запас). Свыше → 422 на границе.
    nodes: list[dict] = Field(max_length=connections.GRAPH_NODE_CAP + 50)


class GraphBuildResponse(BaseModel):
    node_count: int
    saved: bool = True


@router.get("/graph/local", response_model=GraphLocalResponse)
async def graph_local(
    center: UUID,
    depth: int = Query(2, ge=1, le=3),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GraphLocalResponse:
    """Локальный (эго) граф вокруг заметки — как local graph в Obsidian."""
    owner = await session.execute(
        select(Bookmark.id).where(
            Bookmark.id == center, Bookmark.user_id == current_user.id
        )
    )
    if owner.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    g = await connections.ego_graph(session, current_user.id, center, depth=depth)
    return GraphLocalResponse(**g)


@router.get("/graph", response_model=GraphResponse)
async def graph_full(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Полный граф пользователя + закэшированная раскладка и флаг устаревания."""
    g = await connections.get_full_graph(session, current_user.id)
    current = await connections.current_graph_node_count(session, current_user.id)
    layout = await connections.get_graph_layout(session, current_user.id)
    stale = layout is None or layout["node_count"] != current
    return GraphResponse(
        nodes=g["nodes"],
        edges=g["edges"],
        layout=(layout["nodes"] if layout else None),
        stale=stale,
        node_count=current,
        built_at=(layout["built_at"] if layout else None),
    )


@router.post("/graph/build", response_model=GraphBuildResponse)
async def graph_build(
    body: GraphBuildRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GraphBuildResponse:
    """Сохранить раскладку, посчитанную клиентом (кнопка «Построить граф»)."""
    current = await connections.current_graph_node_count(session, current_user.id)
    await connections.save_graph_layout(session, current_user.id, body.nodes, current)
    return GraphBuildResponse(node_count=current, saved=True)
