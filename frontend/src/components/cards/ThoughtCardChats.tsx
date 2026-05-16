import type { Thought, ThoughtKind } from "../../lib/types";
import { Glyph } from "../ui/Glyph";
import { Pulse } from "../ui/Pulse";
import { kindLabel } from "./IconType";
import { formatRelativeDate } from "../../lib/formatters";

interface ThoughtCardChatsProps {
  thought: Thought;
  onMenuTap: () => void;
  isLast?: boolean;
}

/**
 * Chat-row mode — Telegram-style dense row. Anatomy verbatim from
 * docs/design-system/reference_app/ChatRow.jsx:
 * avatar 46 (gradient by tone) · name Onest 14.5/500 · time JetBrains Mono 11 ·
 * preview Lora italic 13.5 with mono <src> prefix · hairline 0.5px between rows.
 */
type Tone = "sage" | "honey" | "slate" | "plum" | "clay" | "moss";

const KIND_TONE: Record<ThoughtKind, Tone> = {
  idea: "sage",
  voice: "honey",
  article: "honey",
  link: "slate",
  task: "sage",
  action: "moss",
  other: "sage",
};

export function ThoughtCardChats({ thought, onMenuTap, isLast = false }: ThoughtCardChatsProps) {
  const t = thought;
  const processing = t.aiStatus !== "completed";
  const isTask = t.kind === "task";
  const tone = KIND_TONE[t.kind];
  const letter = (t.title.trim()[0] || "•").toUpperCase();
  const host = t.url ? safeHost(t.url) : null;
  const counter = t.taskProgress
    ? `${t.taskProgress.done}/${t.taskProgress.total}`
    : null;

  return (
    <div
      className="chat-row"
      onContextMenu={(e) => {
        e.preventDefault();
        onMenuTap();
      }}
    >
      {isTask ? (
        <span className="chat-avatar chat-avatar--task" aria-hidden="true">
          <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="4" />
            <path d="M8 12l3 3 5-6" />
          </svg>
        </span>
      ) : (
        <span className={`chat-avatar chat-avatar--${tone}`} aria-hidden="true">
          {letter}
        </span>
      )}

      <div className={`chat-body ${isLast ? "is-last" : ""}`}>
        <div className="chat-row1">
          <span className="chat-name">{t.title}</span>
          <span className="chat-time">{formatRelativeDate(t.createdAt)}</span>
        </div>

        <div className="chat-row2">
          <span className="chat-preview">
            {host && <span className="chat-src">{host}</span>}
            {t.summary || t.rawText.slice(0, 90)}
          </span>
          <span className="chat-trailing">
            {processing && <Pulse size={7} color="#C49454" />}
            {counter && <span className="chat-badge">{counter}</span>}
            {t.hasReminder && !counter && <Glyph ch="↺" size={15} />}
            {t.isFavorite && <Glyph ch="★" size={15} />}
          </span>
        </div>
      </div>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** preview "тип · текст" — exported for possible reuse */
export function buildChatPreview(t: Thought): string {
  const label = kindLabel(t.kind);
  const body = t.summary || t.rawText.slice(0, 60);
  return label === "заметка" ? body : `${label} · ${body}`;
}
