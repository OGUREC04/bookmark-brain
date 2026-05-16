import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
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
    {/* HashRouter — safer than BrowserRouter in Telegram WebView (no 404 on reload, no popstate quirks on iOS). */}
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
);
