import { AppHeader } from "../components/layout/AppHeader";

/**
 * Пространства — stub T3. В T11 здесь будет grid с пространствами + создание.
 * Пока показывает только Header.
 */
export function SpacesPage() {
  return (
    <div className="page">
      <AppHeader title="Пространства" />
      <div className="page__content">
        <div className="placeholder">
          <p>Здесь будут пространства (T11).</p>
        </div>
      </div>
    </div>
  );
}
