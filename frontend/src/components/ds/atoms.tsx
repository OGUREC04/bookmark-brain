/* DS atoms — ported 1:1 from docs/design-system-miniapp/ds/Atoms.jsx.
   Inline styles kept verbatim (reference CSS vars live in tokens.css). */
import { cloneElement, type ReactNode, type CSSProperties } from "react";
import { Icons } from "./icons";

/* ─── editorial glyph (Lora italic char as icon) ─── */
export function Glyph({
  ch,
  size = 28,
  color = "var(--brand-primary)",
  weight = 500,
  opacity = 1,
}: {
  ch: string;
  size?: number;
  color?: string;
  weight?: number;
  opacity?: number;
}) {
  return (
    <span
      aria-hidden="true"
      style={{
        fontFamily: "var(--font-display)",
        fontStyle: "italic",
        fontWeight: weight,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.01em",
        color,
        opacity,
        display: "inline-block",
      }}
    >
      {ch}
    </span>
  );
}

/* ─── tag palette · sage-anchored warm ─── */
export const tagPalette: Record<number, { bg: string; fg: string }> = {
  1: { bg: "#E2EDE2", fg: "#2F4A2F" },
  2: { bg: "#F4E6CC", fg: "#7A5828" },
  3: { bg: "#D8E2EA", fg: "#3D5A6E" },
  4: { bg: "#E5D8E8", fg: "#5C3D6E" },
  5: { bg: "#EFD8D2", fg: "#8A2A20" },
  6: { bg: "#E0E5C8", fg: "#4A5A2A" },
  7: { bg: "#F4D8DC", fg: "#8A2A35" },
  8: { bg: "#E0DED8", fg: "#56544C" },
};

/** Deterministic stop 1..8 from a tag name (no colour stored in DB). */
export function tagStop(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h + name.charCodeAt(i)) % 8;
  return h + 1;
}

export function TagChip({
  name,
  color = 1,
  onClick,
  size = "md",
}: {
  name: string;
  color?: number;
  onClick?: () => void;
  size?: "sm" | "md";
}) {
  const c = tagPalette[color] || tagPalette[1];
  const sz = size === "sm" ? { pad: "3px 10px", fs: 11 } : { pad: "5px 12px", fs: 12 };
  return (
    <span
      onClick={onClick}
      style={{
        padding: sz.pad,
        borderRadius: 999,
        fontSize: sz.fs,
        fontWeight: 500,
        background: c.bg,
        color: c.fg,
        cursor: onClick ? "pointer" : "default",
        whiteSpace: "nowrap",
        fontFamily: "var(--font-ui)",
        letterSpacing: "-0.005em",
      }}
    >
      {`#${name}`}
    </span>
  );
}

/* ─── pulsing dot (DS spinner replacement) ─── */
export function Pulse({ size = 8, color = "var(--brand-primary)" }: { size?: number; color?: string }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        animation: "mPulse 1.6s ease-in-out infinite",
        display: "inline-block",
        flexShrink: 0,
      }}
    />
  );
}

/* ─── liquid glass tile ─── */
export function GlassTile({
  children,
  strong = false,
  style = {},
}: {
  children: ReactNode;
  strong?: boolean;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        background: strong ? "rgba(255,252,246,0.72)" : "rgba(255,252,246,0.55)",
        backdropFilter: `blur(${strong ? 32 : 20}px) saturate(${strong ? 160 : 140}%)`,
        WebkitBackdropFilter: `blur(${strong ? 32 : 20}px) saturate(${strong ? 160 : 140}%)`,
        border: "1px solid rgba(255,255,255,0.6)",
        borderRadius: strong ? 28 : 22,
        boxShadow:
          "0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 10px 30px rgba(60,40,25,0.08)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* ─── search bar — telegram-style glass pill ─── */
export function SearchBar({
  value,
  placeholder = "найти в памяти…",
  onFocus,
  onChange,
  focused,
}: {
  value?: string;
  placeholder?: string;
  onFocus?: () => void;
  onChange?: (v: string) => void;
  focused?: boolean;
}) {
  return (
    <div
      onClick={onFocus}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "13px 18px",
        background: "rgba(255,252,246,0.72)",
        backdropFilter: "blur(20px) saturate(160%)",
        WebkitBackdropFilter: "blur(20px) saturate(160%)",
        border: `1px solid ${focused ? "var(--brand-primary)" : "rgba(255,255,255,0.6)"}`,
        borderRadius: 999,
        cursor: "text",
        boxShadow: focused
          ? "0 1px 0 rgba(255,255,255,0.6) inset, 0 0 0 4px rgba(122,156,122,0.18), 0 8px 20px rgba(60,90,60,0.1)"
          : "0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 4px 12px rgba(60,40,25,0.06)",
        transition: "box-shadow 200ms",
      }}
    >
      <span style={{ color: "var(--fg-3)", display: "flex", flexShrink: 0 }}>
        {cloneElement(Icons.search, { size: 18, sw: 1.6 } as never)}
      </span>
      {value !== undefined && value !== "" ? (
        <input
          value={value}
          onChange={(e) => onChange && onChange(e.target.value)}
          autoFocus
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
      ) : (
        <span
          style={{
            flex: 1,
            fontSize: 15,
            color: "var(--fg-3)",
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontWeight: 400,
          }}
        >
          {placeholder}
        </span>
      )}
    </div>
  );
}

/* ─── empty state · big editorial glyph ─── */
export function EmptyState({
  glyph = "∅",
  head,
  copy,
}: {
  glyph?: string;
  head: ReactNode;
  copy?: ReactNode;
}) {
  return (
    <div style={{ textAlign: "center", padding: "48px 24px 64px" }}>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontStyle: "italic",
          fontSize: 72,
          color: "var(--brand-primary)",
          lineHeight: 1,
          marginBottom: 18,
          opacity: 0.55,
        }}
      >
        {glyph}
      </div>
      <div
        style={{
          fontSize: 17,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          color: "var(--fg-1)",
          marginBottom: 6,
        }}
      >
        {head}
      </div>
      {copy && (
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontSize: 14,
            color: "var(--fg-3)",
            lineHeight: 1.4,
            letterSpacing: 0,
          }}
        >
          {copy}
        </div>
      )}
    </div>
  );
}
