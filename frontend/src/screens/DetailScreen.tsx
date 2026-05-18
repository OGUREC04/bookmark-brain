/* Заметка — detail view. No DS-handoff artboard for this; built from DS
   tokens/atoms to stay visually consistent. Opens on tap of a note. */
import { cloneElement } from "react";
import { Icons, ExtraIcons } from "../components/ds/icons";
import { Glyph, TagChip } from "../components/ds/atoms";
import { type Bookmark } from "../lib/api";
import { hostOf } from "../lib/adapters";
import { formatRelativeDate } from "../lib/formatters";
import { tagStop } from "../lib/tagPalette";

function openLink(url: string) {
  const tg = window.Telegram?.WebApp as { openLink?: (u: string) => void } | undefined;
  if (tg?.openLink) tg.openLink(url);
  else window.open(url, "_blank", "noopener");
}

export function DetailScreen({
  bookmark,
  onBack,
  onMore,
}: {
  bookmark: Bookmark;
  onBack: () => void;
  onMore: () => void;
}) {
  const title = bookmark.title || (bookmark.raw_text ?? "").slice(0, 80) || "без названия";
  const host = bookmark.url ? hostOf(bookmark.url) : null;
  const tasks = bookmark.structured_data?.type === "task_list" ? bookmark.structured_data.tasks : null;

  return (
    <div style={{ padding: "6px 0 calc(116px + env(safe-area-inset-bottom, 0px))" }}>
      <div style={{ padding: "0 16px", display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <button
          onClick={onBack}
          aria-label="назад"
          style={{
            background: "rgba(255,252,246,0.7)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: "1px solid rgba(255,255,255,0.6)",
            width: 36,
            height: 36,
            borderRadius: "50%",
            color: "var(--fg-1)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)",
          }}
        >
          {cloneElement(Icons.back, { size: 16, sw: 1.6 } as never)}
        </button>
        <h2 style={{ flex: 1, fontSize: 22, fontWeight: 500, letterSpacing: "-0.03em", margin: 0, color: "var(--fg-1)" }}>заметка</h2>
        <button
          onClick={onMore}
          aria-label="действия"
          style={{
            background: "rgba(255,252,246,0.7)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: "1px solid rgba(255,255,255,0.6)",
            width: 36,
            height: 36,
            borderRadius: "50%",
            color: "var(--fg-1)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)",
          }}
        >
          {cloneElement(ExtraIcons.more, { size: 18, sw: 1.6 } as never)}
        </button>
      </div>

      <div style={{ padding: "0 16px" }}>
        <div
          style={{
            background: "rgba(255,252,246,0.72)",
            backdropFilter: "blur(20px) saturate(160%)",
            WebkitBackdropFilter: "blur(20px) saturate(160%)",
            border: "1px solid rgba(255,255,255,0.6)",
            borderRadius: 22,
            padding: "20px 20px 22px",
            boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)",
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              color: "var(--fg-3)",
              letterSpacing: ".06em",
              marginBottom: 10,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {host && (
              <>
                <span style={{ color: "var(--fg-2)", fontWeight: 500 }}>{host}</span>
                <span style={{ width: 2.5, height: 2.5, borderRadius: "50%", background: "var(--fg-4)" }} />
              </>
            )}
            <span>{formatRelativeDate(bookmark.created_at)}</span>
            {bookmark.ai_status !== "completed" && (
              <>
                <span style={{ width: 2.5, height: 2.5, borderRadius: "50%", background: "var(--fg-4)" }} />
                <span style={{ color: "#7A5828" }}>ai обрабатывает…</span>
              </>
            )}
          </div>

          <h1 style={{ fontSize: 21, fontWeight: 500, color: "var(--fg-1)", lineHeight: 1.28, margin: "0 0 12px", letterSpacing: "-0.02em" }}>
            {title}
          </h1>

          {bookmark.summary && (
            <p
              style={{
                fontFamily: "var(--font-display)",
                fontStyle: "italic",
                fontWeight: 400,
                fontSize: 15,
                color: "var(--fg-2)",
                lineHeight: 1.5,
                margin: "0 0 14px",
                letterSpacing: 0,
              }}
            >
              {bookmark.summary}
            </p>
          )}

          {tasks && tasks.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, margin: "0 0 14px" }}>
              {tasks.map((t, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                  <span
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: 6,
                      flexShrink: 0,
                      marginTop: 1,
                      border: t.done ? "none" : "1.5px solid var(--border-strong)",
                      background: t.done ? "var(--brand-primary)" : "transparent",
                      color: "var(--fg-on-brand)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    {t.done && cloneElement(Icons.check, { size: 11, sw: 2.5 } as never)}
                  </span>
                  <span
                    style={{
                      fontSize: 14.5,
                      color: t.done ? "var(--fg-3)" : "var(--fg-1)",
                      textDecoration: t.done ? "line-through" : "none",
                      lineHeight: 1.4,
                    }}
                  >
                    {t.text}
                  </span>
                </div>
              ))}
            </div>
          )}

          {bookmark.raw_text && bookmark.raw_text !== title && (
            <p style={{ fontSize: 14.5, color: "var(--fg-1)", lineHeight: 1.55, margin: "0 0 14px", whiteSpace: "pre-wrap" }}>
              {bookmark.raw_text}
            </p>
          )}

          {bookmark.url && (
            <button
              onClick={() => openLink(bookmark.url!)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "9px 14px",
                borderRadius: 999,
                background: "var(--brand-primary-tint)",
                border: "1px solid rgba(122,156,122,0.3)",
                color: "var(--brand-primary-press)",
                fontFamily: "var(--font-ui)",
                fontSize: 13,
                fontWeight: 500,
                cursor: "pointer",
                marginBottom: bookmark.tags.length ? 14 : 0,
              }}
            >
              {cloneElement(Icons.link, { size: 14, sw: 1.8 } as never)}
              открыть источник
            </button>
          )}

          {bookmark.tags.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {bookmark.tags.map((t) => (
                <TagChip key={t.id} name={t.name} color={tagStop(t.name)} size="sm" />
              ))}
            </div>
          )}

          {bookmark.key_ideas && bookmark.key_ideas.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  letterSpacing: ".12em",
                  textTransform: "uppercase",
                  color: "var(--ai-suggest-fg)",
                  fontWeight: 500,
                  marginBottom: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Glyph ch="✦" size={12} /> ключевые мысли
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, color: "var(--fg-2)", fontSize: 14, lineHeight: 1.6 }}>
                {bookmark.key_ideas.map((k, i) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
