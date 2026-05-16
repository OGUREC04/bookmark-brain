import { Star } from "lucide-react";

export type FilterValue =
  | { kind: "all" }
  | { kind: "favorite" }
  | { kind: "type"; itemType: string }
  | { kind: "tag"; tag: string };

export interface FilterOption {
  id: string;
  label: string;
  value: FilterValue;
  count?: number;
  icon?: "star";
}

interface FilterChipsProps {
  options: FilterOption[];
  activeId: string;
  onSelect: (option: FilterOption) => void;
}

/**
 * Горизонтальный sticky chip-row под шапкой.
 * - Активный: фон --fg-1, текст --bg-page.
 * - Неактивный: прозрачный, текст --fg-2.
 * - Counter (опционально) в чипе справа от label.
 */
export function FilterChips({ options, activeId, onSelect }: FilterChipsProps) {
  return (
    <div className="filter-chips" role="tablist">
      {options.map((opt) => {
        const isActive = opt.id === activeId;
        return (
          <button
            key={opt.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`filter-chip ${isActive ? "is-active" : ""}`}
            onClick={() => onSelect(opt)}
          >
            {opt.icon === "star" && (
              <Star size={13} strokeWidth={1.6} fill="currentColor" aria-hidden />
            )}
            <span>{opt.label}</span>
            {opt.count !== undefined && (
              <span className="filter-chip__count">{opt.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
