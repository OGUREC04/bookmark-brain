import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type Bookmark, type Folder } from "../lib/api";
import { BookmarkCard } from "../components/BookmarkCard";
import { getTelegramWebApp } from "../lib/telegram";

export function FolderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [folder, setFolder] = useState<Folder | null>(null);
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const perPage = 20;

  const load = useCallback(
    async (p: number) => {
      if (!id) return;
      setLoading(true);
      try {
        const [folderData, bData] = await Promise.all([
          api.getFolders().then((fs) => fs.find((f) => f.id === id) || null),
          api.getFolderBookmarks(id, p, perPage),
        ]);
        setFolder(folderData);
        setBookmarks(bData.items);
        setTotal(bData.total);
        setPage(p);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    },
    [id]
  );

  useEffect(() => {
    load(1);
  }, [load]);

  // Telegram back button
  useEffect(() => {
    const app = getTelegramWebApp();
    if (!app) return;
    const goBack = () => navigate("/folders");
    app.BackButton.show();
    app.BackButton.onClick(goBack);
    return () => {
      app.BackButton.hide();
      app.BackButton.offClick(goBack);
    };
  }, [navigate]);

  const handleRemove = async (bookmarkId: string) => {
    if (!id) return;
    try {
      await api.removeBookmarkFromFolder(id, bookmarkId);
      setBookmarks((prev) => prev.filter((b) => b.id !== bookmarkId));
      setTotal((t) => t - 1);
    } catch {
      /* ignore */
    }
  };

  const totalPages = Math.ceil(total / perPage);

  if (loading && bookmarks.length === 0) {
    return (
      <div className="loading-center">
        <div className="spinner" />
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">
            {folder?.emoji || "\u{1F4C1}"} {folder?.name || "Папка"}
          </div>
          <div className="page-subtitle">{total} закладок</div>
        </div>
      </div>

      {bookmarks.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">{"\u{1F4C2}"}</div>
          <div className="empty-state-text">
            Папка пуста.
            <br />
            Добавь закладки из карточки закладки.
          </div>
        </div>
      )}

      {bookmarks.map((b) => (
        <div key={b.id} style={{ position: "relative" }}>
          <BookmarkCard bookmark={b} />
          <button
            className="folder-remove-btn"
            onClick={(e) => {
              e.stopPropagation();
              handleRemove(b.id);
            }}
            title="Убрать из папки"
          >
            {"\u2715"}
          </button>
        </div>
      ))}

      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
          <button className="btn btn-secondary" disabled={page <= 1} onClick={() => load(page - 1)}>
            {"\u2190"}
          </button>
          <span style={{ alignSelf: "center", fontSize: 14, color: "var(--color-text-secondary)" }}>
            {page} / {totalPages}
          </span>
          <button className="btn btn-secondary" disabled={page >= totalPages} onClick={() => load(page + 1)}>
            {"\u2192"}
          </button>
        </div>
      )}
    </>
  );
}
