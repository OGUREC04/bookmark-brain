/* ЭКРАН 1 — Мысли · feed with our IA: filter chips + reminders bell */

function MysliScreen({ onSearch, onBell, onLongPress }) {
  const [view, setView] = React.useState('chat');
  const [filter, setFilter] = React.useState('all');
  const [hideSuggest, setHideSuggest] = React.useState(false);

  return (
    <div style={{ padding: '6px 0 100px' }}>
      {/* header — title + bell + counter */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', marginBottom: 14, marginTop: 4, gap: 10,
      }}>
        <h1 style={{
          fontSize: 32, fontWeight: 500, letterSpacing: '-0.035em',
          margin: 0, color: 'var(--fg-1)', lineHeight: 1,
        }}>
          мысли
          <span style={{
            fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500,
            color: 'var(--brand-primary)', marginLeft: 6, letterSpacing: '-0.01em',
          }}>·</span>
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ReminderBell count={3} onClick={onBell}/>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--fg-3)', letterSpacing: '.06em', fontWeight: 500,
          }}>347</span>
        </div>
      </div>

      {/* search */}
      <div style={{ padding: '0 16px', marginBottom: 14 }}>
        <SearchBar onFocus={onSearch}/>
      </div>

      {/* view toggle + day */}
      <div style={{
        padding: '0 16px', marginBottom: 10,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <ViewToggle view={view} setView={setView}/>
        <span style={{ flex: 1 }}/>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--fg-3)', letterSpacing: '.12em', textTransform: 'uppercase', fontWeight: 500,
        }}>сегодня</span>
      </div>

      {/* filter chips — sticky horizontal scroll */}
      <FilterChipsRow active={filter} onChange={setFilter}/>

      {/* AI suggestions (chat-mode only, dismissable) */}
      {!hideSuggest && view === 'chat' && filter === 'all' && (
        <SuggestionPager
          items={[
            {
              text: <>3 закладки про rlhf — собрать в <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--brand-primary)'}}>«alignment»</b>?</>,
              sources: [
                { letter: 'A', tone: 'sage',  domain: 'anthropic' },
                { letter: 'O', tone: 'slate', domain: 'openai' },
                { letter: 'K', tone: 'honey', domain: 'x.com' },
              ],
            },
            {
              text: <>год назад ты сохранил <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>«scaling laws»</b> — открыть?</>,
              sources: [
                { letter: 'S', tone: 'plum', domain: 'arxiv.org' },
              ],
              meta: '11 месяцев в очереди',
            },
            {
              text: <>не открывал «pinterest · ceramics» 30 дней — в архив?</>,
              sources: [
                { letter: 'P', tone: 'clay', domain: 'pinterest' },
              ],
              meta: 'это редкое сообщение',
            },
          ]}
          onDismissAll={() => setHideSuggest(true)}
        />
      )}

      {/* main view, filtered */}
      {view === 'chat'
        ? <FilteredChatView filter={filter} onLongPress={onLongPress}/>
        : <FilteredCardsView filter={filter}/>}
    </div>
  );
}

/* ─── ReminderBell — sage-tint pill with editorial glyph counter ── */
function ReminderBell({ count = 0, onClick }) {
  return (
    <button onClick={onClick} aria-label="напоминания" style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '5px 10px 5px 8px',
      background: 'var(--brand-primary-tint)',
      border: '1px solid rgba(122,156,122,0.25)',
      borderRadius: 999, cursor: 'pointer',
      color: 'var(--brand-primary-press)',
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,90,60,0.06)',
    }}>
      {React.cloneElement(ExtraIcons.clock, { size: 14, sw: 1.6 })}
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
        letterSpacing: '.04em',
      }}>{count}</span>
    </button>
  );
}

