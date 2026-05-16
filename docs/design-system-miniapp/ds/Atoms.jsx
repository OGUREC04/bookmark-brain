/* Atoms — liquid glass + editorial language for Mini App */

/* ─── icons (slim line 1.4, currentColor) ─────────────── */
const Icon = ({ d, size=20, sw=1.5, fill='none', stroke='currentColor', children, style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={stroke}
    strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {d ? <path d={d}/> : children}
  </svg>
);

const Icons = {
  search:   <Icon><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></Icon>,
  bookmark: <Icon><path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></Icon>,
  tag:      <Icon><path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/></Icon>,
  user:     <Icon><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></Icon>,
  feed:     <Icon><path d="M4 6h16M4 12h16M4 18h10"/></Icon>,
  cards:    <Icon><rect x="3" y="4" width="8" height="16" rx="2"/><rect x="13" y="4" width="8" height="16" rx="2"/></Icon>,
  chat:     <Icon><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/></Icon>,
  close:    <Icon><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></Icon>,
  arrow:    <Icon><path d="M5 12h14M13 6l6 6-6 6"/></Icon>,
  back:     <Icon><path d="M19 12H5M11 18l-6-6 6-6"/></Icon>,
  link:     <Icon><circle cx="5.5" cy="18.5" r="1.6"/><path d="M7 17 L17 7"/><path d="M11 6.5h6.5V13"/></Icon>,
  archive:  <Icon><rect x="2" y="4" width="20" height="5" rx="1.5"/><path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/></Icon>,
  task:     <Icon><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M8 12l3 3 5-6"/></Icon>,
  voice:    <Icon><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><line x1="12" y1="18" x2="12" y2="22"/></Icon>,
  pin:      <Icon><path d="M12 2v8M8 10h8l-2 6h-4zM12 16v6"/></Icon>,
  check:    <Icon sw={2}><polyline points="20 6 9 17 4 12"/></Icon>,
  plus:     <Icon><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></Icon>,
  brain:    <Icon><circle cx="12" cy="12" r="9" strokeDasharray="3 4"/><circle cx="12" cy="12" r="3.5"/></Icon>,
};

/* ─── editorial glyph (Lora italic char as icon) ─────── */
function Glyph({ ch, size=28, color='var(--brand-primary)', weight=500, opacity=1 }) {
  return (
    <span style={{
      fontFamily: 'var(--font-display)', fontStyle: 'italic',
      fontWeight: weight, fontSize: size, lineHeight: 1, letterSpacing: '-0.01em',
      color, opacity, display: 'inline-block',
    }}>{ch}</span>
  );
}

/* ─── tag palette · sage-anchored warm ───────────────── */
const tagPalette = {
  1: { bg:'#E2EDE2', fg:'#2F4A2F' },  /* sage */
  2: { bg:'#F4E6CC', fg:'#7A5828' },  /* ochre */
  3: { bg:'#D8E2EA', fg:'#3D5A6E' },  /* slate */
  4: { bg:'#E5D8E8', fg:'#5C3D6E' },  /* plum */
  5: { bg:'#EFD8D2', fg:'#8A2A20' },  /* clay */
  6: { bg:'#E0E5C8', fg:'#4A5A2A' },  /* moss */
  7: { bg:'#F4D8DC', fg:'#8A2A35' },  /* rose */
  8: { bg:'#E0DED8', fg:'#56544C' },  /* taupe */
};

function TagChip({ name, color=1, onClick, size='md' }) {
  const c = tagPalette[color] || tagPalette[1];
  const sz = size === 'sm' ? { pad:'3px 10px', fs:11 } : { pad:'5px 12px', fs:12 };
  return (
    <span onClick={onClick} style={{
      padding: sz.pad, borderRadius: 999, fontSize: sz.fs, fontWeight: 500,
      background: c.bg, color: c.fg, cursor: 'pointer', whiteSpace: 'nowrap',
      fontFamily: 'var(--font-ui)', letterSpacing: '-0.005em',
    }}>{`#${name}`}</span>
  );
}

/* ─── pulsing dot ─────────────────────────────────────── */
function Pulse({ size=8, color='var(--brand-primary)' }) {
  return (
    <span style={{
      width: size, height: size, borderRadius: '50%',
      background: color,
      animation: 'mPulse 1.6s ease-in-out infinite',
      display: 'inline-block', flexShrink: 0,
    }}/>
  );
}

/* ─── liquid glass tile (reusable) ────────────────────── */
function GlassTile({ children, strong=false, style={} }) {
  return (
    <div style={{
      background: strong ? 'rgba(255,252,246,0.72)' : 'rgba(255,252,246,0.55)',
      backdropFilter: `blur(${strong?32:20}px) saturate(${strong?160:140}%)`,
      WebkitBackdropFilter: `blur(${strong?32:20}px) saturate(${strong?160:140}%)`,
      border: '1px solid rgba(255,255,255,0.6)',
      borderRadius: strong ? 28 : 22,
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 10px 30px rgba(60,40,25,0.08)',
      ...style,
    }}>{children}</div>
  );
}

/* ─── search bar — telegram-style glass pill ─────────── */
function SearchBar({ value, placeholder='найти в памяти…', onFocus, onChange, focused }) {
  return (
    <div onClick={onFocus} style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '13px 18px',
      background: 'rgba(255,252,246,0.72)',
      backdropFilter: 'blur(20px) saturate(160%)',
      WebkitBackdropFilter: 'blur(20px) saturate(160%)',
      border: `1px solid ${focused ? 'var(--brand-primary)' : 'rgba(255,255,255,0.6)'}`,
      borderRadius: 999, cursor: 'text',
      boxShadow: focused
        ? '0 1px 0 rgba(255,255,255,0.6) inset, 0 0 0 4px rgba(122,156,122,0.18), 0 8px 20px rgba(60,90,60,0.1)'
        : '0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 4px 12px rgba(60,40,25,0.06)',
      transition: 'box-shadow 200ms',
    }}>
      <span style={{ color: 'var(--fg-3)', display: 'flex', flexShrink: 0 }}>
        {React.cloneElement(Icons.search, { size: 18, sw: 1.6 })}
      </span>
      {value
        ? <input value={value} onChange={e=>onChange && onChange(e.target.value)} autoFocus style={{
            flex: 1, border: 'none', outline: 'none', background: 'transparent',
            font: 'inherit', fontSize: 15, color: 'var(--fg-1)', letterSpacing: '-0.01em',
          }}/>
        : <span style={{
            flex: 1, fontSize: 15, color: 'var(--fg-3)',
            fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
          }}>{placeholder}</span>}
      <span style={{ color: 'var(--fg-3)', display: 'flex', flexShrink: 0 }}>
        {React.cloneElement(Icons.voice, { size: 18, sw: 1.6 })}
      </span>
    </div>
  );
}

