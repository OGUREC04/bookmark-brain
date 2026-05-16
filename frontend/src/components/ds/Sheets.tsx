/* Bottom Sheets — ported 1:1 from docs/design-system-miniapp/app/Sheets.jsx.
   Visual inline styles verbatim; data wired via props. */
import { useState, cloneElement, type ReactNode } from "react";
import { Icons, ExtraIcons } from "./icons";
import { Glyph } from "./atoms";
import { Avatar } from "./ChatRow";

export function BottomSheet({
  children,
  onDismiss,
  paddingBottom = 24,
  height = "auto",
}: {
  children: ReactNode;
  onDismiss?: () => void;
  paddingBottom?: number;
  height?: string;
}) {
  return (
    <>
      <div
        onClick={onDismiss}
        style={{
          position: "absolute",
          inset: 0,
          background: "var(--bg-overlay, rgba(28,22,18,0.32))",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
          zIndex: 100,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 101,
          height,
          animation: "sheetUp 320ms var(--ease-out) both",
        }}
      >
        <div
          style={{
            background: "rgba(255,252,246,0.92)",
            backdropFilter: "blur(32px) saturate(160%)",
            WebkitBackdropFilter: "blur(32px) saturate(160%)",
            borderTopLeftRadius: 28,
            borderTopRightRadius: 28,
            borderTop: "1px solid rgba(255,255,255,0.7)",
            padding: `6px 0 ${paddingBottom}px`,
            boxShadow: "0 -8px 30px rgba(60,40,25,0.12), 0 1px 0 rgba(255,255,255,0.6) inset",
          }}
        >
          <div style={{ display: "flex", justifyContent: "center", padding: "6px 0 10px" }}>
            <div style={{ width: 38, height: 4, borderRadius: 999, background: "var(--border-strong, #C9C0AC)" }} />
          </div>
          {children}
        </div>
      </div>
    </>
  );
}

export function SheetTitle({ title, right }: { title: ReactNode; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "4px 20px 14px" }}>
      <h3 style={{ fontSize: 20, fontWeight: 500, letterSpacing: "-0.025em", color: "var(--fg-1)", margin: 0 }}>{title}</h3>
      {right && (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-3)", letterSpacing: ".06em", fontWeight: 500 }}>
          {right}
        </span>
      )}
    </div>
  );
}

export interface SheetTarget {
  id: string;
  title: string;
  src: string;
  letter: string;
}

/* ── ActionSheet — long-press on bookmark ─────────────────── */
export function ActionSheet({
  target,
  onDismiss,
  onRemind,
  onStar,
  onMove,
  onDelete,
}: {
  target: SheetTarget;
  onDismiss?: () => void;
  onRemind?: () => void;
  onStar?: () => void;
  onMove?: () => void;
  onDelete?: () => void;
}) {
  const items = [
    { id: "remind", icon: ExtraIcons.clock, label: "напомнить", sub: "выбрать время", on: onRemind },
    { id: "star", glyph: "★", label: "в избранное", sub: null, on: onStar },
    { id: "space", icon: ExtraIcons.folder, label: "в пространство", sub: "выбрать", on: onMove },
    { id: "del", icon: ExtraIcons.trash, label: "удалить", sub: null, danger: true, on: onDelete },
  ] as const;
  return (
    <BottomSheet onDismiss={onDismiss}>
      <div
        style={{
          margin: "0 16px 6px",
          padding: "10px 14px",
          background: "rgba(234,227,207,0.45)",
          border: "1px solid var(--border-1)",
          borderRadius: 14,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #8FA888 0%, #4A6648 100%)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--font-ui)",
            fontWeight: 500,
            fontSize: 13,
          }}
        >
          {target.letter}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: "var(--fg-1)",
              letterSpacing: "-0.01em",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {target.title}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--fg-3)", letterSpacing: ".06em" }}>
            {target.src}
          </div>
        </div>
      </div>

      <div style={{ padding: "4px 6px 4px" }}>
        {items.map((it) => (
          <button
            key={it.id}
            onClick={it.on}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              width: "100%",
              padding: "12px 14px",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "danger" in it && it.danger ? "var(--semantic-error, #8A2A20)" : "var(--fg-1)",
              textAlign: "left",
            }}
          >
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 10,
                background: "danger" in it && it.danger ? "rgba(138,42,32,0.08)" : "rgba(234,227,207,0.55)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "danger" in it && it.danger ? "var(--semantic-error, #8A2A20)" : "var(--brand-primary-press)",
                flexShrink: 0,
              }}
            >
              {"glyph" in it && it.glyph ? (
                <Glyph ch={it.glyph} size={18} color="currentColor" />
              ) : (
                cloneElement((it as { icon: React.ReactElement }).icon, { size: 18, sw: 1.6 } as never)
              )}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 500, letterSpacing: "-0.01em" }}>{it.label}</div>
              {it.sub && (
                <div
                  style={{
                    fontFamily: "var(--font-display)",
                    fontStyle: "italic",
                    fontSize: 12.5,
                    color: "var(--fg-3)",
                    letterSpacing: 0,
                    marginTop: 2,
                  }}
                >
                  {it.sub}
                </div>
              )}
            </span>
          </button>
        ))}
      </div>
    </BottomSheet>
  );
}

