import { NavLink, useLocation } from "react-router-dom";
import { Home, Search, Plus, LayoutGrid, User } from "lucide-react";
import { hapticImpact } from "../../lib/telegram";

/**
 * Floating liquid-glass bottom nav with 5 items:
 *   Мысли · Поиск · [+ FAB центр] · Простр. · Я
 *
 * - FAB центральный 46x46, тёмный rgba(44,40,37,0.92), без brand-цвета.
 * - Active item gets rgba(0,0,0,0.05) bg.
 * - backdrop-filter blur 28px + saturate 180% для liquid-glass effect.
 * - На detail-роутах (e.g. /bookmark/:id) скрывается через CSS class.
 */
export function BottomNav() {
  const location = useLocation();

  // Hide on detail screens — same convention as legacy.
  const hide =
    location.pathname.startsWith("/bookmark/") ||
    location.pathname.startsWith("/folder/") ||
    location.pathname.startsWith("/thought/") ||
    location.pathname.startsWith("/space/");
  if (hide) return null;

  const handleFabClick = () => {
    hapticImpact("medium");
    // T13: open QuickCreateSheet. Stub for now.
    window.location.hash = "#/create";
  };

  return (
    <nav className="bottom-nav" aria-label="Главная навигация">
      <NavLink
        to="/"
        end
        className={({ isActive }) => `bottom-nav__btn ${isActive ? "is-active" : ""}`}
      >
        <Home size={20} strokeWidth={1.9} />
        <span className="bottom-nav__label">Мысли</span>
      </NavLink>

      <NavLink
        to="/search"
        className={({ isActive }) => `bottom-nav__btn ${isActive ? "is-active" : ""}`}
      >
        <Search size={20} strokeWidth={1.9} />
        <span className="bottom-nav__label">Поиск</span>
      </NavLink>

      <button
        type="button"
        className="bottom-nav__btn bottom-nav__fab"
        onClick={handleFabClick}
        aria-label="Создать мысль"
      >
        <Plus size={22} strokeWidth={2.2} />
      </button>

      <NavLink
        to="/spaces"
        className={({ isActive }) => `bottom-nav__btn ${isActive ? "is-active" : ""}`}
      >
        <LayoutGrid size={20} strokeWidth={1.9} />
        <span className="bottom-nav__label">Простр.</span>
      </NavLink>

      <NavLink
        to="/me"
        className={({ isActive }) => `bottom-nav__btn ${isActive ? "is-active" : ""}`}
      >
        <User size={20} strokeWidth={1.9} />
        <span className="bottom-nav__label">Я</span>
      </NavLink>
    </nav>
  );
}
