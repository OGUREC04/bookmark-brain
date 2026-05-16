import { Routes, Route, Navigate } from "react-router-dom";
import { ThoughtsPage } from "./pages/Thoughts";
import { SpacesPage } from "./pages/Spaces";
import { MePage } from "./pages/Me";
import { SearchPage } from "./pages/Search";
import { BookmarkDetailPage } from "./pages/BookmarkDetail";
import { FolderDetailPage } from "./pages/FolderDetail";
import { BottomNav } from "./components/nav/BottomNav";

/**
 * Mini App layout.
 * - / → Thoughts (главный экран)
 * - /search → Search
 * - /spaces → Spaces (бывшие Folders)
 * - /me → профиль
 * - /thought/:id → детальная (legacy BookmarkDetailPage, переименуем в T7+)
 * - /space/:id → внутри пространства (legacy FolderDetailPage)
 * - /folders, /bookmark/:id, /folder/:id — redirect на новые пути (обратная совместимость закладок)
 */
export function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<ThoughtsPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/spaces" element={<SpacesPage />} />
        <Route path="/me" element={<MePage />} />
        <Route path="/thought/:id" element={<BookmarkDetailPage />} />
        <Route path="/space/:id" element={<FolderDetailPage />} />

        {/* Legacy redirects */}
        <Route path="/folders" element={<Navigate to="/spaces" replace />} />
        <Route path="/bookmark/:id" element={<Navigate to="/thought/:id" replace />} />
        <Route path="/folder/:id" element={<Navigate to="/space/:id" replace />} />
      </Routes>
      <BottomNav />
    </div>
  );
}
