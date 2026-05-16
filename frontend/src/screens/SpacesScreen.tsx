/* ЭКРАН 3 — Пространства. Ported from docs/design-system-miniapp/app/Spaces.jsx,
   wired to the real /folders API. */
import { useEffect, useState, cloneElement } from "react";
import { Icons } from "../components/ds/icons";
import { Glyph } from "../components/ds/atoms";
import { api, type Folder } from "../lib/api";

const TONE_GRADS: Record<string, string> = {
  sage: "linear-gradient(135deg, #BBD0BA 0%, #7A9C7A 100%)",
  honey: "linear-gradient(135deg, #E6D2B0 0%, #B8946A 100%)",
  slate: "linear-gradient(135deg, #B6C7D2 0%, #6E8898 100%)",
  plum: "linear-gradient(135deg, #C9BCD3 0%, #8E7AA0 100%)",
  clay: "linear-gradient(135deg, #E6B5A8 0%, #B86A55 100%)",
  moss: "linear-gradient(135deg, #C5D49D 0%, #8AA15A 100%)",
};
const TONES = ["sage", "honey", "slate", "plum", "clay", "moss"];
const GLYPHS = ["¶", "§", "℘", "∞", "★", "∆", "◇", "∴"];

function pick<T>(arr: T[], seed: string): T {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h + seed.charCodeAt(i)) % arr.length;
  return arr[h];
}

function SpaceTile({ folder, onClick }: { folder: Folder; onClick?: () => void }) {
  const tone = pick(TONES, folder.id);
  const glyph = folder.emoji || pick(GLYPHS, folder.name);
  return (
    <div
      onClick={onClick}
      style={{
        position: "relative",
        overflow: "hidden",
        background: "rgba(255,252,246,0.55)",
        backdropFilter: "blur(20px) saturate(150%)",
        WebkitBackdropFilter: "blur(20px) saturate(150%)",
        border: "1px solid rgba(255,255,255,0.6)",
        borderRadius: 22,
        padding: "14px 14px 14px",
        minHeight: 130,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 6px 18px rgba(60,40,25,0.05)",
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          borderRadius: 12,
          background: TONE_GRADS[tone] || TONE_GRADS.sage,
          color: tone === "honey" ? "#2B1F12" : "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 1px 0 rgba(255,255,255,0.4) inset, 0 4px 10px rgba(60,40,25,0.08)",
        }}
      >
        <Glyph ch={glyph} size={22} color="currentColor" />
      </div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <span style={{ fontSize: 14.5, fontWeight: 500, color: "var(--fg-1)", letterSpacing: "-0.01em" }}>{folder.name}</span>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--fg-3)", letterSpacing: ".06em", fontWeight: 500 }}>
          {folder.bookmarks_count} закладок
        </div>
      </div>
    </div>
  );
}

function CreateSpaceTile({ onClick }: { onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        background: "rgba(255,252,246,0.35)",
        backdropFilter: "blur(20px) saturate(140%)",
        WebkitBackdropFilter: "blur(20px) saturate(140%)",
        border: "1px dashed var(--border-strong)",
        borderRadius: 22,
        padding: "14px",
        minHeight: 130,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "space-between",
        color: "var(--fg-3)",
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          borderRadius: 12,
          background: "rgba(255,252,246,0.6)",
          border: "1px solid var(--border-2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--brand-primary)",
        }}
      >
        {cloneElement(Icons.plus, { size: 18, sw: 1.8 } as never)}
      </div>
      <div>
        <div style={{ fontSize: 14.5, fontWeight: 500, color: "var(--fg-2)", letterSpacing: "-0.01em", marginBottom: 4 }}>
          создать
        </div>
        <div style={{ fontFamily: "var(--font-display)", fontStyle: "italic", fontSize: 12.5, color: "var(--fg-3)", letterSpacing: 0 }}>
          или дай AI собрать
        </div>
      </div>
    </div>
  );
}

export function SpacesScreen({ onOpen, onCreate }: { onOpen: (f: Folder) => void; onCreate: () => void }) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .getFolders()
      .then((f) => alive && setFolders(f))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div style={{ padding: "6px 16px 100px" }}>
      <div style={{ marginBottom: 4, marginTop: 4 }}>
        <h1 style={{ fontSize: 32, fontWeight: 500, letterSpacing: "-0.035em", margin: 0, color: "var(--fg-1)", lineHeight: 1 }}>
          пространства
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
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontStyle: "italic",
          fontWeight: 400,
          fontSize: 14,
          color: "var(--fg-2)",
          margin: "8px 0 18px",
          letterSpacing: 0,
          lineHeight: 1.4,
        }}
      >
        {loading ? "загрузка…" : `${folders.length} пространств · AI собирает похожее само`}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {folders.map((f) => (
          <SpaceTile key={f.id} folder={f} onClick={() => onOpen(f)} />
        ))}
        <CreateSpaceTile onClick={onCreate} />
      </div>
    </div>
  );
}