/* ── RemindersSheet — grouped reminders list ────────────── */
export interface ReminderRowData {
  id: string;
  avatar: React.ComponentProps<typeof Avatar>;
  name: string;
  time: string;
  preview: string;
}

export function RemindersSheet({
  groups,
  onDismiss,
  onSnooze,
  onCancel,
}: {
  groups: { label: string; rows: ReminderRowData[] }[];
  onDismiss?: () => void;
  onSnooze?: (id: string) => void;
  onCancel?: (id: string) => void;
}) {
  const total = groups.reduce((s, g) => s + g.rows.length, 0);
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="напоминания" right={total > 0 ? String(total) : undefined} />
      {groups.length === 0 && (
        <div
          style={{
            padding: "20px 20px 28px",
            textAlign: "center",
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontSize: 14,
            color: "var(--fg-3)",
          }}
        >
          напоминаний пока нет
        </div>
      )}
      {groups.map((g) => (
        <div key={g.label} style={{ marginBottom: 10 }}>
          <div
            style={{
              padding: "0 20px 4px",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "var(--brand-primary-press)",
              fontWeight: 500,
            }}
          >
            {g.label}
          </div>
          <div>
            {g.rows.map((r, i) => (
              <ReminderRow
                key={r.id}
                {...r}
                isLast={i === g.rows.length - 1}
                onSnooze={() => onSnooze?.(r.id)}
                onCancel={() => onCancel?.(r.id)}
              />
            ))}
          </div>
        </div>
      ))}
    </BottomSheet>
  );
}

