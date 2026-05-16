import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { initTelegramApp, onThemeChanged } from "./lib/telegram";
import "./styles.css";

// Sync theme bootstrap BEFORE createRoot — prevents flash of wrong theme.
initTelegramApp();

// Re-apply on TG themeChanged (user switches light/dark in Telegram settings).
onThemeChanged(() => {
  /* applyTheme is called inside the listener — CSS vars updated automatically. */
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Navigation is state-driven (DS single-frame + sheets); no router needed. */}
    <App />
  </React.StrictMode>
);
