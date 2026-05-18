import logging

import httpx

logger = logging.getLogger(__name__)


class BackendClient:
    """Клиент для обращения к FastAPI backend от имени бота."""

    def __init__(self, base_url: str, bot_secret: str):
        transport = httpx.AsyncHTTPTransport(retries=2)
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Bot-Secret": bot_secret},
            timeout=10.0,
            transport=transport,
        )

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> dict:
        """Создать/обновить юзера, вернуть JWT token."""
        response = await self.client.post(
            "/api/v1/auth/bot",
            json={
                "telegram_id": telegram_id,
                "telegram_username": username,
                "telegram_first_name": first_name,
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_me(self, token: str) -> dict:
        """GET /api/v1/users/me — получить данные текущего юзера."""
        response = await self.client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()

    async def update_settings(self, token: str, settings: dict) -> dict:
        """PATCH /api/v1/users/me/settings — обновить настройки юзера."""
        response = await self.client.patch(
            "/api/v1/users/me/settings",
            headers={"Authorization": f"Bearer {token}"},
            json=settings,
        )
        response.raise_for_status()
        return response.json()

    async def update_timezone(self, token: str, tz: str) -> dict:
        """PATCH /api/v1/users/me/timezone — сменить часовой пояс.

        Raises httpx.HTTPStatusError 400 если timezone невалидный.
        """
        response = await self.client.patch(
            "/api/v1/users/me/timezone",
            headers={"Authorization": f"Bearer {token}"},
            json={"timezone": tz},
        )
        response.raise_for_status()
        return response.json()

    async def create_reminder(
        self,
        token: str,
        fire_at: str,  # ISO 8601 UTC
        bookmark_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        """POST /api/v1/reminders/ — создать напоминание."""
        response = await self.client.post(
            "/api/v1/reminders/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "fire_at": fire_at,
                "bookmark_id": bookmark_id,
                "payload": payload or {},
            },
        )
        response.raise_for_status()
        return response.json()

    async def update_reminder(
        self, token: str, reminder_id: str, fire_at: str
    ) -> dict:
        """PATCH /api/v1/reminders/{id} — продлить (snooze)."""
        response = await self.client.patch(
            f"/api/v1/reminders/{reminder_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"fire_at": fire_at},
        )
        response.raise_for_status()
        return response.json()

    async def cancel_reminder(self, token: str, reminder_id: str) -> None:
        """DELETE /api/v1/reminders/{id} — отменить."""
        response = await self.client.delete(
            f"/api/v1/reminders/{reminder_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

    async def apply_reminder_decision(
        self,
        token: str,
        bookmark_id: str,
        form: str,
        composite_fire_at: str | None = None,
    ) -> dict:
        """POST /api/v1/reminders/apply-decision/{bookmark_id} — Phase 2.6.

        form: task_list_with_reminders | composite_reminder | single_reminder
        composite_fire_at: ISO 8601 UTC, обязателен для composite_reminder
        если в decision не было dated items.
        """
        params: dict = {"form": form}
        if composite_fire_at is not None:
            params["composite_fire_at"] = composite_fire_at
        response = await self.client.post(
            f"/api/v1/reminders/apply-decision/{bookmark_id}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def list_upcoming_reminders(self, token: str, limit: int = 50) -> dict:
        """GET /api/v1/reminders/upcoming."""
        response = await self.client.get(
            "/api/v1/reminders/upcoming",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def list_reminder_history(
        self, token: str, limit: int = 20, days: int = 30,
    ) -> dict:
        """GET /api/v1/reminders/history (T12 v2.1)."""
        response = await self.client.get(
            "/api/v1/reminders/history",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit, "days": days},
        )
        response.raise_for_status()
        return response.json()

    async def create_bookmark(
        self,
        token: str,
        raw_text: str,
        url: str | None = None,
        title: str | None = None,
        source: str = "bot_forward",
        source_message_id: int | None = None,
        notify_chat_id: int | None = None,
        notify_message_id: int | None = None,
        silent: bool = False,
        # Phase 3 — media fields
        content_type: str = "other",
        media_file_id: str | None = None,
        transcription: str | None = None,
        media_duration: float | None = None,
        voice_tag: bool = False,
        document_page_count: int | None = None,
    ) -> dict:
        payload = {
            "raw_text": raw_text,
            "url": url,
            "title": title,
            "source": source,
            "source_message_id": source_message_id,
            "content_type": content_type,
        }
        if media_file_id:
            payload["media_file_id"] = media_file_id
        if transcription:
            payload["transcription"] = transcription
        if media_duration is not None:
            payload["media_duration"] = media_duration
        if document_page_count is not None:
            payload["document_page_count"] = document_page_count
        if notify_chat_id and notify_message_id:
            payload["notify_chat_id"] = notify_chat_id
            payload["notify_message_id"] = notify_message_id
        if silent:
            payload["silent"] = True
        if voice_tag:
            payload["voice_tag"] = True

        response = await self.client.post(
            "/api/v1/bookmarks/",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def search_bookmarks(
        self, token: str, query: str, limit: int = 5
    ) -> dict:
        response = await self.client.post(
            "/api/v1/search/",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def get_bookmarks(
        self, token: str, page: int = 1, per_page: int = 20,
        structured_type: str | None = None,
    ) -> dict:
        params: dict = {"page": page, "per_page": per_page}
        if structured_type is not None:
            params["structured_type"] = structured_type
        response = await self.client.get(
            "/api/v1/bookmarks/",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def get_bookmark(self, token: str, bookmark_id: str) -> dict:
        """Получает одну закладку по ID."""
        response = await self.client.get(
            f"/api/v1/bookmarks/{bookmark_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()

    async def update_bookmark(
        self, token: str, bookmark_id: str, patch: dict
    ) -> dict:
        """PATCH /api/bookmarks/{id} — частичное обновление."""
        response = await self.client.patch(
            f"/api/v1/bookmarks/{bookmark_id}",
            headers={"Authorization": f"Bearer {token}"},
            json=patch,
        )
        response.raise_for_status()
        return response.json()

    async def delete_bookmark(self, token: str, bookmark_id: str) -> None:
        """Удаляет закладку по ID."""
        response = await self.client.delete(
            f"/api/v1/bookmarks/{bookmark_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

    async def get_random_bookmark(self, token: str) -> dict | None:
        """Получает случайную закладку через dedicated endpoint."""
        response = await self.client.get(
            "/api/v1/bookmarks/random",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def nl_edit_bookmark(
        self, token: str, bookmark_id: str, text: str
    ) -> dict:
        """POST /api/bookmarks/{id}/nl-edit — NL-редактирование task_list."""
        response = await self.client.post(
            f"/api/v1/bookmarks/{bookmark_id}/nl-edit",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": text},
            timeout=40.0,
        )
        response.raise_for_status()
        return response.json()

    async def merge_task_list(
        self, token: str, new_id: str, old_id: str
    ) -> dict:
        """POST /api/v1/bookmarks/{new_id}/merge-into/{old_id} — объединить списки."""
        response = await self.client.post(
            f"/api/v1/bookmarks/{new_id}/merge-into/{old_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=40.0,
        )
        response.raise_for_status()
        return response.json()

    async def reprocess_all(
        self, token: str, only_missing_phase1: bool = True
    ) -> dict:
        """Батч-переобработка закладок юзера."""
        response = await self.client.post(
            "/api/v1/bookmarks/reprocess-all",
            headers={"Authorization": f"Bearer {token}"},
            params={"only_missing_phase1": str(only_missing_phase1).lower()},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()

    async def get_tags(self, token: str) -> list[dict]:
        response = await self.client.get(
            "/api/v1/search/tags",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
