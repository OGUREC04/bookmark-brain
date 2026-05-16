import { NavLink, useLocation } from "react-router-dom";
import { Home, Search, Plus, Tag, User } from "lucide-react";
import { hapticImpact } from "../../lib/telegram";

/**
 * Bottom nav — OUR IA (5 cells: Мысли/Поиск/+/Простр./Я, central FAB),
 * DS STYLING (frosted-pill container, sage-pill active w/ label,
 * icon-only idle). Anatomy from docs/design-system/reference_app/MiniApp.jsx
 * BottomTab — adapted to keep our central FAB.
 *
 * Idle tab  : icon only, --fg-3, transparent.
 * Active tab : sage bg + white text + label, padding 8/16, primary shadow.
 * FAB        : central, our addition (DS deviation kept per C1).
 */
export function BottomNav() {
  const location = useLocation();

  const hide =
    location.pathname.startsWith("/thought/") ||
    location.pathname.startsWith("/space/") ||
    location.pathname.startsWith("/bookmark/") ||
    location.pathname.startsWith("/folder/");
  if (hide) return null;

  const handleFabClick = () => {
    hapticImpact("medium");
    window.location.hash = "#/create"; // T13: QuickCreateSheet
  };

  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav-tab ${isActive ? "is-active" : ""}`;

  return (
    <nav className="bottom-nav" aria-label="Главная навигация">
      <NavLink to="/" end className={cls}>
        <Home size={18} strokeWidth={1.6} aria-hidden />
        <span className="nav-tab__label">Мысли</span>
      </NavLink>

      <NavLink to="/search" className={cls}>
        <Search size={18} strokeWidth={1.6} aria-hidden />
        <span className="nav-tab__label">Поиск</span>
      </NavLink>

      <button
        type="button"
        className="nav-fab"
        onClick={handleFabClick}
        aria-label="Создать мысль"
      >
        <Plus size={22} strokeWidth={1.6} aria-hidden />
      </button>

      <NavLink to="/spaces" className={cls}>
        <Tag size={18} strokeWidth={1.6} aria-hidden />
        <span className="nav-tab__label">Простр.</span>
      </NavLink>

      <NavLink to="/me" className={cls}>
        <User size={18} strokeWidth={1.6} aria-hidden />
        <span className="nav-tab__label">Я</span>
      </NavLink>
    </nav>
  );
}
