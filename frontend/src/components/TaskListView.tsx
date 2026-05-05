import { useState } from "react";
import { api, type TaskListData } from "../lib/api";

interface Props {
  bookmarkId: string;
  data: TaskListData;
  /** Опциональный колбек если родитель хочет синхронизировать состояние */
  onChange?: (next: TaskListData) => void;
}

function formatDeadline(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    if (d.getHours() === 0 && d.getMinutes() === 0) return `${dd}.${mm}`;
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${dd}.${mm} ${hh}:${mi}`;
  } catch {
    return "";
  }
}

/**
 * Интерактивный task_list — клик по чекбоксу переключает done.
 * Обновляет через PATCH /api/v1/bookmarks/{id} без перезагрузки страницы.
 */
export function TaskListView({ bookmarkId, data, onChange }: Props) {
  const [local, setLocal] = useState<TaskListData>(data);
  const [saving, setSaving] = useState(false);

  const total = local.tasks.length;
  const done = local.tasks.filter((t) => t.done).length;

  const toggle = async (idx: number) => {
    // Optimistic update
    const next: TaskListData = {
      ...local,
      tasks: local.tasks.map((t, i) =>
        i === idx ? { ...t, done: !t.done } : t
      ),
    };
    setLocal(next);
    onChange?.(next);

    setSaving(true);
    try {
      await api.updateBookmark(bookmarkId, { structured_data: next });
    } catch {
      // Rollback при ошибке
      setLocal(local);
      onChange?.(local);
    } finally {
      setSaving(false);
    }
  };

  if (!local.tasks.length) return null;

  return (
    <div className="task-list" onClick={(e) => e.stopPropagation()}>
      <div className="task-list-header">
        <span className="task-list-icon">{"\u{1F4CB}"}</span>
        <span className="task-list-progress">
          {done} из {total}
        </span>
        {saving && <span className="task-list-saving">…</span>}
      </div>
      <ul className="task-list-items">
        {local.tasks.map((t, i) => (
          <li
            key={i}
            className={`task-item ${t.done ? "task-item-done" : ""}`}
            onClick={() => toggle(i)}
          >
            <span className="task-check">{t.done ? "\u2705" : "\u2610"}</span>
            <span className="task-text">{t.text}</span>
            {t.deadline && (
              <span className="task-deadline">{`\u23F0 ${formatDeadline(t.deadline)}`}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
