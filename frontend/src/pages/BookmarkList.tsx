import { useEffect, useState, useCallback } from "react";
import { api, type Bookmark } from "../lib/api";
import { BookmarkCard } from "../components/BookmarkCard";

export function BookmarkListPage() {
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const perPage = 20;

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getBookmarks(p, perPage);
      setBookmarks(data.items);
      setTotal(data.total);
      setPage(p);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(1);
  }, [load]);

  const totalPages = Math.ceil(total / perPage);

  if (loading && bookmarks.length === 0) {
    return (
      <>
        <div className="page-header">
          <div>
            <div className="page-title">Закладки</div>
          </div>
        </div>
        <div className="loading-center">
          <div className="spinner" />
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <div className="page-header">
          <div className="page-title">Закладки</div>
        </div>
        <div className="empty-state">
          <div className="empty-state-icon">{"\u26A0\uFE0F"}</div>
          <div className="empty-state-text">{error}</div>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => load(1)}>
            Попробовать снова
          </button>
        </div>
      </>
    );
  }

  if (bookmarks.length === 0) {
    return (
      <>
        <div className="page-header">
          <div className="page-title">Закладки</div>
        </div>
        <div className="empty-state">
          <div className="empty-state-icon">{"\u{1F4DA}"}</div>
          <div className="empty-state-text">
            Пока нет закладок.
            <br />
            Перешли сообщение боту — и оно появится здесь.
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Закладки</div>
          <div className="page-subtitle">{total} сохранено</div>
        </div>
      </div>

      {bookmarks.map((b) => (
        <BookmarkCard key={b.id} bookmark={b} />
      ))}

      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
          <button
            className="btn btn-secondary"
            disabled={page <= 1}
            onClick={() => load(page - 1)}
          >
            {"\u2190"}
          </button>
          <span style={{ alignSelf: "center", fontSize: 14, color: "var(--color-text-secondary)" }}>
            {page} / {totalPages}
          </span>
          <button
            className="btn btn-secondary"
            disabled={page >= totalPages}
            onClick={() => load(page + 1)}
          >
            {"\u2192"}
          </button>
        </div>
      )}
    </>
  );
}
