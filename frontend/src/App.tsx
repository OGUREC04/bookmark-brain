import { Routes, Route } from "react-router-dom";
import { BookmarkListPage } from "./pages/BookmarkList";
import { BookmarkDetailPage } from "./pages/BookmarkDetail";
import { SearchPage } from "./pages/Search";
import { FoldersPage } from "./pages/Folders";
import { FolderDetailPage } from "./pages/FolderDetail";
import { BottomNav } from "./components/BottomNav";

export function App() {
  return (
    <>
      <div className="app">
        <Routes>
          <Route path="/" element={<BookmarkListPage />} />
          <Route path="/bookmark/:id" element={<BookmarkDetailPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/folders" element={<FoldersPage />} />
          <Route path="/folder/:id" element={<FolderDetailPage />} />
        </Routes>
      </div>
      <BottomNav />
    </>
  );
}
