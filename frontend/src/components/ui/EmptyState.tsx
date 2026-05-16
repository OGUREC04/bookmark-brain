import type { ReactNode } from "react";
import { Glyph } from "./Glyph";

interface EmptyStateProps {
  /** Editorial glyph: ∅ search-empty · ? pre-query · ★ no-favorites · ¶ no-notes */
  glyph?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

/**
 * Empty state — big Lora-italic glyph hero (DS: 72px, opacity 0.55, sage),
 * Onest 17/500 head, Lora-italic 14 copy. Verbatim from Atoms.jsx EmptyState.
 */
export function EmptyState({ glyph = "∅", title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state__glyph">
        <Glyph ch={glyph} size={72} opacity={0.55} />
      </div>
      <p className="empty-state__title">{title}</p>
      {description && <p className="empty-state__desc">{description}</p>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}
