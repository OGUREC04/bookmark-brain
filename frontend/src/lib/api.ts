// API client for BookmarkBrain backend

import { getInitData } from "./telegram";

let authToken: string | null = null;

async function getToken(): Promise<string> {
  if (authToken) return authToken;

  const initData = getInitData();
  if (!initData) {
    throw new Error("No Telegram initData available");
  }

  const res = await fetch("/api/v1/auth/telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: initData }),
  });

  if (!res.ok) throw new Error("Auth failed");

  const data = await res.json();
  authToken = data.access_token;
  return authToken!;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await getToken();
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });

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

// API methods

export const api = {
  getBookmarks(page = 1, perPage = 20): Promise<BookmarkList> {
    return request(`/api/v1/bookmarks/?page=${page}&per_page=${perPage}`);
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
};
