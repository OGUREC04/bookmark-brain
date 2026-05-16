// Telegram Web App SDK integration
// Updated 2026-05-15 (T1): theme bridge to CSS vars, themeChanged listener, viewport helpers, BackButton/MainButton/Haptic re-exports.

declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp;
    };
  }
}

type ThemeParams = Partial<{
  bg_color: string;
  text_color: string;
  hint_color: string;
  link_color: string;
  button_color: string;
  button_text_color: string;
  secondary_bg_color: string;
  header_bg_color: string;
  accent_text_color: string;
  section_bg_color: string;
  section_header_text_color: string;
  subtitle_text_color: string;
  destructive_text_color: string;
}>;

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      first_name: string;
      last_name?: string;
      username?: string;
      language_code?: string;
    };
  };
  colorScheme: "light" | "dark";
  themeParams: ThemeParams;
  viewportHeight: number;
  viewportStableHeight: number;
  isExpanded: boolean;
  ready: () => void;
  expand: () => void;
  close: () => void;
  onEvent: (eventType: string, handler: () => void) => void;
  offEvent: (eventType: string, handler: () => void) => void;
  MainButton: {
    text: string;
    isVisible: boolean;
    isActive: boolean;
    show: () => void;
    hide: () => void;
    enable: () => void;
    disable: () => void;
    setText: (text: string) => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
    showProgress: (leaveActive?: boolean) => void;
    hideProgress: () => void;
  };
  BackButton: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  HapticFeedback: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
}

export function getTelegramWebApp(): TelegramWebApp | null {
  return window.Telegram?.WebApp ?? null;
}

export function getInitData(): string {
  return getTelegramWebApp()?.initData ?? "";
}

export function isDarkTheme(): boolean {
  return getTelegramWebApp()?.colorScheme === "dark";
}

export function getUserInfo() {
  return getTelegramWebApp()?.initDataUnsafe?.user ?? null;
}

export function getViewportStableHeight(): number {
  return getTelegramWebApp()?.viewportStableHeight ?? window.innerHeight;
}

// HapticFeedback wrappers (no-op outside TG, never throw)
export function hapticImpact(style: "light" | "medium" | "heavy" = "medium"): void {
  try {
    getTelegramWebApp()?.HapticFeedback?.impactOccurred(style);
  } catch {
    /* no-op */
  }
}

export function hapticNotify(type: "error" | "success" | "warning" = "success"): void {
  try {
    getTelegramWebApp()?.HapticFeedback?.notificationOccurred(type);
  } catch {
    /* no-op */
  }
}

export function hapticSelection(): void {
  try {
    getTelegramWebApp()?.HapticFeedback?.selectionChanged();
  } catch {
    /* no-op */
  }
}

/**
 * Maps Telegram themeParams → CSS custom properties on documentElement
 * via [data-tg-bridge=true]. Reads our token names from tokens.css.
 * Idempotent: safe to call multiple times.
 */
export function applyTheme(): void {
  const app = getTelegramWebApp();
  const root = document.documentElement;
  const dark = app?.colorScheme === "dark";
  // Lock direction = echo (Sage). Dark = echo-dark. Other tokens.css directions not used by Mini App.
  root.setAttribute("data-theme", dark ? "echo-dark" : "echo");
  root.setAttribute("data-tg-bridge", app ? "true" : "false");
  if (app) {
    if (dark) {
      root.classList.add("theme-dark");
      root.setAttribute("data-color-scheme", "dark");
    } else {
      root.classList.remove("theme-dark");
      root.setAttribute("data-color-scheme", "light");
    }
    // Expose tg-theme-* vars under stable names (used by tokens.css [data-tg-bridge="true"]).
    const t = app.themeParams ?? {};
    const set = (k: string, v: string | undefined): void => {
      if (v) root.style.setProperty(k, v);
    };
    set("--tg-theme-bg-color", t.bg_color);
    set("--tg-theme-secondary-bg-color", t.secondary_bg_color);
    set("--tg-theme-text-color", t.text_color);
    set("--tg-theme-hint-color", t.hint_color);
    set("--tg-theme-link-color", t.link_color);
    set("--tg-theme-button-color", t.button_color);
    set("--tg-theme-button-text-color", t.button_text_color);
  }
}

/**
 * Subscribe to TG themeChanged. Returns cleanup.
 */
export function onThemeChanged(cb: () => void): () => void {
  const app = getTelegramWebApp();
  if (!app) return () => {};
  const handler = (): void => {
    applyTheme();
    cb();
  };
  app.onEvent("themeChanged", handler);
  return () => app.offEvent("themeChanged", handler);
}

/**
 * Sync init for main.tsx — call BEFORE createRoot to avoid theme-flash.
 */
export function initTelegramApp(): void {
  const app = getTelegramWebApp();
  if (app) {
    app.ready();
    app.expand();
  }
  applyTheme();
}

// Re-export typed handles for the rest of the app.
export function getBackButton(): TelegramWebApp["BackButton"] | null {
  return getTelegramWebApp()?.BackButton ?? null;
}

export function getMainButton(): TelegramWebApp["MainButton"] | null {
  return getTelegramWebApp()?.MainButton ?? null;
}
