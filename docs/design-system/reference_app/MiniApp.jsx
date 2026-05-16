/* MiniApp — shell · brand-light backdrop · frosted bottom tab */

function MiniApp() {
  const [view, setView] = React.useState('feed'); // feed | search | tags | me

  React.useEffect(() => {
    document.body.setAttribute('data-theme', 'echo');
  }, []);

  return (
    <IOSDevice width={402} height={840}>
      <div style={{
        height: '100%', overflow: 'auto', position: 'relative',
        background: 'var(--backdrop-gradient)',
        paddingTop: 54,
      }}>
        {view === 'feed' && <Feed onSearch={() => setView('search')}/>}
        {view === 'search' && <SearchView onBack={() => setView('feed')}/>}
        {view === 'tags' && <TagsView/>}
        {view === 'me' && <MeView/>}
        <BottomTab current={view} onChange={setView}/>
      </div>
    </IOSDevice>
  );
}

function BottomTab({ current, onChange }) {
  const tabs = [
    { id: 'feed',   label: 'лента', icon: Icons.feed },
    { id: 'search', label: 'поиск', icon: Icons.search },
    { id: 'tags',   label: 'теги',  icon: Icons.tag },
    { id: 'me',     label: 'я',     icon: Icons.user },
  ];

  return (
    <div style={{
      position: 'absolute', left: 12, right: 12, bottom: 24,
      background: 'rgba(255,252,246,0.7)',
      backdropFilter: 'blur(28px) saturate(180%)',
      WebkitBackdropFilter: 'blur(28px) saturate(180%)',
      border: '1px solid rgba(255,255,255,0.7)',
      borderRadius: 999,
      display: 'flex', justifyContent: 'space-around',
      padding: '8px',
      boxShadow: '0 1px 0 rgba(255,255,255,0.7) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 16px 40px rgba(60,40,25,0.12)',
    }}>
      {tabs.map(t => {
        const active = current === t.id;
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={{
            background: active ? 'var(--brand-primary)' : 'transparent',
            border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
            padding: active ? '8px 16px' : '8px 12px',
            borderRadius: 999,
            color: active ? 'var(--fg-on-brand)' : 'var(--fg-3)',
            fontFamily: 'var(--font-ui)', fontSize: 12.5, fontWeight: 500,
            letterSpacing: '-0.005em',
            boxShadow: active ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.2)' : 'none',
            transition: 'all 220ms var(--ease-out)',
          }}>
            {React.cloneElement(t.icon, { size: 18, sw: 1.6 })}
            {active && <span>{t.label}</span>}
          </button>
        );
      })}
    </div>
  );
}

Object.assign(window, { MiniApp, BottomTab });
