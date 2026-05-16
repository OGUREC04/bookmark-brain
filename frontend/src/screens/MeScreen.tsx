/* ЭКРАН 4 — Я. Ported from docs/design-system-miniapp/app/Me.jsx,
   profile/stats wired to /users/me. */
import { useEffect, useState } from "react";
import { api, type UserInfo } from "../lib/api";
import { formatDate } from "../lib/formatters";

function Stat({ n, l }: { n: string | number; l: string }) {
  return (
    <div
      style={{
        background: "rgba(255,252,246,0.55)",
        backdropFilter: "blur(16px) saturate(140%)",
        WebkitBackdropFilter: "blur(16px) saturate(140%)",
        border: "1px solid rgba(255,255,255,0.6)",
        borderRadius: 16,
        padding: "14px 8px",
        textAlign: "center",
        boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 12px rgba(60,40,25,0.04)",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontStyle: "italic",
          fontWeight: 500,
          fontSize: 28,
          color: "var(--brand-primary)",
          lineHeight: 1,
          letterSpacing: "-0.01em",
        }}
      >
        {n}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--fg-3)",
          letterSpacing: ".08em",
          textTransform: "uppercase",
          marginTop: 6,
          fontWeight: 500,
        }}
      >
        {l}
      </div>
    </div>
  );
}

function SettingsGroup({
  title,
  rows,
  onRow,
}: {
  title: string;
  rows: { l: string; r: string; danger?: boolean }[];
  onRow?: (l: string) => void;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: ".12em",
          textTransform: "uppercase",
          color: "var(--fg-3)",
          fontWeight: 500,
          padding: "0 4px 8px",
        }}
      >
        {title}
      </div>
      <div
        style={{
          background: "rgba(255,252,246,0.72)",
          backdropFilter: "blur(20px) saturate(160%)",
          WebkitBackdropFilter: "blur(20px) saturate(160%)",
          border: "1px solid rgba(255,255,255,0.6)",
          borderRadius: 22,
          overflow: "hidden",
          boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)",
        }}
      >
        {rows.map((it, i) => (
          <div
            key={it.l}
            onClick={() => onRow?.(it.l)}
            style={{
              display: "flex",
              alignItems: "center",
              padding: "14px 16px",
              borderBottom: i < rows.length - 1 ? "1px solid var(--border-1)" : "none",
              fontSize: 14.5,
              letterSpacing: "-0.01em",
              cursor: "pointer",
            }}
          >
            <span style={{ flex: 1, color: it.danger ? "var(--semantic-error, #8A2A20)" : "var(--fg-1)" }}>{it.l}</span>
            <span
              style={{
                fontFamily: it.r === "→" ? "var(--font-ui)" : "var(--font-mono)",
                fontSize: it.r === "→" ? 14 : 11,
                color: "var(--fg-3)",
                letterSpacing: ".04em",
              }}
            >
              {it.r}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MeScreen() {
  const [me, setMe] = useState<UserInfo | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getMe()
      .then((u) => alive && setMe(u))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const handle = me?.telegram_username
    ? `@${me.telegram_username}`
    : me?.telegram_first_name || "@anonim";
  const initial = (handle.replace("@", "")[0] || "а").toLowerCase();
  const since = me ? `с ${formatDate(me.created_at)}` : "";

  return (
    <div style={{ padding: "6px 16px 100px" }}>
      <h1 style={{ fontSize: 32, fontWeight: 500, letterSpacing: "-0.035em", margin: "4px 0 16px", color: "var(--fg-1)", lineHeight: 1 }}>
        я
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

      <div
        style={{
          background: "rgba(255,252,246,0.72)",
          backdropFilter: "blur(20px) saturate(160%)",
          WebkitBackdropFilter: "blur(20px) saturate(160%)",
          border: "1px solid rgba(255,255,255,0.6)",
          borderRadius: 22,
          padding: 16,
          display: "flex",
          gap: 14,
          alignItems: "center",
          marginBottom: 10,
          boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)",
        }}
      >
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #8FA888 0%, #4A6648 100%)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 1px 0 rgba(255,255,255,0.4) inset, 0 2px 6px rgba(60,40,25,0.06)",
          }}
        >
          <span style={{ fontFamily: "var(--font-display)", fontStyle: "italic", fontWeight: 500, fontSize: 30, letterSpacing: "-0.01em" }}>
            {initial}
          </span>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 500, letterSpacing: "-0.02em", color: "var(--fg-1)" }}>{handle}</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-3)", letterSpacing: ".06em", marginTop: 2 }}>
            {me ? `${me.bookmarks_count} закладок · ${since}` : "загрузка…"}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 16 }}>
        <Stat n={me?.bookmarks_count ?? "—"} l="всего" />
        <Stat n="—" l="на неделе" />
        <Stat n="—" l="прочитал" />
      </div>

      <SettingsGroup
        title="приватность"
        rows={[
          { l: "тихий режим", r: "в боте" },
          { l: "AI-подсказки", r: "вкл" },
          { l: "таймзона", r: "GMT+3" },
        ]}
      />
      <SettingsGroup
        title="вид"
        rows={[
          { l: "тема", r: "светлая" },
          { l: "архивировать через", r: "90 дней" },
          { l: "плотность списка", r: "обычная" },
        ]}
      />
      <SettingsGroup
        title="данные"
        rows={[
          { l: "экспорт в Markdown", r: "→" },
          { l: "подключить Notion", r: "→" },
        ]}
      />

      <div
        style={{
          fontFamily: "var(--font-display)",
          fontStyle: "italic",
          fontSize: 12.5,
          color: "var(--fg-3)",
          textAlign: "center",
          letterSpacing: 0,
          marginTop: 18,
        }}
      >
        v0.5 · собрано вручную
      </div>
    </div>
  );
}
