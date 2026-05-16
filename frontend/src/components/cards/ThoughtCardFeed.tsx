import type { Thought } from "../../lib/types";
import { Glyph } from "../ui/Glyph";
import { Pulse } from "../ui/Pulse";
import { tagStop } from "../../lib/tagPalette";
import { formatDate } from "../../lib/formatters";

interface ThoughtCardFeedProps {
  thought: Thought;
  onMenuTap: () => void;
}

/**
 * Card mode — liquid-glass tile. Anatomy verbatim from
 * docs/design-system/reference_app/BookmarkCard.jsx.
 * Title Onest 15.5/500, summary Lora italic 14, meta JetBrains Mono 10.5.
 */
export function ThoughtCardFeed({ thought, onMenuTap }: ThoughtCardFeedProps) {
  const t = thought;
  const processing = t.aiStatus !== "completed";
  const host = t.url ? safeHost(t.url) : null;

  return (
    <article
      className="card-feed"
      onContextMenu={(e) => {
        e.preventDefault();
        onMenuTap();
      }}
    >
      <h4 className="card-feed__title">{t.title}</h4>

      {t.summary && <p className="card-feed__summary">{t.summary}</p>}

      {t.taskProgress && (
        <div className="card-feed__task">
          <div className="card-feed__task-meta">
            <span>
              {t.taskProgress.done}/{t.taskProgress.total} готово
            </span>
          </div>
          <div className="card-feed__task-bar">
            <div
              className="card-feed__task-fill"
              style={{
                width: `${(t.taskProgress.done / Math.max(t.taskProgress.total, 1)) * 100}%`,
              }}
            />
          </div>
        </div>
      )}

      <div className="card-feed__meta">
        {host && <span className="card-feed__src">{host}</span>}
        {host && <span className="card-feed__metadot" />}
        <span>{formatDate(t.createdAt)}</span>
        {processing && (
          <>
            <span className="card-feed__metadot" />
            <span className="card-feed__ai">
              <Pulse size={5} color="#C49454" />
              ai…
            </span>
          </>
        )}
        {t.isFavorite && (
          <>
            <span className="card-feed__spacer" />
            <Glyph ch="★" size={14} />
          </>
        )}
      </div>

      {t.tags.length > 0 && (
        <div className="card-feed__tags">
          {t.tags.slice(0, 4).map((tag) => (
            <span key={tag.id} className="tag-chip" data-stop={tagStop(tag.name)}>
              #{tag.name}
            </span>
          ))}
          {t.tags.length > 4 && (
            <span className="tag-chip" data-stop={8}>
              +{t.tags.length - 4}
            </span>
          )}
        </div>
      )}
    </article>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
