import { useCallback, useState } from "react";

export type ViewMode = "feed" | "chats";

const KEY = "bb_view_mode";
const DEFAULT: ViewMode = "feed";

function read(): ViewMode {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "feed" || v === "chats") return v;
  } catch {
    /* SSR or storage disabled */
  }
  return DEFAULT;
}

/**
 * useViewMode — persist выбора вид/список в localStorage.
 * Default 'feed' — крупные карточки понятнее новому юзеру.
 */
export function useViewMode() {
  const [viewMode, setViewModeState] = useState<ViewMode>(() => read());

  const setViewMode = useCallback((mode: ViewMode) => {
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* ignore */
    }
    setViewModeState(mode);
  }, []);

  const toggleViewMode = useCallback(() => {
    setViewMode(viewMode === "feed" ? "chats" : "feed");
  }, [viewMode, setViewMode]);

  return { viewMode, setViewMode, toggleViewMode };
}
