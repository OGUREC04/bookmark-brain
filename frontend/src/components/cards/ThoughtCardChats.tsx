import { Star, Clock, Pin } from "lucide-react";
import type { Thought } from "../../lib/types";
import { IconType, kindLabel } from "./IconType";
import { formatRelativeDate, formatProgress } from "../../lib/formatters";

interface ThoughtCardChatsProps {
  thought: Thought;
  onMenuTap: () => void;
}

/**
 * Chats variant — плотный list-item «как в Telegram».
 * Avatar 48×48 (цветной по типу) + title + preview одной строкой + time + badge.
 */
export function ThoughtCardChats({ thought }: ThoughtCardChatsProps) {
  const t = thought;
  // Counter badge:
  //   tasklist → "3/5"
  //   reminder в ближайшее → не используем здесь (он в preview)
  //   иначе → нет
  const counter = t.taskProgress
    ? formatProgress(t.taskProgress.done, t.taskProgress.total)
    : null;

  return (
    <div className="card-chat" role="listitem">
      <IconType kind={t.kind} avatar />

      <div className="card-chat__body">
        <div className="card-chat__row1">
          <div className="card-chat__title">
            {t.isFavorite && (
              <span className="icon-star" aria-label="избранное">
                <Star size={12} strokeWidth={1.6} fill="currentColor" />
              </span>
            )}
            <span className="card-chat__title-text">{t.title}</span>
          </div>
          <span className="card-chat__time">{formatRelativeDate(t.createdAt)}</span>
        </div>

        <div className="card-chat__row2">
          <span className="card-chat__preview">
            {t.summary || t.rawText.slice(0, 80)}
          </span>
          <div className="card-chat__badges">
            {t.hasReminder && (
              <span className="badge-pin" aria-label="напоминание">
                <Clock size={13} strokeWidth={1.8} />
              </span>
            )}
            {counter && <span className="badge-counter">{counter}</span>}
          </div>
        </div>

        {!counter && !t.hasReminder && t.tags.length === 0 && null}
      </div>
    </div>
  );
}

/** Compatibility: chat-style preview "tipe · text" — оставлен для возможного use в future */
export function buildChatPreview(t: Thought): string {
  const label = kindLabel(t.kind);
  const body = t.summary || t.rawText.slice(0, 60);
  return label === "заметка" ? body : `${label} · ${body}`;
}
