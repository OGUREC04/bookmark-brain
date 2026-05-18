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

/** Реэкспорт чтобы import { Bookmark } через одну точку. */
export type { Bookmark, TaskListData, Tag };
