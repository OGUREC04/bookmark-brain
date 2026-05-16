// DS tag palette — 8 stops, sage-anchored warm. Never competes with brand.
// Source: docs/design-system/README.md §"Tag palette" + reference_app/Atoms.jsx

export interface TagStop {
  bg: string;
  fg: string;
}

export const TAG_PALETTE: Record<number, TagStop> = {
  1: { bg: "#E2EDE2", fg: "#2F4A2F" }, // sage
  2: { bg: "#F4E6CC", fg: "#7A5828" }, // ochre
  3: { bg: "#D8E2EA", fg: "#3D5A6E" }, // slate
  4: { bg: "#E5D8E8", fg: "#5C3D6E" }, // plum
  5: { bg: "#EFD8D2", fg: "#8A2A20" }, // clay
  6: { bg: "#E0E5C8", fg: "#4A5A2A" }, // moss
  7: { bg: "#F4D8DC", fg: "#8A2A35" }, // rose
  8: { bg: "#E0DED8", fg: "#56544C" }, // taupe
};

const STOP_COUNT = 8;

/**
 * Deterministic stop (1..8) from a tag name — stable colour per tag
 * without storing colour in DB. Simple sum-hash; collisions are fine
 * (palette is decorative, sage-anchored so any pair harmonises).
 */
export function tagStop(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h + name.charCodeAt(i)) % STOP_COUNT;
  return h + 1;
}

export function tagColors(name: string): TagStop {
  return TAG_PALETTE[tagStop(name)];
}
