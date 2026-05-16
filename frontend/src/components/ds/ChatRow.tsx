/* ChatRow + DaySeparator — ported 1:1 from
   docs/design-system-miniapp/ds/ChatRow.jsx. Inline styles verbatim. */
import { cloneElement, type ReactNode } from "react";
import { Icons } from "./icons";
import { Glyph, Pulse } from "./atoms";

export type AvatarTone = "sage" | "honey" | "slate" | "plum" | "clay" | "moss";

export const avatarGradients: Record<AvatarTone, string> = {
  sage: "linear-gradient(135deg, #8FA888 0%, #4A6648 100%)",
  honey: "linear-gradient(135deg, #DAC8B0 0%, #B8946A 100%)",
  slate: "linear-gradient(135deg, #9BB0BE 0%, #4F6A7A 100%)",
  plum: "linear-gradient(135deg, #B5A8C0 0%, #6E5A80 100%)",
  clay: "linear-gradient(135deg, #D9907F 0%, #A04934 100%)",
  moss: "linear-gradient(135deg, #B0C28E 0%, #6E8444 100%)",
};

export interface AvatarSpec {
  kind?: "letter" | "brain" | "task" | "archive" | "icon";
  tone?: AvatarTone;
  letter?: string;
  glyph?: string;
  icon?: ReactNode;
}

export function Avatar({ kind = "letter", tone = "sage", letter = "B", glyph, icon }: AvatarSpec) {
  const base: React.CSSProperties = {
    width: 46,
    height: 46,
    borderRadius: "50%",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: "0 1px 0 rgba(255,255,255,0.4) inset, 0 2px 6px rgba(60,40,25,0.06)",
  };
  if (kind === "brain") {
    return (
      <div style={{ ...base, background: "#fff", border: "1px solid rgba(255,255,255,0.6)" }}>
        <Glyph ch={glyph || "✦"} size={24} />
      </div>
    );
  }
  if (kind === "task") {
    return (
      <div style={{ ...base, background: "rgba(255,252,246,0.9)", border: "1.5px solid var(--brand-primary)", color: "var(--brand-primary)" }}>
        {cloneElement(Icons.task, { size: 22, sw: 1.6 } as never)}
      </div>
    );
  }
  if (kind === "archive") {
    return (
      <div style={{ ...base, background: "rgba(234,227,207,0.9)", border: "1px dashed var(--border-strong)", color: "var(--fg-3)" }}>
        {cloneElement(Icons.archive, { size: 20, sw: 1.4 } as never)}
      </div>
    );
  }
  if (kind === "icon") {
    return (
      <div style={{ ...base, background: avatarGradients[tone] || avatarGradients.sage, color: "#fff" }}>
        {icon}
      </div>
    );
  }
  return (
    <div
      style={{
        ...base,
        background: avatarGradients[tone] || avatarGradients.sage,
        color: tone === "honey" ? "#2B1F12" : "#fff",
        fontFamily: "var(--font-ui)",
        fontWeight: 500,
        fontSize: 16,
        letterSpacing: "-0.01em",
      }}
    >
      {letter}
    </div>
  );
}

export interface ChatRowProps {
  avatar: AvatarSpec;
  name: ReactNode;
  time: ReactNode;
  timeNow?: boolean;
  pinned?: boolean;
  preview?: ReactNode;
  src?: string;
  unread?: boolean;
  badge?: number | string | null;
  star?: boolean;
  pulsing?: boolean;
  done?: boolean;
  muted?: boolean;
  onClick?: () => void;
  isLast?: boolean;
}

export function ChatRow({
  avatar,
  name,
  time,
  timeNow = false,
  pinned = false,
  preview,
  src,
  unread = false,
  badge = null,
  star = false,
  pulsing = false,
  done = false,
  muted = false,
  onClick,
  isLast = false,
}: ChatRowProps) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 16px",
        cursor: "pointer",
        position: "relative",
        transition: "background 160ms var(--ease-out)",
      }}
    >
      {unread && (
        <span
          style={{
            position: "absolute",
            left: 6,
            top: "50%",
            transform: "translateY(-50%)",
            width: 3,
            height: 22,
            borderRadius: 2,
            background: "var(--brand-primary)",
          }}
        />
      )}

      <Avatar {...avatar} />

      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 3,
          position: "relative",
          paddingBottom: !isLast ? 10 : 0,
          marginBottom: !isLast ? -10 : 0,
        }}
      >
        {!isLast && (
          <span
            style={{
              position: "absolute",
              left: 0,
              right: -4,
              bottom: 0,
              borderBottom: "0.5px solid var(--border-1)",
            }}
          />
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 14.5,
              fontWeight: 500,
              letterSpacing: "-0.01em",
              color: muted ? "var(--fg-3)" : "var(--fg-1)",
              flex: 1,
              minWidth: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {name}
          </span>
          {pinned && (
            <span style={{ color: "var(--fg-3)", transform: "rotate(40deg)", flexShrink: 0, display: "flex" }}>
              {cloneElement(Icons.pin, { size: 13, sw: 1.6 } as never)}
            </span>
          )}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: timeNow ? "var(--brand-primary)" : "var(--fg-3)",
              letterSpacing: ".04em",
              flexShrink: 0,
            }}
          >
            {time}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              flex: 1,
              minWidth: 0,
              fontFamily: "var(--font-display)",
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: 13.5,
              color: muted ? "var(--fg-4)" : "var(--fg-2)",
              lineHeight: 1.4,
              letterSpacing: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {done && (
              <span style={{ display: "inline-flex", verticalAlign: "-1.5px", marginRight: 6, color: "var(--brand-primary)" }}>
                {cloneElement(Icons.check, { size: 11, sw: 2.5 } as never)}
              </span>
            )}
            {src && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontStyle: "normal",
                  fontSize: 11,
                  color: "var(--fg-3)",
                  letterSpacing: ".04em",
                  marginRight: 6,
                }}
              >
                {src}
              </span>
            )}
            {preview}
          </span>
          {badge != null && (
            <span
              style={{
                flexShrink: 0,
                minWidth: 20,
                height: 20,
                padding: "0 7px",
                borderRadius: 999,
                background: "var(--brand-primary)",
                color: "var(--fg-on-brand)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                fontWeight: 500,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {badge}
            </span>
          )}
          {star && <Glyph ch="★" size={15} color="var(--brand-primary)" />}
          {pulsing && <Pulse size={7} />}
        </div>
      </div>
    </div>
  );
}

export function DaySeparator({ label }: { label: ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "12px 0 10px" }}>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--fg-3)",
          letterSpacing: ".12em",
          textTransform: "uppercase",
          fontWeight: 500,
          padding: "4px 12px",
          background: "rgba(234,227,207,0.7)",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
          borderRadius: 999,
        }}
      >
        {label}
      </span>
    </div>
  );
}
