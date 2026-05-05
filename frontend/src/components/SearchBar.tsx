import { useState, useCallback } from "react";

interface Props {
  onSearch: (query: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

export function SearchBar({ onSearch, placeholder = "Поиск закладок...", autoFocus }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (value.trim()) onSearch(value.trim());
    },
    [value, onSearch]
  );

  return (
    <div className="search-bar">
      <form onSubmit={handleSubmit}>
        <div className="search-wrapper">
          <span className="search-icon">{"\u{1F50D}"}</span>
          <input
            className="search-input"
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={placeholder}
            autoFocus={autoFocus}
          />
        </div>
      </form>
    </div>
  );
}
