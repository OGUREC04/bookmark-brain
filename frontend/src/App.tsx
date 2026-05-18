/* Mini App shell — state-driven, DS-faithful (no router; one frame + sheets).
   Ported IA from docs/design-system-miniapp. */
import { useCallback, useEffect, useState } from "react";
import { BottomNav, type NavTab } from "./components/ds/Nav";
import { MysliScreen } from "./screens/Mysli";
import { SearchScreen } from "./screens/SearchScreen";
import { SpacesScreen } from "./screens/SpacesScreen";
import { MeScreen } from "./screens/MeScreen";
import { DetailScreen } from "./screens/DetailScreen";
import {
  ActionSheet,
  RemindersSheet,
  ReminderPickerSheet,
  MoveToSpaceSheet,
  QuickCreateSheet,
  type SheetTarget,
  type SpaceOption,
} from "./components/ds/Sheets";
import { api, type Bookmark, type Folder } from "./lib/api";
import { targetOf, groupReminders } from "./lib/adapters";
import { hapticImpact, hapticNotify, getBackButton } from "./lib/telegram";

type Sheet =
  | { type: "action"; target: SheetTarget; bookmark: Bookmark }
  | { type: "reminders" }
  | { type: "reminderPicker"; bookmark: Bookmark }
  | { type: "moveToSpace"; bookmark: Bookmark }
  | { type: "quickCreate" }
  | null;

