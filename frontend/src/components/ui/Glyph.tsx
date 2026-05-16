interface GlyphProps {
  /** Editorial char: ∅ ✦ ★ ¶ § # @ № → ← ↗ ↺ « » — + × */
  ch: string;
  size?: number;
  color?: string;
  weight?: number;
  opacity?: number;
}

/**
 * Editorial glyph — Lora italic char rendered as an icon.
 * DS: emotion/state/AI markers, empty-state hero (size 64-72, opacity 0.55),
 * favorite star, dividers. NEVER for UI labels/buttons.
 */
export function Glyph({ ch, size = 28, color = "var(--brand-primary)", weight = 500, opacity = 1 }: GlyphProps) {
  return (
    <span
      aria-hidden="true"
      style={{
        fontFamily: "var(--font-display)",
        fontStyle: "italic",
        fontWeight: weight,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.01em",
        color,
        opacity,
        display: "inline-block",
      }}
    >
      {ch}
    </span>
  );
}
