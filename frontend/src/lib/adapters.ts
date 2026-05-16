// Маппинг Bookmark (backend) → Thought (UI). См. MINIAPP-ARCHITECTURE.md §9.

import type { Bookmark } from "./api";
import type { Thought, ThoughtKind, TaskProgress } from "./types";

/**
 * Деривация визуального типа карточки.
 * Порядок проверок ВАЖЕН — task_list приоритетнее url, voice раньше item_type, etc.
 */
export function deriveKind(b: Bookmark): ThoughtKind {
  if (b.structured_data?.type === "task_list") return "task";
  if (b.content_type === "voice") return "voice";
  if (b.item_type === "action") return "action";
  if (b.item_type === "thought") return "idea";
  if (b.item_type === "content" && b.url) return "article";
  if (b.url) return "link";
  return "other";
}

/** Прогресс тасклиста или null если bookmark — не tasklist. */
export function deriveTaskProgress(b: Bookmark): TaskProgress | null {
  const sd = b.structured_data;
  if (!sd || sd.type !== "task_list") return null;
  const tasks = sd.tasks ?? [];
  const done = tasks.filter((t) => t.done).length;
  return { done, total: tasks.length };
}

/** Адаптер Bookmark → Thought. Иммутабельный, не мутирует Bookmark. */
export function bookmarkToThought(
  b: Bookmark,
  remindersMap: Map<string, { fireAt: string }> = new Map(),
): Thought {
  const reminder = remindersMap.get(b.id);
  return {
    id: b.id,
    title: b.title || b.raw_text.slice(0, 80),
    summary: b.summary,
    tags: b.tags,
    isFavorite: b.is_favorite,
    createdAt: b.created_at,
    folderId: b.folder_id,
    aiStatus: b.ai_status,
    url: b.url,
    rawText: b.raw_text,
    structuredData: b.structured_data ?? null,

    kind: deriveKind(b),
    taskProgress: deriveTaskProgress(b),
    hasReminder: !!reminder,
    reminderAt: reminder?.fireAt ?? null,
  };
}

/**
 * Строит O(1)-lookup Map<bookmarkId, {fireAt}> из ответа /reminders/upcoming.
 * Используется в Thoughts.tsx чтобы избежать N запросов на проверку
 * «есть ли reminder» для каждой карточки.
 */
export function buildRemindersMap(
  reminders: Array<{ bookmark_id: string | null; fire_at: string }>,
): Map<string, { fireAt: string }> {
  const map = new Map<string, { fireAt: string }>();
  for (const r of reminders) {
    if (r.bookmark_id) map.set(r.bookmark_id, { fireAt: r.fire_at });
  }
  return map;
}