function ReminderRow({
  avatar,
  name,
  time,
  preview,
  isLast,
  onSnooze,
  onCancel,
}: ReminderRowData & { isLast?: boolean; onSnooze?: () => void; onCancel?: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", cursor: "pointer", position: "relative" }}>
      {!isLast && (
        <span style={{ position: "absolute", left: 70, right: 16, bottom: 0, borderBottom: "0.5px solid var(--border-1)" }} />
      )}
      <Avatar {...avatar} size={38} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: "var(--fg-1)",
              letterSpacing: "-0.01em",
              flex: 1,
              minWidth: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {name}
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--brand-primary)", letterSpacing: ".04em", fontWeight: 500 }}>
            {time}
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--fg-2)",
            lineHeight: 1.35,
            marginTop: 1,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {preview}
        </div>
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <button
          aria-label="отложить"
          onClick={onSnooze}
          style={{
            width: 32,
            height: 32,
            borderRadius: 10,
            background: "rgba(255,252,246,0.7)",
            border: "1px solid rgba(255,255,255,0.6)",
            color: "var(--fg-3)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {cloneElement(ExtraIcons.clock, { size: 14, sw: 1.6 } as never)}
        </button>
        <button
          aria-label="отменить"
          onClick={onCancel}
          style={{
            width: 32,
            height: 32,
            borderRadius: 10,
            background: "transparent",
            border: "1px solid transparent",
            color: "var(--fg-4)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {cloneElement(Icons.close, { size: 13, sw: 1.6 } as never)}
        </button>
      </div>
    </div>
  );
}

/* ── ReminderPickerSheet — quick slot pills ─────────────── */
const SLOTS = [
  { id: "tonight", label: "сегодня вечером", sub: "в 18:00", hours: 0, at: [18, 0] },
  { id: "morning", label: "завтра утром", sub: "в 9:00", hours: 24, at: [9, 0] },
  { id: "weekend", label: "на выходные", sub: "сб, 10:00", hours: -1, at: [10, 0] },
  { id: "week", label: "через неделю", sub: "пт, 9:00", hours: 168, at: [9, 0] },
] as const;

function slotToISO(id: string): string {
  const now = new Date();
  const d = new Date(now);
  if (id === "tonight") {
    d.setHours(18, 0, 0, 0);
    if (d <= now) d.setDate(d.getDate() + 1);
  } else if (id === "morning") {
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
  } else if (id === "weekend") {
    const day = d.getDay();
    const toSat = (6 - day + 7) % 7 || 7;
    d.setDate(d.getDate() + toSat);
    d.setHours(10, 0, 0, 0);
  } else {
    d.setDate(d.getDate() + 7);
    d.setHours(9, 0, 0, 0);
  }
  return d.toISOString();
}

export function ReminderPickerSheet({
  contextText,
  onDismiss,
  onConfirm,
}: {
  contextText: string;
  onDismiss?: () => void;
  onConfirm?: (fireAtISO: string) => void;
}) {
  const [picked, setPicked] = useState<string>("tonight");
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="напомнить" />
      <div
        style={{
          margin: "0 16px 10px",
          padding: "10px 14px",
          background: "rgba(234,227,207,0.45)",
          border: "1px solid var(--border-1)",
          borderRadius: 14,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <Glyph ch="✦" size={20} />
        <span
          style={{
            flex: 1,
            fontFamily: "var(--font-display)",
            fontStyle: "italic",
            fontWeight: 400,
            fontSize: 13.5,
            color: "var(--fg-2)",
            lineHeight: 1.35,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          «{contextText}»
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "0 16px" }}>
        {SLOTS.map((s) => {
          const on = picked === s.id;
          return (
            <button
              key={s.id}
              onClick={() => setPicked(s.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "13px 16px",
                background: on ? "var(--brand-primary-tint)" : "rgba(255,252,246,0.7)",
                border: on ? "1px solid rgba(122,156,122,0.45)" : "1px solid rgba(255,255,255,0.6)",
                borderRadius: 14,
                cursor: "pointer",
                textAlign: "left",
                color: "var(--fg-1)",
              }}
            >
              <span
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  border: on ? "none" : "1.5px solid var(--border-strong)",
                  background: on ? "var(--brand-primary)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--fg-on-brand)",
                  flexShrink: 0,
                }}
              >
                {on && cloneElement(Icons.check, { size: 11, sw: 2.5 } as never)}
              </span>
              <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: "-0.01em" }}>{s.label}</span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: on ? "var(--brand-primary-press)" : "var(--fg-3)",
                  letterSpacing: ".04em",
                }}
              >
                {s.sub}
              </span>
            </button>
          );
        })}
      </div>

      <div style={{ padding: "16px 16px 0" }}>
        <TelegramMainButton label="напомнить" enabled onClick={() => onConfirm?.(slotToISO(picked))} />
      </div>
    </BottomSheet>
  );
}

/* ── MoveToSpaceSheet ──────────────────────────────────── */
export interface SpaceOption {
  id: string;
  name: string;
  count: number;
  glyph?: string;
}

export function MoveToSpaceSheet({
  spaces,
  onDismiss,
  onPick,
  onCreate,
}: {
  spaces: SpaceOption[];
  onDismiss?: () => void;
  onPick?: (id: string) => void;
  onCreate?: () => void;
}) {
  const [picked, setPicked] = useState<string>("");
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="в пространство" />
      <div style={{ padding: "0 12px" }}>
        {spaces.slice(0, 6).map((s) => {
          const on = picked === s.id;
          return (
            <button
              key={s.id}
              onClick={() => {
                setPicked(s.id);
                onPick?.(s.id);
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                width: "100%",
                padding: "10px 12px",
                background: on ? "var(--brand-primary-tint)" : "transparent",
                border: "1px solid " + (on ? "rgba(122,156,122,0.35)" : "transparent"),
                borderRadius: 12,
                cursor: "pointer",
                textAlign: "left",
                marginBottom: 2,
              }}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 10,
                  background: "linear-gradient(135deg, rgba(143,168,136,0.7), rgba(74,102,72,0.7))",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Glyph ch={s.glyph || "·"} size={16} color="currentColor" />
              </div>
              <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: "-0.01em", color: "var(--fg-1)" }}>
                {s.name}
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--fg-3)", letterSpacing: ".06em" }}>
                {s.count}
              </span>
              {on && (
                <span style={{ color: "var(--brand-primary)", display: "flex" }}>
                  {cloneElement(Icons.check, { size: 16, sw: 2.2 } as never)}
                </span>
              )}
            </button>
          );
        })}
        <button
          onClick={onCreate}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            width: "100%",
            padding: "10px 12px",
            marginTop: 4,
            background: "transparent",
            border: "1px dashed var(--border-strong)",
            borderRadius: 12,
            cursor: "pointer",
            textAlign: "left",
            color: "var(--brand-primary)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 10,
              background: "rgba(255,252,246,0.7)",
              border: "1px solid var(--border-2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {cloneElement(Icons.plus, { size: 16, sw: 1.8 } as never)}
          </div>
          <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: "-0.01em" }}>создать пространство</span>
        </button>
      </div>
    </BottomSheet>
  );
}

