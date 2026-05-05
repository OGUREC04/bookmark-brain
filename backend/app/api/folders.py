from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_session
from app.models import Bookmark, Folder, User
from app.schemas import (
    BookmarkListResponse,
    BookmarkResponse,
    FolderCreate,
    FolderResponse,
    FolderUpdate,
)

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


@router.get("/", response_model=list[FolderResponse])
async def list_folders(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Folder)
        .where(Folder.user_id == current_user.id)
        .order_by(Folder.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    data: FolderCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Проверяем уникальность
    existing = await session.execute(
        select(Folder).where(
            Folder.user_id == current_user.id,
            Folder.name == data.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Folder with this name already exists")

    folder = Folder(
        user_id=current_user.id,
        name=data.name,
        emoji=data.emoji,
    )
    session.add(folder)
    await session.flush()
    return folder


@router.get("/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_user_folder(folder_id, current_user, session)
    return folder


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: UUID,
    data: FolderUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_user_folder(folder_id, current_user, session)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(folder, field, value)
    return folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_user_folder(folder_id, current_user, session)
    # Открепляем закладки из папки (не удаляем их)
    await session.execute(
        update(Bookmark)
        .where(Bookmark.folder_id == folder_id)
        .values(folder_id=None)
    )
    await session.delete(folder)


@router.get("/{folder_id}/bookmarks", response_model=BookmarkListResponse)
async def folder_bookmarks(
    folder_id: UUID,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_user_folder(folder_id, current_user, session)

    stmt = (
        select(Bookmark)
        .options(selectinload(Bookmark.tags))
        .where(Bookmark.user_id == current_user.id, Bookmark.folder_id == folder_id)
        .order_by(Bookmark.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(stmt)
    bookmarks = result.scalars().all()

    count_result = await session.execute(
        select(func.count(Bookmark.id)).where(
            Bookmark.user_id == current_user.id, Bookmark.folder_id == folder_id
        )
    )
    total = count_result.scalar() or 0

    return BookmarkListResponse(items=bookmarks, total=total, page=page, per_page=per_page)


@router.post("/{folder_id}/bookmarks/{bookmark_id}", status_code=status.HTTP_200_OK)
async def add_bookmark_to_folder(
    folder_id: UUID,
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_user_folder(folder_id, current_user, session)

    result = await session.execute(
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    # Если закладка была в другой папке — уменьшить счётчик
    if bookmark.folder_id and bookmark.folder_id != folder_id:
        await session.execute(
            update(Folder)
            .where(Folder.id == bookmark.folder_id)
            .values(bookmarks_count=Folder.bookmarks_count - 1)
        )

    old_folder_id = bookmark.folder_id
    bookmark.folder_id = folder_id

    if old_folder_id != folder_id:
        folder.bookmarks_count = (folder.bookmarks_count or 0) + 1

    return {"status": "ok"}


@router.delete("/{folder_id}/bookmarks/{bookmark_id}", status_code=status.HTTP_200_OK)
async def remove_bookmark_from_folder(
    folder_id: UUID,
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_user_folder(folder_id, current_user, session)

    result = await session.execute(
        select(Bookmark).where(
            Bookmark.id == bookmark_id,
            Bookmark.user_id == current_user.id,
            Bookmark.folder_id == folder_id,
        )
    )
    bookmark = result.scalar_one_or_none()
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not in this folder")

    bookmark.folder_id = None
    folder.bookmarks_count = max(0, (folder.bookmarks_count or 1) - 1)
    return {"status": "ok"}


async def _get_user_folder(
    folder_id: UUID, current_user: User, session: AsyncSession
) -> Folder:
    result = await session.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return folder
