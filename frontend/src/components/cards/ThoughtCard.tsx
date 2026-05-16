import { useNavigate } from "react-router-dom";
import type { Thought, CardVariant } from "../../lib/types";
import { useLongPress } from "../../hooks/useLongPress";
import { ThoughtCardFeed } from "./ThoughtCardFeed";
import { ThoughtCardChats } from "./ThoughtCardChats";

interface ThoughtCardProps {
  thought: Thought;
  variant: CardVariant;
  /** Открыть детали мысли. По умолчанию навигация на /thought/:id. */
  onTap?: (id: string) => void;
  /** Открыть ActionSheet (T8). По умолчанию stub — TODO в T8 wire-up. */
  onLongPress?: (id: string, position: { x: number; y: number }) => void;
}

/**
 * Wrapper компонент:
 * - применяет useLongPress (500ms + haptic)
 * - подавляет click если longpress сработал
 * - роутит между Feed и Chats variant
 *
 * `onLongPress` пока stub — wire-up с SheetContext.openSheet(ActionSheet) в T8.
 */
export function ThoughtCard({ thought, variant, onTap, onLongPress }: ThoughtCardProps) {
  const navigate = useNavigate();

  const handleLongPress = (pos: { x: number; y: number }) => {
    if (onLongPress) onLongPress(thought.id, pos);
    else console.debug("[ThoughtCard] longPress stub — T8 will wire ActionSheet", thought.id);
  };

  const lp = useLongPress(handleLongPress);

  const handleClick = (e: React.MouseEvent) => {
    // Не открываем детали если только что сработал longpress
    if (lp.triggered.current) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (onTap) onTap(thought.id);
    else navigate(`/thought/${thought.id}`);
  };

  const handleMenuTap = () => {
    handleLongPress({ x: 0, y: 0 });
  };

  const isFeed = variant === "feed";

  return (
    <div
      className={`thought-card thought-card--${variant}`}
      role="listitem"
      aria-label={thought.title}
      onClick={handleClick}
      onPointerDown={lp.onPointerDown}
      onPointerUp={lp.onPointerUp}
      onPointerMove={lp.onPointerMove}
      onPointerCancel={lp.onPointerCancel}
      onPointerLeave={lp.onPointerLeave}
      onContextMenu={lp.onContextMenu}
    >
      {isFeed ? (
        <ThoughtCardFeed thought={thought} onMenuTap={handleMenuTap} />
      ) : (
        <ThoughtCardChats thought={thought} onMenuTap={handleMenuTap} />
      )}
    </div>
  );
}
