/* Feed — chat-list primary, card alt. Toggle in header. */

const seedBookmarks = [
  {
    id: 1, title: 'Constitutional AI: harmlessness from AI feedback',
    summary: 'Метод обучения через набор принципов — без ручной разметки. Самокритика по правилам.',
    url: 'anthropic.com', time: '14:32', is_favorite: true,
    tags: [{name:'ai',color:1},{name:'чтиво',color:2}],
    ai_status: 'completed',
  },
  {
    id: 2, title: 'тред @karpathy про эволюцию rlhf',
    summary: 'От InstructGPT через DPO к нынешним методам. Andrej считает DPO «проще, но не лучше».',
    url: 'x.com', time: '12:08',
    tags: [{name:'ai',color:1},{name:'треды',color:3}],
    ai_status: 'completed',
  },
  {
    id: 3, title: 'sana.ai · platform overview',
    summary: null, url: 'sana.ai', time: '2 дня',
    tags: [{name:'дизайн',color:4}],
    ai_status: 'processing',
  },
  {
    id: 4, title: 'список покупок на выходные',
    summary: null, url: 'task', time: 'вчера',
    tags: [{name:'дом',color:2}], content_type: 'task',
    task_progress: { done: 1, total: 3 }, ai_status: 'completed',
  },
  {
    id: 5, title: 'idli · индийские рисовые лепёшки',
    summary: 'Замочить на 6 часов, смолоть, ферментировать ночь. Готовить на пару 12 минут.',
    url: 'youtube.com', time: 'нед.',
    tags: [{name:'рецепты',color:6}],
    ai_status: 'completed',
  },
];

/* chat rows are richer than seedBookmarks — built inline for variety */

function Feed({ onSearch }) {
  const [hideSuggest, setHideSuggest] = React.useState(false);
  const [view, setView] = React.useState('chat'); // chat | cards

  return (
    <div style={{ padding: '6px 0 100px' }}>
      {/* header */}
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        padding: '0 16px', marginBottom: 16, marginTop: 4,
      }}>
        <h1 style={{
          fontSize: 32, fontWeight: 500, letterSpacing: '-0.035em',
          margin: 0, color: 'var(--fg-1)', lineHeight: 1,
        }}>
          лента
          <span style={{
            fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500,
            color: 'var(--brand-primary)', marginLeft: 6, letterSpacing: '-0.01em',
          }}>·</span>
        </h1>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--fg-3)', letterSpacing: '.06em', fontWeight: 500,
        }}>347</span>
      </div>

      {/* search */}
      <div style={{ padding: '0 16px', marginBottom: 16 }}>
        <SearchBar onFocus={onSearch}/>
      </div>

      {/* view toggle */}
      <div style={{
        padding: '0 16px', marginBottom: 14,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <ViewToggle view={view} setView={setView}/>
        <span style={{ flex: 1 }}/>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--fg-3)', letterSpacing: '.12em', textTransform: 'uppercase', fontWeight: 500,
        }}>сегодня</span>
      </div>

      {/* AI suggestions — section with horizontal pager */}
      {!hideSuggest && view === 'chat' && (
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
              text: <>DPO paper связан с тредом @karpathy</>,
              sources: [
                { letter: 'D', tone: 'slate', domain: 'arxiv.org' },
                { letter: 'K', tone: 'honey', domain: 'x.com' },
              ],
              meta: 'связать?',
            },
          ]}
          onDismissAll={() => setHideSuggest(true)}
        />
      )}

      {/* main view */}
      {view === 'chat' ? <ChatView/> : <CardsView/>}
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

function ChatView() {
  return (
    <div>
      <ChatRow
        avatar={{ kind: 'letter', tone: 'sage', letter: 'A' }}
        name="Anthropic · AI safety"
        time="14:32"
        preview={<>«модели должны быть честными по умолчанию»</>}
        src="x.com"
        star
      />
      <ChatRow
        avatar={{ kind: 'letter', tone: 'honey', letter: 'K' }}
        name="@karpathy · rlhf evolution"
        time="12:08"
        preview={<>От InstructGPT через DPO к нынешним методам</>}
        src="x.com"
      />
      <ChatRow
        avatar={{ kind: 'task' }}
        name="список покупок"
        time="вчера"
        preview={<><b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>1/3</b> · хлеб, пылесос</>}
        src="task"
        done
      />
      <DaySeparator label="вчера"/>
      <ChatRow
        avatar={{ kind: 'letter', tone: 'slate', letter: 'D' }}
        name="DPO paper"
        time="10:15"
        preview={<>Direct Preference Optimization без reward model</>}
        src="arxiv"
        pulsing
      />
      <ChatRow
        avatar={{ kind: 'letter', tone: 'plum', letter: 'К' }}
        name="коллекция · alignment"
        time="9:02"
        preview={<><b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>12</b> закладок · открывал 3 дня назад</>}
      />
      <ChatRow
        avatar={{ kind: 'letter', tone: 'clay', letter: 'P' }}
        name="Pinterest · ceramics"
        time="чт"
        preview={<>moodboard, 24 изображения</>}
        src="pin"
      />
      <ChatRow
        avatar={{ kind: 'archive' }}
        name="scaling laws"
        time="11 мес"
        preview={<>в архиве · так и не открыл</>}
        src="arxiv"
        muted
        isLast
      />
    </div>
  );
}

function CardsView() {
  return (
    <div style={{ padding: '0 16px' }}>
      {seedBookmarks.map(b => <BookmarkCard key={b.id} bookmark={b}/>)}
    </div>
  );
}

Object.assign(window, { Feed, seedBookmarks, ChatView, CardsView, ViewToggle });