/* ── QuickCreateSheet — FAB+ (functional) ──────────────── */
export function QuickCreateSheet({
  onDismiss,
  onSave,
}: {
  onDismiss?: () => void;
  onSave?: (text: string) => void | Promise<void>;
}) {
  const [v, setV] = useState("");
  const [saving, setSaving] = useState(false);
  const enabled = v.trim().length > 0 && !saving;

  const save = async () => {
    if (!enabled) return;
    setSaving(true);
    try {
      await onSave?.(v.trim());
    } finally {
      setSaving(false);
    }
  };

  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="новая мысль" right="бот разберёт сам" />

      <div style={{ padding: "0 16px" }}>
        <div
          style={{
            background: "rgba(255,252,246,0.85)",
            border: "1px solid rgba(255,255,255,0.7)",
            borderRadius: 18,
            padding: "14px 16px",
            boxShadow: "0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 12px rgba(60,40,25,0.05)",
            minHeight: 110,
            position: "relative",
          }}
        >
          {!v && (
            <span
              style={{
                position: "absolute",
                fontFamily: "var(--font-display)",
                fontStyle: "italic",
                fontSize: 16,
                color: "var(--fg-3)",
                lineHeight: 1.4,
                letterSpacing: 0,
                pointerEvents: "none",
              }}
            >
              пиши мысль · вставь ссылку · бот разберёт сам
            </span>
          )}
          <textarea
            value={v}
            onChange={(e) => setV(e.target.value)}
            autoFocus
            rows={3}
            style={{
              width: "100%",
              border: "none",
              outline: "none",
              resize: "none",
              background: "transparent",
              font: "inherit",
              fontSize: 16,
              color: "var(--fg-1)",
              lineHeight: 1.4,
              letterSpacing: "-0.005em",
            }}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 4px 6px" }}>
          <button
            aria-label="вложение"
            disabled
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              background: "rgba(234,227,207,0.4)",
              border: "1px solid var(--border-1)",
              color: "var(--fg-4)",
              cursor: "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {cloneElement(ExtraIcons.paperclip, { size: 16, sw: 1.6 } as never)}
          </button>
          <button
            aria-label="голос"
            disabled
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              background: "rgba(234,227,207,0.4)",
              border: "1px solid var(--border-1)",
              color: "var(--fg-4)",
              cursor: "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {cloneElement(ExtraIcons.mic, { size: 16, sw: 1.6 } as never)}
          </button>
          <span
            style={{
              flex: 1,
              fontFamily: "var(--font-display)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--fg-3)",
              letterSpacing: 0,
            }}
          >
            вложения — в боте
          </span>
        </div>

        <div style={{ marginTop: 8 }}>
          <TelegramMainButton label={saving ? "сохраняю…" : "сохранить"} enabled={enabled} onClick={save} />
        </div>
      </div>
    </BottomSheet>
  );
}

export function TelegramMainButton({
  label,
  enabled,
  onClick,
}: {
  label: string;
  enabled: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      disabled={!enabled}
      onClick={onClick}
      style={{
        width: "100%",
        padding: "14px 18px",
        borderRadius: 14,
        background: enabled ? "var(--brand-primary)" : "rgba(122,156,122,0.35)",
        color: "var(--fg-on-brand)",
        border: "none",
        fontFamily: "var(--font-ui)",
        fontSize: 15,
        fontWeight: 500,
        letterSpacing: "-0.005em",
        cursor: enabled ? "pointer" : "not-allowed",
        boxShadow: enabled
          ? "0 1px 0 rgba(255,255,255,0.2) inset, 0 4px 12px rgba(122,156,122,0.25)"
          : "none",
      }}
    >
      {label}
    </button>
  );
}
