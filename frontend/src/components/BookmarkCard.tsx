import { useNavigate } from "react-router-dom";
import type { Bookmark } from "../lib/api";
import { TaskListView } from "./TaskListView";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    year: d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

export function BookmarkCard({ bookmark }: { bookmark: Bookmark }) {
  const navigate = useNavigate();
  const title = bookmark.title || bookmark.raw_text.slice(0, 60);
  const rawSummary = bookmark.summary || bookmark.raw_text.slice(0, 120);

  // Не показываем summary если оно совпадает с title
  const showSummary =
    rawSummary && !title.startsWith(rawSummary.slice(0, 30)) && rawSummary.slice(0, 30) !== title.slice(0, 30);

  const isTaskList =
    bookmark.structured_data?.type === "task_list" &&
    bookmark.structured_data.tasks.length > 0;

  return (
    <div className="card" onClick={() => navigate(`/bookmark/${bookmark.id}`)}>
      <div className="card-header">
        <div className="card-title">
          {isTaskList && <span className="card-icon">{"\u{1F4CB}"}</span>}
          {title}
        </div>
        <span className="card-date">{formatDate(bookmark.created_at)}</span>
      </div>

      {isTaskList && bookmark.structured_data && (
        <TaskListView
          bookmarkId={bookmark.id}
          data={bookmark.structured_data}
        />
      )}

      {!isTaskList && showSummary && (
        <div className="card-summary">{rawSummary}</div>
      )}

      <div className="card-footer">
        <div className="tags">
          {bookmark.category && (
            <span className="tag tag-accent">{bookmark.category}</span>
          )}
          {bookmark.tags.slice(0, 3).map((tag) => (
            <span className="tag" key={tag.id}>
              {tag.name}
            </span>
          ))}
        </div>

        {bookmark.ai_status !== "completed" && (
          <span className={`status status-${bookmark.ai_status}`}>
            {bookmark.ai_status === "processing" && "\u23F3 Обработка..."}
            {bookmark.ai_status === "pending" && "\u{1F552} В очереди"}
            {bookmark.ai_status === "failed" && "\u26A0 Ошибка"}
          </span>
        )}
      </div>
    </div>
  );
}