/* ─── filter chips row · sticky · h-scroll ───────────────── */
function FilterChipsRow({ active, onChange }) {
  const items = [
    { id: 'all',   label: 'все' },
    { id: 'fav',   glyph: '★', label: '' },
    { id: 'task',  label: 'задачи' },
    { id: 'voice', label: 'голос' },
  ];

  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 4,
      padding: '8px 16px 10px',
      marginBottom: 4,
      background: 'linear-gradient(180deg, rgba(247,243,233,0.92) 0%, rgba(247,243,233,0.85) 70%, rgba(247,243,233,0) 100%)',
      backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
      display: 'flex', gap: 6, overflowX: 'auto', scrollbarWidth: 'none',
    }}>
      {items.map(it => {
        const on = active === it.id;
        return (
          <button key={it.id} onClick={() => onChange(it.id)} style={{
            flexShrink: 0,
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '7px 14px', borderRadius: 999,
            fontFamily: 'var(--font-ui)', fontSize: 12.5, fontWeight: 500,
            letterSpacing: '-0.005em',
            background: on ? 'var(--brand-primary)' : 'rgba(255,252,246,0.55)',
            color: on ? 'var(--fg-on-brand)' : 'var(--fg-2)',
            border: on ? 'none' : '1px solid rgba(255,255,255,0.6)',
            backdropFilter: on ? 'none' : 'blur(12px)',
            WebkitBackdropFilter: on ? 'none' : 'blur(12px)',
            boxShadow: on
              ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.22)'
              : '0 1px 0 rgba(255,255,255,0.6) inset, 0 1px 3px rgba(60,40,25,0.04)',
            cursor: 'pointer',
          }}>
            {it.glyph && (
              <Glyph ch={it.glyph} size={13}
                color={on ? 'currentColor' : 'var(--brand-primary)'}/>
            )}
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

/* chat-mode list filtered (mocked) */
function FilteredChatView({ filter, onLongPress }) {
  const all = [
    { kind:'chat', avatar:{ kind:'letter', tone:'sage', letter:'A' },
      name:'Anthropic · AI safety', time:'14:32',
      preview:<>«модели должны быть честными по умолчанию»</>,
      src:'x.com', star:true, types:['fav'] },
    { kind:'chat', avatar:{ kind:'letter', tone:'honey', letter:'K' },
      name:'@karpathy · rlhf evolution', time:'12:08',
      preview:<>от InstructGPT через DPO к нынешним методам</>,
      src:'x.com', types:[] },
    { kind:'chat', avatar:{ kind:'task' },
      name:'список покупок', time:'вчера',
      preview:<><b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>1/3</b> · хлеб, пылесос</>,
      src:'task', done:true, types:['task'] },
    { kind:'sep', label:'вчера' },
    { kind:'chat', avatar:{ kind:'icon', tone:'clay', icon: React.cloneElement(ExtraIcons.mic, { size:20, sw:1.6 }) },
      name:'голосовая · 0:47', time:'19:04',
      preview:<>«не забыть купить корм для рыбок»</>,
      src:'voice', types:['voice'] },
    { kind:'chat', avatar:{ kind:'letter', tone:'slate', letter:'D' },
      name:'DPO paper', time:'10:15',
      preview:<>Direct Preference Optimization без reward model</>,
      src:'arxiv', pulsing:true, types:[] },
    { kind:'chat', avatar:{ kind:'task' },
      name:'починить кран · кухня', time:'10:02',
      preview:<><b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>0/2</b> · позвонить мастеру</>,
      src:'task', types:['task'] },
    { kind:'chat', avatar:{ kind:'letter', tone:'plum', letter:'К' },
      name:'коллекция · alignment', time:'9:02',
      preview:<><b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>12</b> закладок · открывал 3 дня назад</>,
      star:true, types:['fav'] },
    { kind:'chat', avatar:{ kind:'icon', tone:'moss', icon: React.cloneElement(ExtraIcons.mic, { size:20, sw:1.6 }) },
      name:'голосовая · 1:22', time:'пн',
      preview:<>«идея для эссе про привычки»</>,
      src:'voice', types:['voice'] },
    { kind:'chat', avatar:{ kind:'archive' },
      name:'scaling laws', time:'11 мес',
      preview:<>в архиве · так и не открыл</>,
      src:'arxiv', muted:true, isLast:true, types:[] },
  ];

  const filtered = filter === 'all'
    ? all
    : all.filter(r => r.kind === 'sep' || r.types.includes(filter));

  // collapse stray separators
  const rows = [];
  filtered.forEach((r, i) => {
    if (r.kind === 'sep' && (i === filtered.length - 1 || filtered[i+1]?.kind === 'sep')) return;
    rows.push(r);
  });

  if (rows.filter(r => r.kind === 'chat').length === 0) {
    return <EmptyState glyph="∅" head="ничего по этому фильтру"
              copy={<>сбрось чипы, чтобы увидеть всё</>}/>;
  }

  return (
    <div>
      {rows.map((r, i) => {
        if (r.kind === 'sep') return <DaySeparator key={`s${i}`} label={r.label}/>;
        const last = i === rows.length - 1;
        return (
          <div key={i}
            onContextMenu={e=>{e.preventDefault(); onLongPress && onLongPress(r);}}
          >
            <ChatRow {...r} isLast={last || r.isLast}/>
          </div>
        );
      })}
    </div>
  );
}

function FilteredCardsView({ filter }) {
  const cards = [
    { id:1, title:'Constitutional AI: harmlessness from AI feedback',
      summary:'Метод обучения через набор принципов — без ручной разметки. Самокритика по правилам.',
      url:'anthropic.com', time:'14:32', is_favorite:true,
      tags:[{name:'ai',color:1},{name:'чтиво',color:2}],
      ai_status:'completed', types:['fav'] },
    { id:2, title:'тред @karpathy про эволюцию rlhf',
      summary:'От InstructGPT через DPO к нынешним методам. Andrej считает DPO «проще, но не лучше».',
      url:'x.com', time:'12:08',
      tags:[{name:'ai',color:1},{name:'треды',color:3}],
      ai_status:'completed', types:[] },
    { id:3, title:'список покупок на выходные',
      summary:null, url:'task', time:'вчера',
      tags:[{name:'дом',color:2}], content_type:'task',
      task_progress:{done:1,total:3}, ai_status:'completed', types:['task'] },
    { id:4, title:'голосовая · «корм для рыбок»',
      summary:'Не забыть купить корм перед пятницей. Магазин у метро.',
      url:'voice', time:'19:04',
      tags:[{name:'дом',color:2}], ai_status:'completed', types:['voice'] },
    { id:5, title:'idli · индийские рисовые лепёшки',
      summary:'Замочить на 6 часов, смолоть, ферментировать ночь. Готовить на пару 12 минут.',
      url:'youtube.com', time:'нед.',
      tags:[{name:'рецепты',color:6}],
      ai_status:'completed', types:[] },
  ];
  const f = filter === 'all' ? cards : cards.filter(c => c.types.includes(filter));
  if (f.length === 0) return <EmptyState glyph="∅" head="ничего по этому фильтру" copy="сбрось чипы"/>;
  return (
    <div style={{ padding: '4px 16px 0' }}>
      {f.map(b => <BookmarkCard key={b.id} bookmark={b}/>)}
    </div>
  );
}

function ViewToggle({ view, setView }) {
  const btn = (id, label, icon) => (
    <button onClick={() => setView(id)} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '6px 12px', borderRadius: 999, cursor: 'pointer',
      fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 500, letterSpacing: '-0.005em',
      background: view === id ? 'rgba(255,252,246,0.85)' : 'transparent',
      border: view === id ? '1px solid rgba(255,255,255,0.6)' : '1px solid transparent',
      color: view === id ? 'var(--fg-1)' : 'var(--fg-3)',
      backdropFilter: view === id ? 'blur(12px)' : 'none',
      WebkitBackdropFilter: view === id ? 'blur(12px)' : 'none',
      boxShadow: view === id ? '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)' : 'none',
    }}>
      {React.cloneElement(icon, { size: 14, sw: 1.6 })}
      {label}
    </button>
  );
  return (
    <div style={{
      display: 'inline-flex', gap: 2, padding: 3,
      background: 'rgba(234,227,207,0.4)',
      backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
      borderRadius: 999,
    }}>
      {btn('chat', 'chat', Icons.feed)}
      {btn('cards', 'cards', Icons.cards)}
    </div>
  );
}

Object.assign(window, { MysliScreen, ReminderBell, FilterChipsRow, ViewToggle });
