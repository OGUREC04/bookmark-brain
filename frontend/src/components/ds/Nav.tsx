/* Bottom Nav — 3 tabs + center FAB. Ported 1:1 from
   docs/design-system-miniapp/app/Nav.jsx. Idle = icon only, active = sage pill. */
import { cloneElement } from "react";
import { Icons, ExtraIcons } from "./icons";

export type NavTab = "mysli" | "spaces" | "me";

const tabs: { id: NavTab; label: string; icon: React.ReactElement }[] = [
  { id: "mysli", label: "мысли", icon: ExtraIcons.thoughts },
  { id: "spaces", label: "пространства", icon: ExtraIcons.spaces },
  { id: "me", label: "я", icon: Icons.user },
];

export function BottomNav({
  current,
  onChange,
  onFab,
}: {
  current: NavTab;
  onChange: (t: NavTab) => void;
  onFab: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed",
        left: 14,
        right: 14,
        bottom: "calc(24px + env(safe-area-inset-bottom, 0px))",
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 12,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          flex: 1,
          pointerEvents: "auto",
          background: "rgba(255,252,246,0.75)",
          backdropFilter: "blur(28px) saturate(180%)",
          WebkitBackdropFilter: "blur(28px) saturate(180%)",
          border: "1px solid rgba(255,255,255,0.7)",
          borderRadius: 999,
          display: "flex",
          justifyContent: "space-around",
          alignItems: "center",
          padding: "7px 8px",
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.7) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 16px 40px rgba(60,40,25,0.12)",
        }}
      >
        {tabs.map((t) => {
          const active = current === t.id;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              aria-label={t.label}
              aria-current={active ? "page" : undefined}
              style={{
                background: active ? "var(--brand-primary)" : "transparent",
                border: "none",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: active ? "8px 14px" : "8px 10px",
                borderRadius: 999,
                color: active ? "var(--fg-on-brand)" : "var(--fg-3)",
                fontFamily: "var(--font-ui)",
                fontSize: 12.5,
                fontWeight: 500,
                letterSpacing: "-0.005em",
                boxShadow: active
                  ? "0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.22)"
                  : "none",
                transition: "all 220ms var(--ease-out)",
              }}
            >
              {cloneElement(t.icon, { size: 18, sw: 1.6 } as never)}
              {active && <span>{t.label}</span>}
            </button>
          );
        })}
      </div>

      <button
        onClick={onFab}
        aria-label="создать"
        style={{
          pointerEvents: "auto",
          width: 54,
          height: 54,
          borderRadius: "50%",
          background: "var(--brand-primary)",
          color: "var(--fg-on-brand)",
          border: "none",
          cursor: "pointer",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.25) inset, 0 6px 18px rgba(122,156,122,0.4), 0 2px 6px rgba(60,40,25,0.18)",
          transition: "transform 160ms var(--ease-out)",
        }}
        onMouseDown={(e) => {
          e.currentTarget.style.transform = "translateY(1px)";
        }}
        onMouseUp={(e) => {
          e.currentTarget.style.transform = "translateY(0)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = "translateY(0)";
        }}
      >
        {cloneElement(Icons.plus, { size: 22, sw: 2 } as never)}
      </button>
    </div>
  );
}
