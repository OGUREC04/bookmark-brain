/* ЭКРАН 1 — Мысли. Ported 1:1 from docs/design-system-miniapp/app/Mysli.jsx,
   wired to the real bookmarks API via adapters. */
import { useEffect, useState, cloneElement } from "react";
import { Icons, ExtraIcons } from "../components/ds/icons";
import { Glyph, SearchBar, EmptyState } from "../components/ds/atoms";
import { ChatRow, DaySeparator } from "../components/ds/ChatRow";
import { BookmarkCard } from "../components/ds/BookmarkCard";
import { SuggestionPager } from "../components/ds/SuggestionPager";
import { api, type Bookmark } from "../lib/api";
import { bookmarkToChatRow, bookmarkToCard, matchesFilter } from "../lib/adapters";
import { formatRelativeDate } from "../lib/formatters";

type Filter = "all" | "fav" | "task" | "voice";

function ReminderBell({ count = 0, onClick }: { count?: number; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label="напоминания"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px 5px 8px",
        background: "var(--brand-primary-tint)",
        border: "1px solid rgba(122,156,122,0.25)",
        borderRadius: 999,
        cursor: "pointer",
        color: "var(--brand-primary-press)",
        boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,90,60,0.06)",
      }}
    >
      {cloneElement(ExtraIcons.clock, { size: 14, sw: 1.6 } as never)}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600, letterSpacing: ".04em" }}>{count}</span>
    </button>
  );
}

