import { useCallback, useEffect, useState } from "react";
import { AppHeader } from "../components/layout/AppHeader";
import { ThoughtCard } from "../components/cards/ThoughtCard";
import { SkeletonFeed, SkeletonChats } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { FilterChips, type FilterOption } from "../components/ui/FilterChips";
import { useViewMode } from "../hooks/useViewMode";
import { api } from "../lib/api";
import { bookmarkToThought, buildRemindersMap } from "../lib/adapters";
import type { Thought } from "../lib/types";

const FILTER_OPTIONS: FilterOption[] = [
  { id: "all", label: "Все", value: { kind: "all" } },
  { id: "favorite", label: "", icon: "star", value: { kind: "favorite" } },
  { id: "task", label: "Задачи", value: { kind: "type", itemType: "action" } },
  { id: "voice", label: "Голос", value: { kind: "type", itemType: "voice" } },
];

export function ThoughtsPage() {
  const { viewMode, setViewMode } = useViewMode();
  const [thoughts, setThoughts] = useState<Thought[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState("all");
  const [remindersCount, setRemindersCount] = useState(0);

  const perPage = 20;

  const loadPage = useCallback(
    async (pageNum: number, filterId: string, signal?: AbortSignal) => {
      const filter = FILTER_OPTIONS.find((f) => f.id === filterId) ?? FILTER_OPTIONS[0];
      const params: Parameters<typeof api.getBookmarks>[0] = { page: pageNum, perPage };
      if (filter.value.kind === "favorite") params.isFavorite = true;
      if (filter.value.kind === "type") params.itemType = filter.value.itemType;

      // Параллельно: bookmarks + upcoming reminders (для hasReminder badges)
      const [list, upcoming] = await Promise.all([
        api.getBookmarks(params),
        pageNum === 1 ? api.reminders.upcoming(50).catch(() => ({ items: [], total: 0 })) : Promise.resolve(null),
      ]);
      if (signal?.aborted) return null;

      let remindersMap: Map<string, { fireAt: string }> = new Map();
      if (upcoming) {
        remindersMap = buildRemindersMap(
          upcoming.items.map((r) => ({ bookmark_id: r.bookmark_id, fire_at: r.fire_at })),
        );
        setRemindersCount(upcoming.total);
      }
      const mapped = list.items.map((b) => bookmarkToThought(b, remindersMap));
      return { mapped, total: list.total };
    },
    [],
  );

  // Initial load + filter change
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setPage(1);
    setHasMore(true);

    loadPage(1, activeFilter, controller.signal)
      .then((res) => {
        if (!res || controller.signal.aborted) return;
        setThoughts(res.mapped);
        setTotal(res.total);
        setHasMore(res.mapped.length < res.total);
        setLoading(false);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        setError(e?.message || "Не удалось загрузить мысли");
        setLoading(false);
      });

    return () => controller.abort();
  }, [activeFilter, loadPage]);

  // Infinite scroll trigger
  const loadMore = useCallback(() => {
    if (loading || !hasMore) return;
    const nextPage = page + 1;
    setPage(nextPage);
    loadPage(nextPage, activeFilter).then((res) => {
      if (!res) return;
      setThoughts((prev) => [...prev, ...res.mapped]);
      setHasMore(prev => {
        const newTotal = prev ? res.mapped.length : 0;
        return thoughts.length + res.mapped.length < res.total;
      });
    }).catch(() => {/* silent retry on next scroll */});
  }, [loading, hasMore, page, activeFilter, loadPage, thoughts.length]);

  // Scroll handler (простой, без IntersectionObserver — достаточно для MVP)
  useEffect(() => {
    const onScroll = () => {
      if (loading || !hasMore) return;
      const scrolledToBottom =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 400;
      if (scrolledToBottom) loadMore();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [loadMore, loading, hasMore]);

  const handleFilter = (opt: FilterOption) => setActiveFilter(opt.id);

  return (
    <div className="page">
      <AppHeader
        title="Мысли"
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        remindersCount={remindersCount}
      />

      <FilterChips
        options={FILTER_OPTIONS.map((o) =>
          o.id === "all" ? { ...o, count: total || undefined } : o,
        )}
        activeId={activeFilter}
        onSelect={handleFilter}
      />

      <div className="page__content">
        {loading && thoughts.length === 0 && (
          viewMode === "feed" ? <SkeletonFeed /> : <SkeletonChats />
        )}

        {error && (
          <EmptyState
            glyph="∅"
            title="Не удалось загрузить"
            description={error}
            action={
              <button className="btn btn-primary" onClick={() => setActiveFilter(activeFilter)}>
                Попробовать снова
              </button>
            }
          />
        )}

        {!loading && !error && thoughts.length === 0 && (
          <EmptyState
            glyph="¶"
            title="Пока пусто."
            description="Отправь что-нибудь боту — ссылку, мысль, голосовое. Появится здесь."
          />
        )}

        {thoughts.length > 0 && (
          <div className={`thoughts-list thoughts-list--${viewMode}`} role="list">
            {thoughts.map((t, i) => (
              <ThoughtCard
                key={t.id}
                thought={t}
                variant={viewMode}
                isLast={i === thoughts.length - 1}
              />
            ))}
            {loading && thoughts.length > 0 && (
              <p className="loading-more">Загружаем…</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
