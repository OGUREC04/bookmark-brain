/**
 * Minimal skeleton placeholders для loading-состояния списка.
 * shimmer 1.5s, высота ~88px feed / ~64px chats.
 */
export function SkeletonFeed({ count = 5 }: { count?: number }) {
  return (
    <div className="skeleton-list">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton-card skeleton-card--feed" />
      ))}
    </div>
  );
}

export function SkeletonChats({ count = 8 }: { count?: number }) {
  return (
    <div className="skeleton-list">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton-card skeleton-card--chats">
          <div className="skeleton-avatar" />
          <div className="skeleton-lines">
            <div className="skeleton-line skeleton-line--title" />
            <div className="skeleton-line skeleton-line--text" />
          </div>
        </div>
      ))}
    </div>
  );
}
