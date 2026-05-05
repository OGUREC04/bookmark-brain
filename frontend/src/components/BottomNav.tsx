import { useLocation, useNavigate } from "react-router-dom";

const tabs = [
  { path: "/", icon: "\u{1F4D1}", label: "Закладки" },
  { path: "/folders", icon: "\u{1F4C1}", label: "Папки" },
  { path: "/search", icon: "\u{1F50D}", label: "Поиск" },
];

export function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  // Hide on detail pages
  if (
    location.pathname.startsWith("/bookmark/") ||
    location.pathname.startsWith("/folder/")
  )
    return null;

  return (
    <nav className="bottom-nav">
      {tabs.map((tab) => (
        <button
          key={tab.path}
          className={`nav-item ${location.pathname === tab.path ? "active" : ""}`}
          onClick={() => navigate(tab.path)}
        >
          <span className="nav-item-icon">{tab.icon}</span>
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
