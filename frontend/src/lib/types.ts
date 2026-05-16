// UI-уровень типов для Mini App. Backend остаётся с Bookmark — адаптер в adapters.ts.

import type { Bookmark, TaskListData, Tag } from "./api";

/** Визуальный тип карточки. Деривируется из item_type + content_type через deriveKind. */
export type ThoughtKind =
  | "link"     // url + не article/idea
  | "article"  // url + item_type=content (длинный текст)
  | "voice"    // content_type=voice
  | "task"     // structured_data.type=task_list
  | "idea"     // item_type=thought
  | "action"   // item_type=action
  | "other";

export interface TaskProgress {
  done: number;
  total: number;
}

/** UI Thought. Создаётся адаптером — не хранится в БД. */
export interface Thought {
  // Прямо из Bookmark
  id: string;
  title: string;
  summary: string | null;
  tags: Tag[];
  isFavorite: boolean;
  createdAt: string;
  folderId: string | null;
  aiStatus: string;
  url: string | null;
  rawText: string;
  structuredData: TaskListData | null;

  // Деривативы
  kind: ThoughtKind;
  taskProgress: TaskProgress | null;
  hasReminder: boolean;
  reminderAt: string | null;
}

/** Variant для ThoughtCard. Юзер выбирает через AppHeader view-toggle. */
export type CardVariant = "feed" | "chats";

/** Реэкспорт чтобы import { Bookmark } через одну точку. */
export type { Bookmark, TaskListData, Tag };
