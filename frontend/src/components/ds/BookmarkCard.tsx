/* BookmarkCard — ported 1:1 from docs/design-system-miniapp/ds/BookmarkCard.jsx */
import { Glyph, Pulse, TagChip } from "./atoms";

export interface BookmarkCardData {
  id: string | number;
  title: string;
  summary?: string | null;
  url?: string | null;
  tags?: { name: string; color: number }[];
  time: string;
  ai_status?: "processing" | "completed";
  is_favorite?: boolean;
  content_type?: "task" | "voice" | "link";
  task_progress?: { done: number; total: number } | null;
}

export function BookmarkCard({ bookmark, onOpen }: { bookmark: BookmarkCardData; onOpen?: () => void }) {
  const { title, summary, url, tags = [], time, ai_status = "completed", is_favorite, content_type, task_progress } = bookmark;
  const isTask = content_type === "task";

  return (
    <div
      onClick={onOpen}
      className="ds-bookmark-card"
      style={{
        background: "rgba(255,252,246,0.72)",
        backdropFilter: "blur(20px) saturate(160%)",
        WebkitBackdropFilter: "blur(20px) saturate(160%)",
        border: "1px solid rgba(255,255,255,0.6)",
        borderRadius: 18,
        padding: "16px 18px",
        cursor: "pointer",
        marginBottom: 10,
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 6px 18px rgba(60,40,25,0.05)",
        transition: "transform 200ms var(--ease-out), box-shadow 200ms var(--ease-out)",
      }}
    >
      <h4 style={{ fontSize: 15.5, fontWeight: 500, color: "var(--fg-1)", lineHeight: 1.25, margin: "0 0 6px", letterSpacing: "-0.02em" }}>
        {title}
      </h4>

      {summary && (
        <p style={{ fontFamily: "var(--font-display)", fontStyle: "italic", fontWeight: 400, fontSize: 14, color: "var(--fg-2)", lineHeight: 1.4, margin: "0 0 10px", letterSpacing: 0 }}>
          {summary}
        </p>
      )}

      {isTask && task_progress && (
        <div style={{ margin: "0 0 12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--fg-3)", marginBottom: 6, letterSpacing: ".04em" }}>
            <span>{task_progress.done}/{task_progress.total} готово</span>
          </div>
          <div style={{ height: 3, background: "rgba(234,227,207,0.7)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ width: `${(task_progress.done / Math.max(task_progress.total, 1)) * 100}%`, height: "100%", background: "var(--brand-primary)" }} />
          </div>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--fg-3)", letterSpacing: ".06em", marginBottom: tags.length ? 10 : 0 }}>
        {url && <span style={{ color: "var(--fg-2)", fontWeight: 500 }}>{url}</span>}
        {url && <span style={{ width: 2.5, height: 2.5, borderRadius: "50%", background: "var(--fg-4)" }} />}
        <span>{time}</span>
        {ai_status !== "completed" && (
          <>
            <span style={{ width: 2.5, height: 2.5, borderRadius: "50%", background: "var(--fg-4)" }} />
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "#7A5828" }}>
              <Pulse size={5} color="#C49454" />
              ai…
            </span>
          </>
        )}
        {is_favorite && (
          <>
            <span style={{ flex: 1 }} />
            <Glyph ch="★" size={14} color="var(--brand-primary)" />
          </>
        )}
      </div>

      {tags.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
          {tags.map((t) => (
            <TagChip key={t.name} name={t.name} color={t.color} size="sm" />
          ))}
        </div>
      )}
    </div>
  );
}