/* ─── empty state · big editorial glyph ──────────────── */
function EmptyState({ glyph='∅', head, copy }) {
  return (
    <div style={{
      textAlign: 'center', padding: '48px 24px 64px',
    }}>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic',
        fontSize: 72, color: 'var(--brand-primary)',
        lineHeight: 1, marginBottom: 18, opacity: 0.55,
      }}>{glyph}</div>
      <div style={{
        fontSize: 17, fontWeight: 500, letterSpacing: '-0.02em',
        color: 'var(--fg-1)', marginBottom: 6,
      }}>{head}</div>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic',
        fontSize: 14, color: 'var(--fg-3)', lineHeight: 1.4, letterSpacing: 0,
      }}>{copy}</div>
    </div>
  );
}

/* ─── keyframes (one-time) ────────────────────────────── */
const animCss = `@keyframes mPulse{0%,100%{opacity:1}50%{opacity:.35}}`;
if (typeof document !== 'undefined' && !document.getElementById('mini-app-anim')) {
  const s = document.createElement('style');
  s.id = 'mini-app-anim'; s.textContent = animCss;
  document.head.appendChild(s);
}

Object.assign(window, {
  Icon, Icons, Glyph, TagChip, tagPalette, Pulse, GlassTile, SearchBar, EmptyState,
});
