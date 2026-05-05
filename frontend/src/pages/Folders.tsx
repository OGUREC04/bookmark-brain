import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Folder } from "../lib/api";

const EMOJI_OPTIONS = ["\u{1F4C1}", "\u{1F4DA}", "\u{1F4BC}", "\u{1F3AF}", "\u{1F4A1}", "\u{2B50}", "\u{1F4DD}", "\u{1F6E0}", "\u{1F3AE}", "\u{1F3B5}", "\u{1F4F0}", "\u{1F30D}"];

export function FoldersPage() {
  const navigate = useNavigate();
  const [folders, setFolders] = useState<Folder[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEmoji, setNewEmoji] = useState("\u{1F4C1}");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getFolders();
      setFolders(data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!newName.trim() || creating) return;
    setCreating(true);
    try {
      await api.createFolder(newName.trim(), newEmoji);
      setNewName("");
      setShowCreate(false);
      load();
    } catch {
      /* ignore */
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.deleteFolder(id);
      setFolders((prev) => prev.filter((f) => f.id !== id));
    } catch {
      /* ignore */
    }
  };

  if (loading && folders.length === 0) {
    return (
      <>
        <div className="page-header">
          <div className="page-title">Папки</div>
        </div>
        <div className="loading-center">
          <div className="spinner" />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">Папки</div>
          {folders.length > 0 && (
            <div className="page-subtitle">{folders.length} папок</div>
          )}
        </div>
        <button
          className="btn btn-primary"
          onClick={() => setShowCreate(!showCreate)}
        >
          + Создать
        </button>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="detail-section-title">Новая папка</div>
          <div className="folder-emoji-picker">
            {EMOJI_OPTIONS.map((e) => (
              <button
                key={e}
                className={`folder-emoji-btn ${newEmoji === e ? "active" : ""}`}
                onClick={() => setNewEmoji(e)}
              >
                {e}
              </button>
            ))}
          </div>
          <input
            className="search-input"
            type="text"
            placeholder="Название папки..."
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            autoFocus
            style={{ marginTop: 8, paddingLeft: 16 }}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button
              className="btn btn-primary"
              style={{ flex: 1 }}
              disabled={!newName.trim() || creating}
              onClick={handleCreate}
            >
              {creating ? "Создаю..." : "Создать"}
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => setShowCreate(false)}
            >
              Отмена
            </button>
          </div>
        </div>
      )}

      {folders.length === 0 && !showCreate && (
        <div className="empty-state">
          <div className="empty-state-icon">{"\u{1F4C2}"}</div>
          <div className="empty-state-text">
            Пока нет папок.
            <br />
            Создай папку, чтобы организовать закладки.
          </div>
        </div>
      )}

      {folders.map((folder) => (
        <div
          className="card folder-card"
          key={folder.id}
          onClick={() => navigate(`/folder/${folder.id}`)}
        >
          <div className="folder-row">
            <span className="folder-icon">{folder.emoji || "\u{1F4C1}"}</span>
            <div className="folder-info">
              <div className="folder-name">{folder.name}</div>
              <div className="folder-count">
                {folder.bookmarks_count}{" "}
                {folder.bookmarks_count === 1 ? "закладка" : "закладок"}
              </div>
            </div>
            <button
              className="btn-icon"
              onClick={(e) => handleDelete(e, folder.id)}
              title="Удалить"
            >
              {"\u{1F5D1}"}
            </button>
          </div>
        </div>
      ))}
    </>
  );
}
