import { Fragment } from "react";

interface Props {
  summary: string;
  /** Колбек: пользователь кликнул по [N], нужно подскроллить к результату */
  onCitationClick: (idx: number) => void;
}

/**
 * AI-саммари над списком результатов поиска (как one-box у Google).
 * Парсит маркеры [1], [2], [12] и превращает их в кликабельные кнопки.
 */
export function SearchSummary({ summary, onCitationClick }: Props) {
  // Делим текст по [N], сохраняя сами маркеры в результате
  const parts = summary.split(/(\[\d+\])/g);

  return (
    <div className="search-summary">
      <div className="search-summary-label">{"\u2728 AI-ответ"}</div>
      <div className="search-summary-text">
        {parts.map((part, i) => {
          const m = part.match(/^\[(\d+)\]$/);
          if (m) {
            const idx = parseInt(m[1], 10);
            return (
              <button
                key={i}
                type="button"
                className="search-summary-cite"
                onClick={() => onCitationClick(idx)}
                title={`К результату ${idx}`}
              >
                {idx}
              </button>
            );
          }
          return <Fragment key={i}>{part}</Fragment>;
        })}
      </div>
    </div>
  );
}
