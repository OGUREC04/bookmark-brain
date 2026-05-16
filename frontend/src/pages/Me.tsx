import { AppHeader } from "../components/layout/AppHeader";

/**
 * «Я» — профиль / настройки (timezone, silent mode, etc.).
 * Stub T3. Full implementation later.
 */
export function MePage() {
  return (
    <div className="page">
      <AppHeader title="Я" />
      <div className="page__content">
        <div className="placeholder">
          <p>Профиль и настройки появятся позже.</p>
        </div>
      </div>
    </div>
  );
}
