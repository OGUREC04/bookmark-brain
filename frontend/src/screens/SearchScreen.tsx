/* ЭКРАН 2 — Поиск. Ported from docs/design-system-miniapp/app/Search.jsx,
   wired to the real /search API. */
import { useRef, useState, cloneElement } from "react";
import { Icons } from "../components/ds/icons";
import { Glyph, EmptyState } from "../components/ds/atoms";
import { api, type SearchResult as ApiResult } from "../lib/api";
import { hostOf, titleOf } from "../lib/adapters";
import { formatRelativeDate } from "../lib/formatters";

function SearchResultCard({
  src,
  time,
  title,
  summary,
  onClick,
}: {
  src: string;
  time: string;
  title: string;
  summary: string;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        background: "rgba(255,252,246,0.72)",
        backdropFilter: "blur(20px) saturate(160%)",
        WebkitBackdropFilter: "blur(20px) saturate(160%)",
        border: "1px solid rgba(255,255,255,0.6)",
        borderRadius: 20,
        padding: "16px 18px",
        marginBottom: 8,
        boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 6px 18px rgba(60,40,25,0.05)",
        cursor: "pointer",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--fg-3)",
          letterSpacing: ".06em",
          marginBottom: 6,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {src && (
          <>
            <span
              style={{
                color: "var(--fg-2)",
                fontWeight: 500,
                fontFamily: "var(--font-ui)",
                fontSize: 11,
                letterSpacing: 0,
                textTransform: "lowercase",
              }}
            >
              {src}
            </span>
            <span style={{ width: 2.5, height: 2.5, borderRadius: "50%", background: "var(--fg-4)" }} />
          </>
        )}
        <span>{time}</span>
      </div>
      <div style={{ fontSize: 15.5, fontWeight: 500, letterSpacing: "-0.02em", lineHeight: 1.25, marginBottom: 6, color: "var(--fg-1)" }}>
        {title}
      </div>
      {summary && (
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontWeight: 400,
            fontSize: 13.5,
            color: "var(--fg-2)",
            lineHeight: 1.4,
            letterSpacing: 0,
          }}
        >
          {summary}
        </div>
      )}
    </div>
  );
}

export function SearchScreen({ onBack, onOpen }: { onBack: () => void; onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<ApiResult[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const reqId = useRef(0);

  const run = async (query: string) => {
    if (!query.trim()) {
      setResults([]);
      setSummary(null);
      setSearched(false);
      return;
    }
    const id = ++reqId.current;
    setLoading(true);
    try {
      const r = await api.search(query.trim(), 20);
      if (id !== reqId.current) return; // stale response — a newer search superseded it
      setResults(r.results);
      setSummary(r.summary);
      setSearched(true);
    } catch {
      if (id !== reqId.current) return;
      setResults([]);
      setSummary(null);
      setSearched(true);
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  };

  return (
    <div style={{ padding: "6px 0 calc(116px + env(safe-area-inset-bottom, 0px))" }}>
      <div style={{ padding: "0 16px", display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
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
        <h2 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.03em", margin: 0, color: "var(--fg-1)" }}>поиск</h2>
      </div>

      {/* focused search field — matches DS SearchBar shape */}
      <div style={{ padding: "0 16px", marginBottom: 14 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "13px 18px",
            background: "rgba(255,252,246,0.72)",
            backdropFilter: "blur(20px) saturate(160%)",
            WebkitBackdropFilter: "blur(20px) saturate(160%)",
            border: "1px solid var(--brand-primary)",
            borderRadius: 999,
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.6) inset, 0 0 0 4px rgba(122,156,122,0.18), 0 8px 20px rgba(60,90,60,0.1)",
          }}
        >
          <span style={{ color: "var(--fg-3)", display: "flex", flexShrink: 0 }}>
            {cloneElement(Icons.search, { size: 18, sw: 1.6 } as never)}
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") run(q);
            }}
            autoFocus
            placeholder="найти в памяти…"
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              background: "transparent",
              font: "inherit",
              fontSize: 15,
              color: "var(--fg-1)",
              letterSpacing: "-0.01em",
            }}
          />
        </div>
      </div>

      {loading && (
        <div style={{ padding: "40px 0", display: "flex", justifyContent: "center" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--brand-primary)", animation: "mPulse 1.6s ease-in-out infinite" }} />
        </div>
      )}

      {!loading && searched && summary && (
        <div
          style={{
            margin: "0 16px 12px",
            background: "linear-gradient(160deg, rgba(226,237,226,0.7) 0%, rgba(207,223,207,0.55) 100%)",
            backdropFilter: "blur(18px) saturate(150%)",
            WebkitBackdropFilter: "blur(18px) saturate(150%)",
            border: "1px solid rgba(207,223,207,0.7)",
            borderRadius: 18,
            padding: "14px 16px",
            boxShadow: "0 1px 0 rgba(255,255,255,0.5) inset, 0 4px 14px rgba(60,90,60,0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: ".14em",
              textTransform: "uppercase",
              color: "var(--ai-suggest-fg)",
              fontWeight: 500,
            }}
          >
            <Glyph ch="✦" size={12} /> ответ по сохранённому
          </div>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--font-display)",
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: 14.5,
              color: "var(--fg-1)",
              lineHeight: 1.45,
              letterSpacing: 0,
            }}
          >
            {summary}
          </p>
        </div>
      )}

      {!loading && searched && results.length > 0 && (
        <div style={{ padding: "0 16px" }}>
          {results.map((r) => (
            <SearchResultCard
              key={r.bookmark.id}
              src={r.bookmark.url ? hostOf(r.bookmark.url) : ""}
              time={formatRelativeDate(r.bookmark.created_at)}
              title={titleOf(r.bookmark)}
              summary={r.bookmark.summary || ""}
              onClick={() => onOpen(r.bookmark.id)}
            />
          ))}
        </div>
      )}

      {!loading && !searched && (
        <EmptyState
          glyph="?"
          head="о чём подумать?"
          copy={
            <>
              «анализ rlhf» · «рецепт идли»
              <br />
              «про что был тот тред»
            </>
          }
        />
      )}
      {!loading && searched && results.length === 0 && (
        <EmptyState
          glyph="∅"
          head="ничего не нашлось"
          copy={
            <>
              попробуй другие слова
              <br />
              или сними фильтры
            </>
          }
        />
      )}
    </div>
  );
}
