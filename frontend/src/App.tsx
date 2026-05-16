/* Mini App shell — state-driven, DS-faithful (no router; one frame + sheets).
   Ported IA from docs/design-system-miniapp. */
import { useCallback, useEffect, useState } from "react";
import { BottomNav, type NavTab } from "./components/ds/Nav";
import { MysliScreen } from "./screens/Mysli";
import { SearchScreen } from "./screens/SearchScreen";
import { SpacesScreen } from "./screens/SpacesScreen";
import { MeScreen } from "./screens/MeScreen";
import {
  ActionSheet,
  RemindersSheet,
  ReminderPickerSheet,
  MoveToSpaceSheet,
  QuickCreateSheet,
  type SheetTarget,
  type ReminderRowData,
  type SpaceOption,
} from "./components/ds/Sheets";
import { api, type Bookmark, type Folder } from "./lib/api";
import { hostOf } from "./lib/adapters";
import { formatRelativeDate } from "./lib/formatters";
import { hapticImpact, hapticNotify, getBackButton } from "./lib/telegram";

type Sheet =
  | { type: "action"; target: SheetTarget; bookmark: Bookmark }
  | { type: "reminders" }
  | { type: "reminderPicker"; bookmark: Bookmark }
  | { type: "moveToSpace"; bookmark: Bookmark }
  | { type: "quickCreate" }
  | null;

function targetOf(b: Bookmark): SheetTarget {
  const title = b.title || b.raw_text.slice(0, 80);
  return {
    id: b.id,
    title,
    src: b.url ? `${hostOf(b.url)} · ${formatRelativeDate(b.created_at)}` : formatRelativeDate(b.created_at),
    letter: (title.trim()[0] || "·").toUpperCase(),
  };
}

type RemItem = { id: string; fire_at: string; bookmark_title: string | null; bookmark_raw_text: string | null };

function groupReminders(items: RemItem[]): { label: string; rows: ReminderRowData[] }[] {
  const buckets: Record<string, ReminderRowData[]> = { сегодня: [], завтра: [], "на неделе": [], позже: [] };
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  for (const r of items) {
    const d = new Date(r.fire_at);
    const tgt = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((tgt.getTime() - today.getTime()) / 86_400_000);
    const label = diff <= 0 ? "сегодня" : diff === 1 ? "завтра" : diff < 7 ? "на неделе" : "позже";
    buckets[label].push({
      id: r.id,
      avatar: { kind: "letter", letter: ((r.bookmark_title || "·").trim()[0] || "·").toUpperCase() },
      name: r.bookmark_title || "напоминание",
      time: `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`,
      preview: r.bookmark_raw_text || "",
    });
  }
  return Object.entries(buckets)
    .filter(([, rows]) => rows.length > 0)
    .map(([label, rows]) => ({ label, rows }));
}

export function App() {
  const [tab, setTab] = useState<NavTab>("mysli");
  const [searchOpen, setSearchOpen] = useState(false);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [reloadKey, setReloadKey] = useState(0);

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
    const overlayOpen = searchOpen || sheet !== null;
    if (overlayOpen) {
      back.show();
      const onBack = () => {
        if (sheet !== null) setSheet(null);
        else setSearchOpen(false);
      };
      back.onClick(onBack);
      return () => {
        back.offClick(onBack);
        back.hide();
      };
    }
    back.hide();
  }, [searchOpen, sheet]);

  const onLongPress = useCallback((b: Bookmark) => {
    hapticImpact("medium");
    setSheet({ type: "action", target: targetOf(b), bookmark: b });
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
      <div key={searchOpen ? "search" : tab} className="screen-fade">
        {searchOpen ? (
          <SearchScreen onBack={() => setSearchOpen(false)} onOpen={() => {}} />
        ) : tab === "mysli" ? (
          <MysliScreen
            reloadKey={reloadKey}
            onSearch={() => setSearchOpen(true)}
            onBell={() => setSheet({ type: "reminders" })}
            onLongPress={onLongPress}
            onOpen={onLongPress}
          />
        ) : tab === "spaces" ? (
          <SpacesScreen onOpen={() => {}} onCreate={() => {}} />
        ) : (
          <MeScreen />
        )}
      </div>

      {!searchOpen && (
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
          contextText={sheet.bookmark.title || sheet.bookmark.raw_text.slice(0, 60)}
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
          onCreate={() => {}}
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
    </div>
  );
}
