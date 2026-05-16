// Маппинг Bookmark (backend) → Thought (UI). См. MINIAPP-ARCHITECTURE.md §9.

import type { Bookmark } from "./api";
import type { Thought, ThoughtKind, TaskProgress } from "./types";
import { formatRelativeDate } from "./formatters";
import { tagStop } from "./tagPalette";

/** host из url без www/протокола: "https://www.x.com/a" → "x.com". */
export function hostOf(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
  }
}

const TONES = ["sage", "honey", "slate", "plum", "clay", "moss"] as const;
type Tone = (typeof TONES)[number];

/** Детерминированный tone из строки (стабильный цвет аватара). */
function toneOf(seed: string): Tone {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h + seed.charCodeAt(i)) % TONES.length;
  return TONES[h];
}

export interface ChatRowData {
  id: string;
  avatar: {
    kind: "letter" | "task" | "archive" | "icon";
    tone?: Tone;
    letter?: string;
  };
  name: string;
  time: string;
  preview: string;
  src?: string;
  star?: boolean;
  pulsing?: boolean;
  done?: boolean;
  muted?: boolean;
}

/** Bookmark → props для ChatRow (chat-режим ленты). */
export function bookmarkToChatRow(b: Bookmark): ChatRowData {
  const kind = deriveKind(b);
  const title = b.title || b.raw_text.slice(0, 80);
  const tp = deriveTaskProgress(b);

  let avatar: ChatRowData["avatar"];
  let src: string | undefined;
  if (b.is_archived) {
    avatar = { kind: "archive" };
  } else if (kind === "task") {
    avatar = { kind: "task" };
    src = "task";
  } else if (kind === "voice") {
    avatar = { kind: "icon", tone: toneOf(title) };
    src = "voice";
  } else {
    avatar = { kind: "letter", tone: toneOf(title), letter: (title.trim()[0] || "·").toUpperCase() };
    src = b.url ? hostOf(b.url) : undefined;
  }

  return {
    id: b.id,
    avatar,
    name: title,
    time: formatRelativeDate(b.created_at),
    preview: tp
      ? `${tp.done}/${tp.total} · ${b.summary || b.raw_text.slice(0, 60)}`
      : b.summary || b.raw_text.slice(0, 80),
    src,
    star: b.is_favorite,
    pulsing: b.ai_status !== "completed",
    done: tp ? tp.done === tp.total && tp.total > 0 : false,
    muted: b.is_archived,
  };
}

export interface CardData {
  id: string;
  title: string;
  summary: string | null;
  url: string | null;
  tags: { name: string; color: number }[];
  time: string;
  ai_status: "processing" | "completed";
  is_favorite: boolean;
  content_type?: "task" | "voice" | "link";
  task_progress: { done: number; total: number } | null;
}

/** Bookmark → BookmarkCardData (cards-режим ленты). */
export function bookmarkToCard(b: Bookmark): CardData {
  const kind = deriveKind(b);
  return {
    id: b.id,
    title: b.title || b.raw_text.slice(0, 80),
    summary: b.summary,
    url: b.url ? hostOf(b.url) : null,
    tags: b.tags.map((t) => ({ name: t.name, color: tagStop(t.name) })),
    time: formatRelativeDate(b.created_at),
    ai_status: b.ai_status === "completed" ? "completed" : "processing",
    is_favorite: b.is_favorite,
    content_type: kind === "task" ? "task" : kind === "voice" ? "voice" : "link",
    task_progress: deriveTaskProgress(b),
  };
}

/** Соответствует ли bookmark фильтр-чипу (все/fav/task/voice). */
export function matchesFilter(b: Bookmark, filter: string): boolean {
  if (filter === "all") return true;
  if (filter === "fav") return b.is_favorite;
  if (filter === "task") return deriveKind(b) === "task";
  if (filter === "voice") return deriveKind(b) === "voice";
  return true;
}

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