function FilterChipsRow({ active, onChange }: { active: Filter; onChange: (f: Filter) => void }) {
  const items: { id: Filter; label: string; glyph?: string }[] = [
    { id: "all", label: "все" },
    { id: "fav", glyph: "★", label: "" },
    { id: "task", label: "задачи" },
    { id: "voice", label: "голос" },
  ];
  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: 4,
        padding: "8px 16px 10px",
        marginBottom: 4,
        background:
          "linear-gradient(180deg, rgba(247,243,233,0.92) 0%, rgba(247,243,233,0.85) 70%, rgba(247,243,233,0) 100%)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        display: "flex",
        gap: 6,
        overflowX: "auto",
        scrollbarWidth: "none",
      }}
    >
      {items.map((it) => {
        const on = active === it.id;
        return (
          <button
            key={it.id}
            onClick={() => onChange(it.id)}
            style={{
              flexShrink: 0,
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              padding: "7px 14px",
              borderRadius: 999,
              fontFamily: "var(--font-ui)",
              fontSize: 12.5,
              fontWeight: 500,
              letterSpacing: "-0.005em",
              background: on ? "var(--brand-primary)" : "rgba(255,252,246,0.55)",
              color: on ? "var(--fg-on-brand)" : "var(--fg-2)",
              border: on ? "none" : "1px solid rgba(255,255,255,0.6)",
              backdropFilter: on ? "none" : "blur(12px)",
              WebkitBackdropFilter: on ? "none" : "blur(12px)",
              boxShadow: on
                ? "0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.22)"
                : "0 1px 0 rgba(255,255,255,0.6) inset, 0 1px 3px rgba(60,40,25,0.04)",
              cursor: "pointer",
            }}
          >
            {it.glyph && <Glyph ch={it.glyph} size={13} color={on ? "currentColor" : "var(--brand-primary)"} />}
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

function ViewToggle({ view, setView }: { view: "chat" | "cards"; setView: (v: "chat" | "cards") => void }) {
  const btn = (id: "chat" | "cards", label: string, icon: React.ReactElement) => (
    <button
      onClick={() => setView(id)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 12px",
        borderRadius: 999,
        cursor: "pointer",
        fontFamily: "var(--font-ui)",
        fontSize: 12,
        fontWeight: 500,
        letterSpacing: "-0.005em",
        background: view === id ? "rgba(255,252,246,0.85)" : "transparent",
        border: view === id ? "1px solid rgba(255,255,255,0.6)" : "1px solid transparent",
        color: view === id ? "var(--fg-1)" : "var(--fg-3)",
        backdropFilter: view === id ? "blur(12px)" : "none",
        WebkitBackdropFilter: view === id ? "blur(12px)" : "none",
        boxShadow: view === id ? "0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)" : "none",
      }}
    >
      {cloneElement(icon, { size: 14, sw: 1.6 } as never)}
      {label}
    </button>
  );
  return (
    <div
      style={{
        display: "inline-flex",
        gap: 2,
        padding: 3,
        background: "rgba(234,227,207,0.4)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderRadius: 999,
      }}
    >
      {btn("chat", "chat", Icons.feed)}
      {btn("cards", "cards", Icons.cards)}
    </div>
  );
}

const SUGGESTION_DEMO = [
  {
    text: (
      <>
        3 закладки про rlhf — собрать в{" "}
        <b style={{ fontFamily: "var(--font-ui)", fontStyle: "normal", fontWeight: 500, color: "var(--brand-primary)" }}>
          «alignment»
        </b>
        ?
      </>
    ),
    sources: [
      { letter: "A", tone: "sage" as const, domain: "anthropic" },
      { letter: "O", tone: "slate" as const, domain: "openai" },
      { letter: "K", tone: "honey" as const, domain: "x.com" },
    ],
  },
  {
    text: (
      <>
        год назад ты сохранил{" "}
        <b style={{ fontFamily: "var(--font-ui)", fontStyle: "normal", fontWeight: 500, color: "var(--fg-1)" }}>
          «scaling laws»
        </b>{" "}
        — открыть?
      </>
    ),
    sources: [{ letter: "S", tone: "plum" as const, domain: "arxiv.org" }],
    meta: "11 месяцев в очереди",
  },
];

export function MysliScreen({
  reloadKey,
  onSearch,
  onBell,
  onMore,
  onOpen,
}: {
  reloadKey: number;
  onSearch: () => void;
  onBell: () => void;
  onMore: (b: Bookmark) => void;
  onOpen: (b: Bookmark) => void;
}) {
  const [view, setView] = useState<"chat" | "cards">("chat");
  const [filter, setFilter] = useState<Filter>("all");
  const [hideSuggest, setHideSuggest] = useState(false);
  const [items, setItems] = useState<Bookmark[]>([]);
  const [total, setTotal] = useState(0);
  const [reminderCount, setReminderCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [list, rem] = await Promise.all([
          api.getBookmarks({ perPage: 50, isArchived: false }),
          api.reminders.upcoming(50).catch(() => ({ items: [], total: 0 })),
        ]);
        if (!alive) return;
        setItems(list.items);
        setTotal(list.total);
        setReminderCount(rem.total);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
    // refetch on reloadKey bump (after a mutation) without unmount/flash
  }, [reloadKey]);

  const filtered = items.filter((b) => matchesFilter(b, filter));

  return (
    <div style={{ padding: "6px 0 100px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 16px",
          marginBottom: 14,
          marginTop: 4,
          gap: 10,
        }}
      >
        <h1 style={{ fontSize: 32, fontWeight: 500, letterSpacing: "-0.035em", margin: 0, color: "var(--fg-1)", lineHeight: 1 }}>
          мысли
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontStyle: "italic",
              fontWeight: 500,
              color: "var(--brand-primary)",
              marginLeft: 6,
              letterSpacing: "-0.01em",
            }}
          >
            ·
          </span>
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ReminderBell count={reminderCount} onClick={onBell} />
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-3)", letterSpacing: ".06em", fontWeight: 500 }}>
            {total}
          </span>
        </div>
      </div>

      <div style={{ padding: "0 16px", marginBottom: 14 }}>
        <SearchBar onFocus={onSearch} />
      </div>

      <div style={{ padding: "0 16px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
        <ViewToggle view={view} setView={setView} />
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--fg-3)",
            letterSpacing: ".12em",
            textTransform: "uppercase",
            fontWeight: 500,
          }}
        >
          сегодня
        </span>
      </div>

      <FilterChipsRow active={filter} onChange={setFilter} />

      {!hideSuggest && view === "chat" && filter === "all" && !loading && items.length > 0 && (
        <SuggestionPager items={SUGGESTION_DEMO} onDismissAll={() => setHideSuggest(true)} />
      )}

      {loading ? (
        <div style={{ padding: "40px 0", display: "flex", justifyContent: "center" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--brand-primary)", animation: "mPulse 1.6s ease-in-out infinite" }} />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          glyph="∅"
          head={items.length === 0 ? "пока пусто" : "ничего по этому фильтру"}
          copy={items.length === 0 ? "сохрани первую мысль через +" : "сбрось чипы, чтобы увидеть всё"}
        />
      ) : view === "chat" ? (
        <ChatView items={filtered} onMore={onMore} onOpen={onOpen} />
      ) : (
        <div style={{ padding: "4px 16px 0" }}>
          {filtered.map((b) => (
            <BookmarkCard key={b.id} bookmark={bookmarkToCard(b)} onOpen={() => onOpen(b)} onMore={() => onMore(b)} />
          ))}
        </div>
      )}
    </div>
  );
}

function ChatView({
  items,
  onMore,
  onOpen,
}: {
  items: Bookmark[];
  onMore: (b: Bookmark) => void;
  onOpen: (b: Bookmark) => void;
}) {
  // group by relative day for DaySeparator
  const rows: ({ sep: string } | { b: Bookmark })[] = [];
  let lastDay = "";
  for (const b of items) {
    const day = formatRelativeDate(b.created_at);
    const dayKey = /^\d{2}:\d{2}$/.test(day) ? "сегодня" : day;
    if (dayKey !== lastDay) {
      rows.push({ sep: dayKey });
      lastDay = dayKey;
    }
    rows.push({ b });
  }

  return (
    <div>
      {rows.map((r, i) => {
        if ("sep" in r) return <DaySeparator key={`s${i}`} label={r.sep} />;
        const cr = bookmarkToChatRow(r.b);
        const last = i === rows.length - 1;
        return (
          <div key={r.b.id} onClick={() => onOpen(r.b)}>
            <ChatRow
              avatar={cr.avatar}
              name={cr.name}
              time={cr.time}
              preview={cr.preview}
              src={cr.src}
              star={cr.star}
              pulsing={cr.pulsing}
              done={cr.done}
              muted={cr.muted}
              onMore={() => onMore(r.b)}
              isLast={last}
            />
          </div>
        );
      })}
    </div>
  );
}
