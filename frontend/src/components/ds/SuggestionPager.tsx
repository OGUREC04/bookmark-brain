/* SuggestionPager — ported 1:1 from docs/design-system-miniapp/ds/SuggestionCard.jsx
   (only the pager path; Mysli uses this. SuggestionCard/Compact/Recall omitted.) */
import { useRef, useState, cloneElement, type ReactNode } from "react";
import { Icons } from "./icons";

type Tone = "sage" | "honey" | "slate" | "plum" | "clay";

const grads: Record<Tone, string> = {
  sage: "linear-gradient(135deg, #8FA888 0%, #4A6648 100%)",
  honey: "linear-gradient(135deg, #DAC8B0 0%, #B8946A 100%)",
  slate: "linear-gradient(135deg, #9BB0BE 0%, #4F6A7A 100%)",
  plum: "linear-gradient(135deg, #B5A8C0 0%, #6E5A80 100%)",
  clay: "linear-gradient(135deg, #D9907F 0%, #A04934 100%)",
};

interface Source {
  letter: string;
  tone?: Tone;
  domain: string;
}
export interface SuggestionItem {
  text: ReactNode;
  sources?: Source[];
  meta?: string;
  onAccept?: () => void;
}

function SourceChip({ letter, tone = "sage", domain }: Source) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px 3px 3px",
        borderRadius: 999,
        background: "rgba(255,252,246,0.7)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: "1px solid rgba(255,255,255,0.65)",
        minWidth: 0,
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: grads[tone] || grads.sage,
          color: tone === "honey" ? "#2B1F12" : "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-ui)",
          fontWeight: 500,
          fontSize: 10,
          letterSpacing: "-0.01em",
          flexShrink: 0,
          boxShadow: "0 1px 0 rgba(255,255,255,0.4) inset",
        }}
      >
        {letter}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--fg-2)",
          letterSpacing: ".04em",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {domain}
      </span>
    </span>
  );
}

function SuggestionSlide({ text, sources = [], meta, onAccept }: SuggestionItem) {
  return (
    <div
      style={{
        flexShrink: 0,
        width: "calc(86% - 16px * 0.86)",
        minWidth: 280,
        maxWidth: 340,
        scrollSnapAlign: "start",
        scrollSnapStop: "always",
        position: "relative",
        overflow: "hidden",
        background: "linear-gradient(160deg, rgba(226,237,226,0.88) 0%, rgba(207,223,207,0.75) 100%)",
        backdropFilter: "blur(20px) saturate(160%)",
        WebkitBackdropFilter: "blur(20px) saturate(160%)",
        border: "1px solid rgba(207,223,207,0.7)",
        borderRadius: 22,
        padding: "18px 18px 16px",
        boxShadow: "0 1px 0 rgba(255,255,255,0.5) inset, 0 8px 22px rgba(60,90,60,0.08)",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: "-50%",
          right: "-25%",
          width: 220,
          height: 220,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(122,156,122,0.18) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "relative",
          fontFamily: "var(--font-display)",
          fontStyle: "italic",
          fontWeight: 500,
          fontSize: 19,
          color: "var(--fg-1)",
          lineHeight: 1.25,
          letterSpacing: "-0.005em",
        }}
      >
        {text}
      </div>

      {sources.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, position: "relative", flexWrap: "nowrap", overflow: "hidden" }}>
          {sources.slice(0, 3).map((s, i) => (
            <SourceChip key={i} {...s} />
          ))}
          {sources.length > 3 && (
            <span
              style={{
                flexShrink: 0,
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                color: "var(--ai-suggest-fg)",
                letterSpacing: ".06em",
                padding: "4px 8px",
                borderRadius: 999,
                background: "rgba(255,252,246,0.6)",
                border: "1px solid rgba(255,255,255,0.6)",
              }}
            >
              +{sources.length - 3}
            </span>
          )}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: "auto", position: "relative" }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--ai-suggest-fg)",
            letterSpacing: ".08em",
            textTransform: "uppercase",
            fontWeight: 500,
          }}
        >
          {meta || `${sources.length} ${sources.length === 1 ? "ссылка" : "ссылки"}`}
        </span>
        <span style={{ flex: 1 }} />
        <button
          onClick={onAccept}
          aria-label="показать"
          style={{
            flexShrink: 0,
            background: "rgba(255,252,246,0.92)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: "1px solid rgba(255,255,255,0.7)",
            width: 34,
            height: 34,
            borderRadius: "50%",
            color: "var(--brand-primary)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 1px 0 rgba(255,255,255,0.7) inset, 0 3px 10px rgba(60,90,60,0.12)",
          }}
        >
          {cloneElement(Icons.arrow, { size: 15, sw: 1.8 } as never)}
        </button>
      </div>
    </div>
  );
}

export function SuggestionPager({ items, onDismissAll }: { items: SuggestionItem[]; onDismissAll?: () => void }) {
  const [idx, setIdx] = useState(0);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const onScroll = () => {
    const el = scrollerRef.current;
    if (!el || !el.firstElementChild) return;
    const step = (el.firstElementChild as HTMLElement).getBoundingClientRect().width + 10;
    const i = Math.round(el.scrollLeft / step);
    if (i !== idx) setIdx(Math.min(items.length - 1, Math.max(0, i)));
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", padding: "0 16px", marginBottom: 10 }}>
        <div
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 11,
            letterSpacing: ".12em",
            textTransform: "uppercase",
            color: "var(--ai-suggest-fg)",
            fontWeight: 500,
          }}
        >
          подсказки
        </div>
        <span style={{ flex: 1 }} />
        {items.length > 1 && (
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            {items.map((_, i) => (
              <span
                key={i}
                style={{
                  width: i === idx ? 14 : 5,
                  height: 5,
                  borderRadius: 999,
                  background: i === idx ? "var(--brand-primary)" : "var(--fg-4)",
                  opacity: i === idx ? 1 : 0.5,
                  transition: "width 240ms var(--ease-out), opacity 240ms",
                }}
              />
            ))}
          </div>
        )}
        {onDismissAll && (
          <button
            onClick={onDismissAll}
            aria-label="скрыть подсказки"
            style={{
              marginLeft: 10,
              background: "transparent",
              border: "none",
              color: "var(--fg-3)",
              cursor: "pointer",
              display: "flex",
            }}
          >
            {cloneElement(Icons.close, { size: 13, sw: 1.8 } as never)}
          </button>
        )}
      </div>

      <div
        ref={scrollerRef}
        onScroll={onScroll}
        style={{
          display: "flex",
          gap: 10,
          overflowX: "auto",
          overflowY: "hidden",
          scrollSnapType: "x mandatory",
          padding: "0 16px 4px",
          scrollPaddingLeft: 16,
          scrollbarWidth: "none",
          WebkitOverflowScrolling: "touch",
        }}
      >
        {items.map((item, i) => (
          <SuggestionSlide key={i} {...item} />
        ))}
      </div>
    </div>
  );
}
