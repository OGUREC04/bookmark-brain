import { useState, useCallback } from "react";
import { api, type SearchResult } from "../lib/api";
import { SearchBar } from "../components/SearchBar";
import { BookmarkCard } from "../components/BookmarkCard";
import { SearchSummary } from "../components/SearchSummary";

export function SearchPage() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [query, setQuery] = useState("");

  const handleSearch = useCallback(async (q: string) => {
    setLoading(true);
    setSearched(true);
    setQuery(q);
    setSummary(null);
    try {
      const data = await api.search(q);
      setResults(data.results);
      setSummary(data.summary);
    } catch {
      setResults([]);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleCitationClick = useCallback((idx: number) => {
    // [N] в саммари — это 1-based индекс результата.
    const el = document.getElementById(`search-result-${idx}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("highlight-flash");
      setTimeout(() => el.classList.remove("highlight-flash"), 1500);
    }
  }, []);

  return (
    <>
      <div className="page-header">
        <div className="page-title">Поиск</div>
      </div>

      <SearchBar onSearch={handleSearch} autoFocus />

      {loading && (
        <div className="loading-center">
          <div className="spinner" />
        </div>
      )}

      {!loading && summary && (
        <SearchSummary summary={summary} onCitationClick={handleCitationClick} />
      )}

      {!loading && searched && results.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">{"\u{1F50E}"}</div>
          <div className="empty-state-text">
            По запросу "{query}" ничего не найдено
          </div>
        </div>
      )}

      {!loading &&
        results.map((r, i) => (
          <div id={`search-result-${i + 1}`} key={r.bookmark.id}>
            <BookmarkCard bookmark={r.bookmark} />
          </div>
        ))}

      {!searched && (
        <div className="empty-state">
          <div className="empty-state-icon">{"\u{1F50D}"}</div>
          <div className="empty-state-text">
            Введи запрос на естественном языке
            <br />
            — AI найдёт подходящие закладки
          </div>
        </div>
      )}
    </>
  );
}
