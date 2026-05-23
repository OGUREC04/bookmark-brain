/* Bottom Nav v2 — floating frosted pill, 3 equal grid cells (icon + always-on
   label), active = tight sage-tint capsule around icon+label (NOT a stretching
   pill) + separate sage FAB. Spec: docs reference patches/navbar_v2/README.md.
   position:fixed + safe-area (our app scrolls full-height; absolute regresses
   the content-under-nav bug). */
import { cloneElement } from "react";
import { Icons, ExtraIcons } from "./icons";

export type NavTab = "mysli" | "spaces" | "me";

const tabs: { id: NavTab; label: string; icon: React.ReactElement }[] = [
  { id: "mysli", label: "мысли", icon: ExtraIcons.thoughts },
  { id: "spaces", label: "пространства", icon: ExtraIcons.spaces },
  { id: "me", label: "я", icon: Icons.user },
];

function TabItem({
  tab,
  active,
  onClick,
}: {
  tab: { id: NavTab; label: string; icon: React.ReactElement };
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={tab.label}
      aria-current={active ? "page" : undefined}
      style={{
        background: "transparent",
        border: "none",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 0,
        minWidth: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 3,
          padding: "7px 10px 6px",
          borderRadius: 16,
          background: active ? "var(--brand-primary-tint)" : "transparent",
          color: active ? "var(--brand-primary-press)" : "var(--fg-3)",
          transition: "background 220ms var(--ease-out), color 220ms var(--ease-out)",
          minWidth: 0,
          maxWidth: "100%",
        }}
      >
        <span
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: 22,
            width: 22,
            flexShrink: 0,
          }}
        >
          {cloneElement(tab.icon, { size: 22, sw: active ? 1.8 : 1.6 } as never)}
        </span>
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 10.5,
            fontWeight: active ? 600 : 500,
            letterSpacing: "-0.005em",
            lineHeight: 1.1,
            color: "inherit",
            whiteSpace: "nowrap",
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {tab.label}
        </span>
      </div>
    </button>
  );
}

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
        bottom: "calc(22px + env(safe-area-inset-bottom, 0px))",
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        gap: 12,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          flex: 1,
          pointerEvents: "auto",
          background: "rgba(255,252,246,0.78)",
          backdropFilter: "blur(28px) saturate(180%)",
          WebkitBackdropFilter: "blur(28px) saturate(180%)",
          border: "1px solid rgba(255,255,255,0.7)",
          borderRadius: 28,
          display: "grid",
          // minmax(0,1fr): строго равные трети, не раздуваются под длинный
          // неразрывный лейбл («пространства») и не прыгают при смене актив-таба.
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          padding: "6px 4px",
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.7) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 16px 40px rgba(60,40,25,0.12)",
        }}
      >
        {tabs.map((t) => (
          <TabItem key={t.id} tab={t} active={current === t.id} onClick={() => onChange(t.id)} />
        ))}
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
