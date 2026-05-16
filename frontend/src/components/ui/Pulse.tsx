interface PulseProps {
  size?: number;
  color?: string;
}

/**
 * Pulsing dot — DS replacement for spinners/progress bars.
 * Single 8px sage dot, opacity 1 → 0.35 → 1 over 1.6s.
 * Keyframe `bb-pulse` is defined in styles/layout.css (respects reduced-motion).
 */
export function Pulse({ size = 8, color = "var(--brand-primary)" }: PulseProps) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        animation: "bb-pulse 1.6s ease-in-out infinite",
        display: "inline-block",
        flexShrink: 0,
      }}
    />
  );
}
