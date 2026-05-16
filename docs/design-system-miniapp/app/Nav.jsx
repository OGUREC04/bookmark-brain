/* Bottom Nav — 3 tabs + center FAB. Floating frosted pill, idle = icon only, active = sage pill. */

function BottomNav({ current, onChange, onFab }) {
  const tabs = [
    { id: 'mysli',  label: 'мысли',       icon: ExtraIcons.thoughts },
    { id: 'spaces', label: 'пространства', icon: ExtraIcons.spaces },
    { id: 'me',     label: 'я',           icon: Icons.user },
  ];

  return (
    <div style={{
      position: 'absolute', left: 14, right: 14, bottom: 24,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: 12,
      pointerEvents: 'none',
    }}>
      {/* tabs pill */}
      <div style={{
        flex: 1,
        pointerEvents: 'auto',
        background: 'rgba(255,252,246,0.75)',
        backdropFilter: 'blur(28px) saturate(180%)',
        WebkitBackdropFilter: 'blur(28px) saturate(180%)',
        border: '1px solid rgba(255,255,255,0.7)',
        borderRadius: 999,
        display: 'flex', justifyContent: 'space-around', alignItems: 'center',
        padding: '7px 8px',
        boxShadow: '0 1px 0 rgba(255,255,255,0.7) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 16px 40px rgba(60,40,25,0.12)',
      }}>
        {tabs.map((t, i) => {
          const active = current === t.id;
          // insert FAB slot between tabs[0] and tabs[1]
          return (
            <React.Fragment key={t.id}>
              <button onClick={() => onChange(t.id)} style={{
                background: active ? 'var(--brand-primary)' : 'transparent',
                border: 'none', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
                padding: active ? '8px 14px' : '8px 10px',
                borderRadius: 999,
                color: active ? 'var(--fg-on-brand)' : 'var(--fg-3)',
                fontFamily: 'var(--font-ui)', fontSize: 12.5, fontWeight: 500,
                letterSpacing: '-0.005em',
                boxShadow: active
                  ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.22)'
                  : 'none',
                transition: 'all 220ms var(--ease-out)',
              }}>
                {React.cloneElement(t.icon, { size: 18, sw: 1.6 })}
                {active && <span>{t.label}</span>}
              </button>
              {/* slot for the FAB after first tab visually but it's an overlay below */}
            </React.Fragment>
          );
        })}
      </div>

      {/* center FAB — overlayed, raised slightly */}
      <button onClick={onFab} aria-label="создать" style={{
        pointerEvents: 'auto',
        width: 54, height: 54, borderRadius: '50%',
        background: 'var(--brand-primary)',
        color: 'var(--fg-on-brand)',
        border: 'none', cursor: 'pointer', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 1px 0 rgba(255,255,255,0.25) inset, 0 6px 18px rgba(122,156,122,0.4), 0 2px 6px rgba(60,40,25,0.18)',
        transition: 'transform 160ms var(--ease-out)',
      }}
        onMouseDown={e=>{e.currentTarget.style.transform='translateY(1px)';}}
        onMouseUp={e=>{e.currentTarget.style.transform='translateY(0)';}}
        onMouseLeave={e=>{e.currentTarget.style.transform='translateY(0)';}}
      >
        {React.cloneElement(Icons.plus, { size: 22, sw: 2 })}
      </button>
    </div>
  );
}

Object.assign(window, { BottomNav });
