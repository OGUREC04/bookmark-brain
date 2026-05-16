// API client for BookmarkBrain backend
// Updated 2026-05-15 (T1): retry-on-401, in-flight auth dedup, AuthExpiredError signal for UI.

import { getInitData } from "./telegram";

let authToken: string | null = null;
let authInFlight: Promise<string> | null = null;

/**
 * Thrown when re-auth via initData fails (TG initData TTL ~24h expires
 * during long-lived WebViews). UI should show a full-screen CTA to
 * restart Mini App from the bot.
 */
export class AuthExpiredError extends Error {
  constructor(message = "Сессия истекла. Перезапусти Mini App из бота.") {
    super(message);
    this.name = "AuthExpiredError";
  }
}

async function fetchNewToken(): Promise<string> {
  const initData = getInitData();
  if (!initData) {
    throw new AuthExpiredError("No Telegram initData available");
  }
  const res = await fetch("/api/v1/auth/telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: initData }),
  });
  if (!res.ok) {
    throw new AuthExpiredError("Auth failed");
  }
  const data = await res.json();
  authToken = data.access_token;
  return authToken!;
}

/**
 * Returns a cached JWT or fetches a fresh one.
 * Deduplicates concurrent auth requests so parallel callers share one POST.
 */
async function getToken(): Promise<string> {
  if (authToken) return authToken;
  if (authInFlight) return authInFlight;
  authInFlight = fetchNewToken().finally(() => {
    authInFlight = null;
  });
  return authInFlight;
}

