import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type Bookmark, type Folder } from "../lib/api";
import { getTelegramWebApp } from "../lib/telegram";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function BookmarkDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [bookmark, setBookmark] = useState<Bookmark | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [showFolderPicker, setShowFolderPicker] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([api.getBookmark(id), api.getFolders()])
      .then(([b, f]) => {
        setBookmark(b);
        setFolders(f);
      })
      .finally(() => setLoading(false));
  }, [id]);

  // Telegram back button
  useEffect(() => {
    const app = getTelegramWebApp();
    if (!app) return;
    const goBack = () => navigate(-1);
    app.BackButton.show();
    app.BackButton.onClick(goBack);
    return () => {
      app.BackButton.hide();
      app.BackButton.offClick(goBack);
    };
  }, [navigate]);

  const handleFavorite = useCallback(async () => {
    if (!bookmark) return;
    const updated = await api.toggleFavorite(bookmark.id, !bookmark.is_favorite);
    setBookmark(updated);
    getTelegramWebApp()?.HapticFeedback.impactOccurred("light");
  }, [bookmark]);

  const handleDelete = useCallback(async () => {
    if (!bookmark || deleting) return;
    setDeleting(true);
    try {
      await api.deleteBookmark(bookmark.id);
      getTelegramWebApp()?.HapticFeedback.notificationOccurred("success");
      navigate("/", { replace: true });
    } catch {
      setDeleting(false);
    }
  }, [bookmark, deleting, navigate]);

  const handleMoveToFolder = async (folderId: string) => {
    if (!bookmark) return;
    try {
      await api.addBookmarkToFolder(folderId, bookmark.id);
      setBookmark({ ...bookmark, folder_id: folderId });
      setShowFolderPicker(false);
      getTelegramWebApp()?.HapticFeedback.impactOccurred("light");
    } catch {
      /* ignore */
    }
  };

  const handleRemoveFromFolder = async () => {
    if (!bookmark || !bookmark.folder_id) return;
    try {
      await api.removeBookmarkFromFolder(bookmark.folder_id, bookmark.id);
      setBookmark({ ...bookmark, folder_id: null });
      getTelegramWebApp()?.HapticFeedback.impactOccurred("light");
    } catch {
      /* ignore */
    }
  };

  const currentFolder = folders.find((f) => f.id === bookmark?.folder_id);

  if (loading) {
    return (
      <div className="loading-center">
        <div className="spinner" />
      </div>
    );
  }

  if (!bookmark) {
    return (
      <div className="empty-state">
        <div className="empty-state-text">Закладка не найдена</div>
      </div>
    );
  }

  return (
    <>
      <div className="detail-header">
        {bookmark.category && (
          <span className="detail-category">{bookmark.category}</span>
        )}
        <div className="detail-title" style={{ marginTop: bookmark.category ? 8 : 0 }}>
          {bookmark.title || bookmark.raw_text.slice(0, 80)}
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 4 }}>
          {formatDate(bookmark.created_at)}
        </div>
      </div>

      {bookmark.summary && (
        <div className="detail-section">
          <div className="detail-section-title">Саммари</div>
          <div className="detail-text">{bookmark.summary}</div>
        </div>
      )}

      {bookmark.tags.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">Теги</div>
          <div className="tags">
            {bookmark.tags.map((tag) => (
              <span className="tag tag-accent" key={tag.id}>
                {tag.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Folder section */}
      <div className="detail-section">
        <div className="detail-section-title">Папка</div>
        {currentFolder ? (
          <div className="folder-badge">
            <span>{currentFolder.emoji || "\u{1F4C1}"} {currentFolder.name}</span>
            <button className="btn-icon" onClick={handleRemoveFromFolder} title="Убрать из папки">
              {"\u2715"}
            </button>
          </div>
        ) : (
          <button
            className="btn btn-secondary"
            onClick={() => setShowFolderPicker(!showFolderPicker)}
            style={{ width: "100%" }}
          >
            {"\u{1F4C2}"} Добавить в папку
          </button>
        )}
        {showFolderPicker && (
          <div className="folder-picker">
            {folders.length === 0 ? (
              <div style={{ padding: 12, color: "var(--color-text-tertiary)", fontSize: 13 }}>
                Нет папок. Создай в разделе "Папки".
              </div>
            ) : (
              folders.map((f) => (
                <button
                  key={f.id}
                  className="folder-picker-item"
                  onClick={() => handleMoveToFolder(f.id)}
                >
                  <span>{f.emoji || "\u{1F4C1}"}</span>
                  <span>{f.name}</span>
                  <span style={{ color: "var(--color-text-tertiary)", fontSize: 12 }}>
                    {f.bookmarks_count}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      <div className="detail-section">
        <div className="detail-section-title">Оригинал</div>
        <div className="detail-text">{bookmark.raw_text}</div>
      </div>

      {bookmark.url && (
        <div className="detail-section">
          <div className="detail-section-title">Ссылка</div>
          <a
            className="detail-link"
            href={bookmark.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {"\u{1F517}"} {bookmark.url}
          </a>
        </div>
      )}

      {bookmark.ai_status !== "completed" && (
        <div className="detail-section">
          <span className={`status status-${bookmark.ai_status}`}>
            {bookmark.ai_status === "processing" && "AI обрабатывает..."}
            {bookmark.ai_status === "pending" && "В очереди на обработку"}
            {bookmark.ai_status === "failed" && "Ошибка AI-обработки"}
          </span>
        </div>
      )}

      <div className="detail-actions">
        <button
          className={`btn ${bookmark.is_favorite ? "btn-primary" : "btn-secondary"}`}
          onClick={handleFavorite}
          style={{ flex: 1 }}
        >
          {bookmark.is_favorite ? "\u2605 В избранном" : "\u2606 В избранное"}
        </button>
        <button
          className="btn btn-danger"
          onClick={handleDelete}
          disabled={deleting}
          style={{ flex: 1 }}
        >
          {deleting ? "Удаление..." : "\u{1F5D1} Удалить"}
        </button>
      </div>
    </>
  );
}
