import { useCallback, useRef } from "react";
import type { PointerEvent as ReactPointerEvent, MouseEvent as ReactMouseEvent } from "react";
import { hapticImpact } from "../lib/telegram";

export interface LongPressOptions {
  /** ms before long-press fires. Default 500. */
  delay?: number;
  /** Cancel if pointer moves more than this many px from start. Default 10. */
  moveThreshold?: number;
}

export interface LongPressHandlers {
  onPointerDown: (e: ReactPointerEvent<HTMLElement>) => void;
  onPointerUp: (e: ReactPointerEvent<HTMLElement>) => void;
  onPointerMove: (e: ReactPointerEvent<HTMLElement>) => void;
  onPointerCancel: (e: ReactPointerEvent<HTMLElement>) => void;
  onPointerLeave: (e: ReactPointerEvent<HTMLElement>) => void;
  onContextMenu: (e: ReactMouseEvent<HTMLElement>) => void;
}

/**
 * useLongPress — hook для long-press жеста (500ms по умолчанию).
 *
 * - Pointer events (не touch) → кроссплатформенно (iOS/Android/desktop).
 * - Cancel при движении >10px (юзер начал скролл).
 * - HapticFeedback.impactOccurred('medium') при срабатывании.
 * - onContextMenu подавляет нативное long-press menu iOS Safari.
 *
 * Использование:
 *   const lp = useLongPress((pos) => openActionSheet(id, pos));
 *   return <div {...lp} onClick={handleTap} />
 *
 * Чтобы click не срабатывал после longpress — проверяем `triggered.current`
 * через сам родитель: см. useLongPressClick().
 */
export function useLongPress(
  onLongPress: (position: { x: number; y: number }) => void,
  options: LongPressOptions = {},
): LongPressHandlers & { triggered: { current: boolean } } {
  const { delay = 500, moveThreshold = 10 } = options;
  const timer = useRef<number | null>(null);
  const startPos = useRef<{ x: number; y: number } | null>(null);
  const triggered = useRef(false);
  const callback = useRef(onLongPress);
  callback.current = onLongPress;

  const clear = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    startPos.current = null;
  }, []);

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      // Только primary button (touch / left click). Игнорим right click.
      if (e.button !== 0 && e.pointerType === "mouse") return;
      triggered.current = false;
      startPos.current = { x: e.clientX, y: e.clientY };
      timer.current = window.setTimeout(() => {
        triggered.current = true;
        hapticImpact("medium");
        if (startPos.current) callback.current(startPos.current);
      }, delay);
    },
    [delay],
  );

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (!startPos.current) return;
      const dx = Math.abs(e.clientX - startPos.current.x);
      const dy = Math.abs(e.clientY - startPos.current.y);
      if (dx > moveThreshold || dy > moveThreshold) clear();
    },
    [moveThreshold, clear],
  );

  const onPointerUp = useCallback((_e: ReactPointerEvent<HTMLElement>) => {
    clear();
  }, [clear]);

  const onPointerCancel = useCallback((_e: ReactPointerEvent<HTMLElement>) => {
    clear();
  }, [clear]);

  const onPointerLeave = useCallback((_e: ReactPointerEvent<HTMLElement>) => {
    clear();
  }, [clear]);

  // Подавляет нативное iOS Safari context-menu при долгом тапе.
  const onContextMenu = useCallback((e: ReactMouseEvent<HTMLElement>) => {
    e.preventDefault();
  }, []);

  return { onPointerDown, onPointerUp, onPointerMove, onPointerCancel, onPointerLeave, onContextMenu, triggered };
}
