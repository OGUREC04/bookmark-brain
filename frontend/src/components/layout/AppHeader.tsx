import { useNavigate, useLocation } from "react-router-dom";
import { Clock, LayoutGrid, List } from "lucide-react";

interface AppHeaderProps {
  title: string;
  /** Active view: feed (grid icon active) or chats (list icon active). Pass undefined to hide toggle. */
  viewMode?: "feed" | "chats";
  onViewModeChange?: (mode: "feed" | "chats") => void;
  /** Count of active reminders. Pass 0 or undefined to hide pill. */
  remindersCount?: number;
}

/**
 * App header for Mini App.
 * Layout: [Title]  ····  [view-toggle?] [reminders-pill?]
 * - Title: 28px / 700 / -0.03em
 * - view-toggle: grid / list icons (feed ↔ chats)
 * - reminders-pill: [Clock-icon · N] in sage tint, opens RemindersSheet on tap (handled by parent route)
 */
export function AppHeader({ title, viewMode, onViewModeChange, remindersCount = 0 }: AppHeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleNotif = () => {
    // RemindersSheet is rendered by /reminders route overlay (T9).
    // For now we just navigate; replaced with sheet host in T9.
    navigate("/reminders", { state: { from: location.pathname } });
  };

  return (
    <header className="app-header">
      <h1 className="app-header__title">{title}</h1>

      <div className="app-header__actions">
        {viewMode && onViewModeChange && (
          <div className="view-toggle" role="group" aria-label="Вид списка">
            <button
              type="button"
              className={`view-toggle__opt ${viewMode === "feed" ? "is-active" : ""}`}
              aria-pressed={viewMode === "feed"}
              aria-label="Лента"
              onClick={() => onViewModeChange("feed")}
            >
              <LayoutGrid size={16} strokeWidth={1.8} />
            </button>
            <button
              type="button"
              className={`view-toggle__opt ${viewMode === "chats" ? "is-active" : ""}`}
              aria-pressed={viewMode === "chats"}
              aria-label="Список"
              onClick={() => onViewModeChange("chats")}
            >
              <List size={16} strokeWidth={1.8} />
            </button>
          </div>
        )}

        {remindersCount > 0 && (
          <button
            type="button"
            className="notif-pill"
            aria-label={`Напоминания, активных: ${remindersCount}`}
            onClick={handleNotif}
          >
            <Clock size={14} strokeWidth={2} />
            <span className="notif-pill__count">{remindersCount}</span>
          </button>
        )}
      </div>
    </header>
  );
}
