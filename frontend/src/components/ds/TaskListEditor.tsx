/* Интерактивный редактор task-list для DetailScreen.
   PRD: docs/prd/TASK-LIST-EDITING.md
   Итерация US-1: тоггл чекбокса (optimistic + debounce 400мс, revert при ошибке).
   Дальше: US-2 (edit), US-3 (delete+undo), US-4 (add), US-5 (deadline). */
import { useCallback, useEffect, useRef, useState, cloneElement } from "react";
import { Icons } from "./icons";
import { api, type Bookmark, type TaskItem } from "../../lib/api";
import { hapticSelection, hapticNotify } from "../../lib/telegram";

const COMMIT_DEBOUNCE_MS = 400;

function extractTasks(b: Bookmark): TaskItem[] {
  return b.structured_data?.type === "task_list" ? b.structured_data.tasks : [];
}

export function TaskListEditor({
  bookmark,
  onCommitted,
  onError,
}: {
  bookmark: Bookmark;
  /** Вызывается после успешного PATCH — родитель обновляет ленту. */
  onCommitted?: (updated: Bookmark) => void;
  /** Текст для тоста при провале сохранения. */
  onError?: (msg: string) => void;
}) {
  const [tasks, setTasks] = useState<TaskItem[]>(() => extractTasks(bookmark));

  // last-known-good для отката при провале PATCH
  const savedRef = useRef<TaskItem[]>(tasks);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<TaskItem[] | null>(null);
  const aliveRef = useRef(true);

  const commit = useCallback(
    async (next: TaskItem[], silent = false) => {
      pendingRef.current = null;
      try {
        const updated = await api.updateBookmark(bookmark.id, {
          structured_data: { type: "task_list", tasks: next },
        });
        savedRef.current = next;
        onCommitted?.(updated);
      } catch {
        // откат к последнему сохранённому состоянию
        if (!silent && aliveRef.current) setTasks(savedRef.current);
        hapticNotify("error");
        onError?.("не сохранилось");
      }
    },
    [bookmark.id, onCommitted, onError]
  );

  const scheduleCommit = useCallback(
    (next: TaskItem[]) => {
      pendingRef.current = next;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        if (pendingRef.current) void commit(pendingRef.current);
      }, COMMIT_DEBOUNCE_MS);
    },
    [commit]
  );

  // Флаш pending-дебаунса при unmount — не теряем последнее изменение (edge case 12).
  useEffect(() => {
    return () => {
      aliveRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
        if (pendingRef.current) void commit(pendingRef.current, true);
      }
    };
  }, [commit]);

  const toggle = useCallback(
    (index: number) => {
      hapticSelection();
      setTasks((prev) => {
        const next = prev.map((t, i) => (i === index ? { ...t, done: !t.done } : t));
        scheduleCommit(next);
        return next;
      });
    },
    [scheduleCommit]
  );

  if (tasks.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, margin: "0 0 14px" }}>
      {tasks.map((t, i) => (
        <TaskRow key={i} task={t} index={i} onToggle={() => toggle(i)} />
      ))}
    </div>
  );
}

function TaskRow({
  task,
  index,
  onToggle,
}: {
  task: TaskItem;
  index: number;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      role="checkbox"
      aria-checked={task.done}
      aria-label={`пункт ${index + 1}: ${task.text}`}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        width: "100%",
        textAlign: "left",
        background: "transparent",
        border: "none",
        padding: "5px 4px",
        margin: 0,
        borderRadius: 8,
        cursor: "pointer",
        WebkitTapHighlightColor: "transparent",
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: 6,
          flexShrink: 0,
          marginTop: 1,
          border: task.done ? "none" : "1.5px solid var(--border-strong)",
          background: task.done ? "var(--brand-primary)" : "transparent",
          color: "var(--fg-on-brand)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "background 140ms var(--ease-out), border-color 140ms var(--ease-out)",
        }}
      >
        {task.done && cloneElement(Icons.check, { size: 11, sw: 2.5 } as never)}
      </span>
      <span
        style={{
          fontSize: 14.5,
          color: task.done ? "var(--fg-3)" : "var(--fg-1)",
          textDecoration: task.done ? "line-through" : "none",
          lineHeight: 1.4,
        }}
      >
        {task.text}
      </span>
    </button>
  );
}
