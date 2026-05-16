import { Star, Clock, MoreHorizontal } from "lucide-react";
import type { Thought } from "../../lib/types";
import { IconType, kindLabel } from "./IconType";
import { formatDate, formatReminderDate, formatProgress } from "../../lib/formatters";

interface ThoughtCardFeedProps {
  thought: Thought;
  onMenuTap: () => void;
}

/**
 * Feed variant — full-width карточка с title/summary/tags/badges.
 * Один акцент на карточке: либо ⭐ (yellow), либо ⏰ (sage), не оба.
 */
export function ThoughtCardFeed({ thought, onMenuTap }: ThoughtCardFeedProps) {
  const t = thought;
  return (
    <article className="card-feed">
      <header className="card-feed__top">
        <span className="card-feed__type">
          <IconType kind={t.kind} size={13} />
          <span>{kindLabel(t.kind)}</span>
        </span>
        <div className="card-feed__meta">
          {t.isFavorite && (
            <span className="icon-star" aria-label="избранное">
              <Star size={13} strokeWidth={1.6} fill="currentColor" />
            </span>
          )}
          <span>{formatDate(t.createdAt)}</span>
          <button
            type="button"
            className="card-feed__menu"
            aria-label="Действия"
            onClick={(e) => {
              e.stopPropagation();
              onMenuTap();
            }}
          >
            <MoreHorizontal size={16} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      <h3 className="card-feed__title">{t.title}</h3>
      {t.summary && <p className="card-feed__summary">{t.summary}</p>}

      {t.taskProgress && (
        <div className="card-feed__task">
          <div className="progress-bar">
            <div
              className="progress-bar__fill"
              style={{ width: `${(t.taskProgress.done / Math.max(t.taskProgress.total, 1)) * 100}%` }}
            />
          </div>
          <span className="card-feed__task-count">{formatProgress(t.taskProgress.done, t.taskProgress.total)}</span>
        </div>
      )}

      {(t.tags.length > 0 || t.hasReminder) && (
        <footer className="card-feed__footer">
          {t.tags.length > 0 && (
            <span className="card-feed__tags">
              {t.tags.slice(0, 3).map((tag) => `#${tag.name}`).join(" ")}
              {t.tags.length > 3 && ` +${t.tags.length - 3}`}
            </span>
          )}
          {t.hasReminder && t.reminderAt && (
            <span className="badge-reminder">
              <Clock size={11} strokeWidth={2} />
              {formatReminderDate(t.reminderAt)}
            </span>
          )}
        </footer>
      )}
    </article>
  );
}
