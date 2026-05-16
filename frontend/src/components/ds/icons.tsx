/* DS icon set — slim-line 1.5 stroke, currentColor. Ported 1:1 from
   docs/design-system-miniapp/ds/Atoms.jsx + app/Icons.jsx (ExtraIcons). */
import type { ReactNode, CSSProperties } from "react";

interface IconProps {
  size?: number;
  sw?: number;
  fill?: string;
  stroke?: string;
  children?: ReactNode;
  style?: CSSProperties;
}

export function Icon({
  size = 20,
  sw = 1.5,
  fill = "none",
  stroke = "currentColor",
  children,
  style,
}: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke={stroke}
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const Icons = {
  search: <Icon><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Icon>,
  bookmark: <Icon><path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></Icon>,
  tag: <Icon><path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><circle cx="7" cy="7" r="1.5" /></Icon>,
  user: <Icon><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></Icon>,
  feed: <Icon><path d="M4 6h16M4 12h16M4 18h10" /></Icon>,
  cards: <Icon><rect x="3" y="4" width="8" height="16" rx="2" /><rect x="13" y="4" width="8" height="16" rx="2" /></Icon>,
  chat: <Icon><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z" /></Icon>,
  close: <Icon><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></Icon>,
  arrow: <Icon><path d="M5 12h14M13 6l6 6-6 6" /></Icon>,
  back: <Icon><path d="M19 12H5M11 18l-6-6 6-6" /></Icon>,
  link: <Icon><circle cx="5.5" cy="18.5" r="1.6" /><path d="M7 17 L17 7" /><path d="M11 6.5h6.5V13" /></Icon>,
  archive: <Icon><rect x="2" y="4" width="20" height="5" rx="1.5" /><path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9" /><path d="M10 13h4" /></Icon>,
  task: <Icon><rect x="3" y="3" width="18" height="18" rx="4" /><path d="M8 12l3 3 5-6" /></Icon>,
  voice: <Icon><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><line x1="12" y1="18" x2="12" y2="22" /></Icon>,
  pin: <Icon><path d="M12 2v8M8 10h8l-2 6h-4zM12 16v6" /></Icon>,
  check: <Icon sw={2}><polyline points="20 6 9 17 4 12" /></Icon>,
  plus: <Icon><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></Icon>,
  brain: <Icon><circle cx="12" cy="12" r="9" strokeDasharray="3 4" /><circle cx="12" cy="12" r="3.5" /></Icon>,
};

export const ExtraIcons = {
  bell: <Icon><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></Icon>,
  star: <Icon><polygon points="12 2 15.1 8.6 22 9.3 16.8 14.1 18.4 21 12 17.6 5.6 21 7.2 14.1 2 9.3 8.9 8.6 12 2" /></Icon>,
  mic: <Icon><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><line x1="12" y1="18" x2="12" y2="22" /></Icon>,
  trash: <Icon><path d="M3 6h18" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></Icon>,
  folder: <Icon><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></Icon>,
  clock: <Icon><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>,
  more: <Icon><circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" /></Icon>,
  sparkle: <Icon><path d="M12 3v6M12 15v6M3 12h6M15 12h6" /><path d="M6 6l3 3M15 15l3 3M6 18l3-3M15 9l3-3" /></Icon>,
  paperclip: <Icon><path d="M21 11.5l-9 9a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></Icon>,
  send: <Icon><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></Icon>,
  inbox: <Icon><polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /><path d="M5.4 6.5L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.4-5.5A2 2 0 0 0 16.9 5H7.1a2 2 0 0 0-1.7 1.5z" /></Icon>,
  spaces: <Icon><rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="8" rx="2" /><rect x="3" y="13" width="8" height="8" rx="2" /><rect x="13" y="13" width="8" height="8" rx="2" /></Icon>,
  thoughts: <Icon><path d="M21 12a8 8 0 0 1-8 8H8l-5 2 2-5a8 8 0 1 1 16-5" /><path d="M8 11h.01M12 11h.01M16 11h.01" /></Icon>,
};