async function doFetch(path: string, options: RequestInit, token: string): Promise<Response> {
  return fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let token = await getToken();
  let res = await doFetch(path, options, token);

  // Retry once on 401: clear cached token, request a fresh one, replay.
  if (res.status === 401) {
    authToken = null;
    try {
      token = await getToken();
    } catch (err) {
      // initData rejected — propagate so UI can show "restart from bot" CTA.
      throw err;
    }
    res = await doFetch(path, options, token);
    if (res.status === 401) {
      // Still 401 after fresh auth — initData is dead.
      throw new AuthExpiredError();
    }
  }

  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// Types
export interface Tag {
  id: string;
  name: string;
  color: string | null;
  bookmarks_count: number;
}

export interface Bookmark {
  id: string;
  user_id: string;
  source: string;
  url: string | null;
  raw_text: string;
  title: string | null;
  content_type: string;
  summary: string | null;
  category: string | null;
  tags: Tag[];
  folder_id: string | null;
  ai_status: string;
  is_favorite: boolean;
  is_archived: boolean;
  created_at: string;
  updated_at: string;

  // Phase 1 — deep processing
  item_type?: string | null;
  takeaway?: string | null;
  key_ideas?: string[] | null;
  entities?: string[] | null;
  open_questions?: string[] | null;

  // Phase 2 — structured content
  structured_data?: TaskListData | null;
}

export interface TaskItem {
  text: string;
  done: boolean;
  deadline: string | null;
}

export interface TaskListData {
  type: "task_list";
  tasks: TaskItem[];
}

export interface Folder {
  id: string;
  name: string;
  emoji: string | null;
  bookmarks_count: number;
  created_at: string;
}

export interface BookmarkList {
  items: Bookmark[];
  total: number;
  page: number;
  per_page: number;
}

export interface SearchResult {
  bookmark: Bookmark;
  score: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
  // AI-саммари по топу результатов с маркерами [1]..[N]
  summary: string | null;
}

export interface UserInfo {
  id: string;
  telegram_id: number;
  telegram_username: string | null;
  telegram_first_name: string | null;
  bookmarks_count: number;
  created_at: string;
}

// Reminders (T5 / Phase 2.5 endpoints, B1 added bookmark_title/raw_text)

export interface Reminder {
  id: string;
  bookmark_id: string | null;
  kind: string;
  fire_at: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  sent_at: string | null;
  bookmark_title: string | null;
  bookmark_raw_text: string | null;
}

export interface RemindersList {
  items: Reminder[];
  total: number;
}

export interface BookmarkListParams {
  page?: number;
  perPage?: number;
  isFavorite?: boolean;
  isArchived?: boolean;
  itemType?: string; // B2
  category?: string;
}

// API methods

export const api = {
  getBookmarks(params: BookmarkListParams = {}): Promise<BookmarkList> {
    const { page = 1, perPage = 20, isFavorite, isArchived, itemType, category } = params;
    const qs = new URLSearchParams({
      page: String(page),
      per_page: String(perPage),
    });
    if (isFavorite !== undefined) qs.set("is_favorite", String(isFavorite));
    if (isArchived !== undefined) qs.set("is_archived", String(isArchived));
    if (itemType) qs.set("item_type", itemType);
    if (category) qs.set("category", category);
    return request(`/api/v1/bookmarks/?${qs.toString()}`);
  },

  createThought(text: string): Promise<Bookmark> {
    // POST /bookmarks/ — source='miniapp', enqueue worker для classify/embed/tags
    return request("/api/v1/bookmarks/", {
      method: "POST",
      body: JSON.stringify({ source: "miniapp", raw_text: text }),
    });
  },

  getBookmark(id: string): Promise<Bookmark> {
    return request(`/api/v1/bookmarks/${id}`);
  },

  deleteBookmark(id: string): Promise<void> {
    return request(`/api/v1/bookmarks/${id}`, { method: "DELETE" });
  },

  toggleFavorite(id: string, isFavorite: boolean): Promise<Bookmark> {
    return request(`/api/v1/bookmarks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_favorite: isFavorite }),
    });
  },

  search(query: string, limit = 20): Promise<SearchResponse> {
    return request("/api/v1/search/", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    });
  },

  getMe(): Promise<UserInfo> {
    return request("/api/v1/users/me");
  },

  getTags(): Promise<Tag[]> {
    return request("/api/v1/search/tags");
  },

  // Folders
  getFolders(): Promise<Folder[]> {
    return request("/api/v1/folders/");
  },

  createFolder(name: string, emoji?: string): Promise<Folder> {
    return request("/api/v1/folders/", {
      method: "POST",
      body: JSON.stringify({ name, emoji }),
    });
  },

  deleteFolder(id: string): Promise<void> {
    return request(`/api/v1/folders/${id}`, { method: "DELETE" });
  },

  getFolderBookmarks(folderId: string, page = 1, perPage = 20): Promise<BookmarkList> {
    return request(`/api/v1/folders/${folderId}/bookmarks?page=${page}&per_page=${perPage}`);
  },

  addBookmarkToFolder(folderId: string, bookmarkId: string): Promise<void> {
    return request(`/api/v1/folders/${folderId}/bookmarks/${bookmarkId}`, { method: "POST" });
  },

  removeBookmarkFromFolder(folderId: string, bookmarkId: string): Promise<void> {
    return request(`/api/v1/folders/${folderId}/bookmarks/${bookmarkId}`, { method: "DELETE" });
  },

  updateBookmark(
    id: string,
    data: Partial<{
      folder_id: string | null;
      is_favorite: boolean;
      is_archived: boolean;
      title: string;
      structured_data: TaskListData | null;
    }>
  ): Promise<Bookmark> {
    return request(`/api/v1/bookmarks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  // Reminders (Phase 2.5 + B1 bookmark fields)
  reminders: {
    upcoming(limit = 50): Promise<RemindersList> {
      return request(`/api/v1/reminders/upcoming?limit=${limit}`);
    },
    history(limit = 20, days = 30): Promise<RemindersList> {
      return request(`/api/v1/reminders/history?limit=${limit}&days=${days}`);
    },
    create(bookmarkId: string, fireAt: string): Promise<Reminder> {
      return request("/api/v1/reminders/", {
        method: "POST",
        body: JSON.stringify({ bookmark_id: bookmarkId, fire_at: fireAt }),
      });
    },
    snooze(id: string, fireAt: string): Promise<Reminder> {
      return request(`/api/v1/reminders/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ fire_at: fireAt }),
      });
    },
    cancel(id: string): Promise<void> {
      return request(`/api/v1/reminders/${id}`, { method: "DELETE" });
    },
  },
};