export function App() {
  const [tab, setTab] = useState<NavTab>("mysli");
  const [searchOpen, setSearchOpen] = useState(false);
  const [detail, setDetail] = useState<Bookmark | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // "В разработке" stub for actions without backend yet.
  const comingSoon = useCallback(() => {
    hapticImpact("light");
    setToast("в разработке");
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 1800);
    return () => clearTimeout(t);
  }, [toast]);

  const [reminders, setReminders] = useState<
    { id: string; fire_at: string; bookmark_title: string | null; bookmark_raw_text: string | null }[]
  >([]);
  const [folders, setFolders] = useState<Folder[]>([]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const closeSheet = useCallback(() => setSheet(null), []);

  /**
   * Runs a mutating API action with uniform error handling: on success →
   * success haptic; on failure → error haptic (the sheet stays open so the
   * user can retry). Without this every handler swallowed rejections and
   * left the UI silently stuck (flagged by code review).
   */
  const runAction = useCallback(async (fn: () => Promise<void>) => {
    try {
      await fn();
      hapticNotify("success");
    } catch {
      hapticNotify("error");
    }
  }, []);

  // Lazily load reminders / folders when a sheet needs them (race-guarded).
  useEffect(() => {
    let alive = true;
    if (sheet?.type === "reminders") {
      api.reminders
        .upcoming(50)
        .then((r) => alive && setReminders(r.items))
        .catch(() => alive && setReminders([]));
    }
    if (sheet?.type === "moveToSpace") {
      api.getFolders()
        .then((f) => alive && setFolders(f))
        .catch(() => alive && setFolders([]));
    }
    return () => {
      alive = false;
    };
  }, [sheet]);

  // Telegram BackButton: native back closes search / any open sheet.
  useEffect(() => {
    const back = getBackButton();
    if (!back) return;
    const overlayOpen = searchOpen || detail !== null || sheet !== null;
    if (overlayOpen) {
      back.show();
      const onBack = () => {
        if (sheet !== null) setSheet(null);
        else if (detail !== null) setDetail(null);
        else setSearchOpen(false);
      };
      back.onClick(onBack);
      return () => {
        back.offClick(onBack);
        back.hide();
      };
    }
    back.hide();
  }, [searchOpen, detail, sheet]);

  const openActions = useCallback((b: Bookmark) => {
    hapticImpact("medium");
    setSheet({ type: "action", target: targetOf(b), bookmark: b });
  }, []);

  const openDetail = useCallback((b: Bookmark) => {
    hapticImpact("light");
    setDetail(b);
  }, []);

  return (
    <div
      style={{
        position: "relative",
        minHeight: "100vh",
        overflowX: "hidden",
      }}
      className="app-shell"
    >
      <div key={detail ? `d-${detail.id}` : searchOpen ? "search" : tab} className="screen-fade">
        {detail ? (
          <DetailScreen bookmark={detail} onBack={() => setDetail(null)} onMore={() => openActions(detail)} />
        ) : searchOpen ? (
          <SearchScreen onBack={() => setSearchOpen(false)} onOpen={comingSoon} />
        ) : tab === "mysli" ? (
          <MysliScreen
            reloadKey={reloadKey}
            onSearch={() => setSearchOpen(true)}
            onBell={() => setSheet({ type: "reminders" })}
            onMore={openActions}
            onOpen={openDetail}
          />
        ) : tab === "spaces" ? (
          <SpacesScreen onOpen={comingSoon} onCreate={comingSoon} />
        ) : (
          <MeScreen onComingSoon={comingSoon} />
        )}
      </div>

      {!searchOpen && !detail && (
        <BottomNav
          current={tab}
          onChange={(t) => {
            hapticImpact("light");
            setTab(t);
          }}
          onFab={() => {
            hapticImpact("light");
            setSheet({ type: "quickCreate" });
          }}
        />
      )}

      {sheet?.type === "action" && (
        <ActionSheet
          target={sheet.target}
          onDismiss={closeSheet}
          onRemind={() => setSheet({ type: "reminderPicker", bookmark: sheet.bookmark })}
          onStar={() =>
            runAction(async () => {
              await api.toggleFavorite(sheet.bookmark.id, !sheet.bookmark.is_favorite);
              closeSheet();
              reload();
            })
          }
          onMove={() => setSheet({ type: "moveToSpace", bookmark: sheet.bookmark })}
          onDelete={() =>
            runAction(async () => {
              await api.deleteBookmark(sheet.bookmark.id);
              closeSheet();
              reload();
            })
          }
        />
      )}

      {sheet?.type === "reminders" && (
        <RemindersSheet
          groups={groupReminders(reminders)}
          onDismiss={closeSheet}
          onCancel={(id) =>
            runAction(async () => {
              await api.reminders.cancel(id);
              const r = await api.reminders.upcoming(50);
              setReminders(r.items);
              reload();
            })
          }
          onSnooze={(id) =>
            runAction(async () => {
              const next = new Date(Date.now() + 3600_000).toISOString();
              await api.reminders.snooze(id, next);
              const r = await api.reminders.upcoming(50);
              setReminders(r.items);
              reload();
            })
          }
        />
      )}

      {sheet?.type === "reminderPicker" && (
        <ReminderPickerSheet
          contextText={sheet.bookmark.title || (sheet.bookmark.raw_text ?? "").slice(0, 60) || "без названия"}
          onDismiss={closeSheet}
          onConfirm={(iso) =>
            runAction(async () => {
              await api.reminders.create(sheet.bookmark.id, iso);
              closeSheet();
            })
          }
        />
      )}

      {sheet?.type === "moveToSpace" && (
        <MoveToSpaceSheet
          spaces={folders.map<SpaceOption>((f) => ({ id: f.id, name: f.name, count: f.bookmarks_count, glyph: f.emoji || "·" }))}
          onDismiss={closeSheet}
          onPick={(folderId) =>
            runAction(async () => {
              await api.addBookmarkToFolder(folderId, sheet.bookmark.id);
              closeSheet();
              reload();
            })
          }
          onCreate={comingSoon}
        />
      )}

      {sheet?.type === "quickCreate" && (
        <QuickCreateSheet
          onDismiss={closeSheet}
          onSave={(text) =>
            runAction(async () => {
              await api.createThought(text);
              closeSheet();
              reload();
            })
          }
        />
      )}

      {toast && (
        <div
          style={{
            position: "fixed",
            left: "50%",
            top: "calc(16px + env(safe-area-inset-top, 0px))",
            transform: "translateX(-50%)",
            zIndex: 200,
            padding: "10px 18px",
            borderRadius: 999,
            background: "rgba(28,22,18,0.86)",
            color: "#FBF7EC",
            fontFamily: "var(--font-ui)",
            fontSize: 13,
            fontWeight: 500,
            letterSpacing: "-0.005em",
            boxShadow: "0 6px 20px rgba(60,40,25,0.28)",
            animation: "toastIn 200ms var(--ease-out, ease) both",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
