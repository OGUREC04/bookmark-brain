/* Canvas — lays out the 9 hifi reference frames.
   Sections:
   · Экраны (4)
   · Шторы / Sheets (5)
   · Состояния Мыслей (variations of screen 1) */

function App() {
  React.useEffect(() => {
    document.body.setAttribute('data-theme', 'echo');
  }, []);

  return (
    <DesignCanvas
      title="BookmarkBrain · Mini App"
      subtitle="hifi reference · 4 screens + 5 sheets · DS v1 (echo, sage anchor)"
    >
      <DCSection id="screens" title="Экраны">
        <DCArtboard id="s1" label="01 · Мысли (главный)" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="s2" label="02 · Поиск (из search-bar)" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <SearchScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="s3" label="03 · Пространства" width={400} height={820}>
          <PhoneFrame nav="spaces">
            <SpacesScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="s4" label="04 · Я" width={400} height={820}>
          <PhoneFrame nav="me">
            <MeScreen/>
          </PhoneFrame>
        </DCArtboard>
      </DCSection>

      <DCSection id="sheets" title="Шторки (T8–T13)">
        <DCArtboard id="sh1" label="ActionSheet · long-press карточки" width={400} height={820}>
          <PhoneFrame nav="mysli" sheet={<ActionSheet/>}>
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="sh2" label="RemindersSheet · колокольчик" width={400} height={820}>
          <PhoneFrame nav="mysli" sheet={<RemindersSheet/>}>
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="sh3" label="ReminderPickerSheet" width={400} height={820}>
          <PhoneFrame nav="mysli" sheet={<ReminderPickerSheet/>}>
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="sh4" label="MoveToSpaceSheet" width={400} height={820}>
          <PhoneFrame nav="mysli" sheet={<MoveToSpaceSheet/>}>
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="sh5" label="QuickCreateSheet · FAB+" width={400} height={820}>
          <PhoneFrame nav="mysli" sheet={<QuickCreateSheet/>}>
            <MysliScreen/>
          </PhoneFrame>
        </DCArtboard>
      </DCSection>

      <DCSection id="variants" title="Мысли · состояния">
        <DCArtboard id="v1" label="Чипы · только задачи" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <MysliVariant initialFilter="task"/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="v2" label="Чипы · только голос" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <MysliVariant initialFilter="voice"/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="v3" label="Режим cards" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <MysliVariant initialView="cards"/>
          </PhoneFrame>
        </DCArtboard>

        <DCArtboard id="v4" label="Empty · фильтр пустой" width={400} height={820}>
          <PhoneFrame nav="mysli">
            <MysliVariant initialFilter="task" emptyOverride/>
          </PhoneFrame>
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

/* Variant of MysliScreen with preset initial state for the variants section. */
function MysliVariant({ initialFilter = 'all', initialView = 'chat', emptyOverride = false }) {
  // We just re-render MysliScreen but seed React state via key+initial props.
  // Simpler: clone MysliScreen with overrides. The original uses useState — we
  // create a tiny wrapper that mounts it with a key change.
  return <MysliWithDefaults initialFilter={emptyOverride ? 'fav' : initialFilter}
                            initialView={initialView}
                            emptyOverride={emptyOverride}/>;
}

/* fork of MysliScreen with seeded state (kept inline to avoid duplicating chat data) */
function MysliWithDefaults({ initialFilter, initialView, emptyOverride }) {
  const [view, setView] = React.useState(initialView);
  const [filter, setFilter] = React.useState(initialFilter);
  const [hideSuggest, setHideSuggest] = React.useState(true); // hide in variants

  return (
    <div style={{ padding: '6px 0 100px' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', marginBottom: 14, marginTop: 4, gap: 10,
      }}>
        <h1 style={{ fontSize: 32, fontWeight: 500, letterSpacing: '-0.035em', margin: 0, color: 'var(--fg-1)', lineHeight: 1 }}>
          мысли
          <span style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500, color: 'var(--brand-primary)', marginLeft: 6 }}>·</span>
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ReminderBell count={3}/>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)', letterSpacing: '.06em', fontWeight: 500 }}>347</span>
        </div>
      </div>
      <div style={{ padding: '0 16px', marginBottom: 14 }}>
        <SearchBar/>
      </div>
      <div style={{ padding: '0 16px', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
        <ViewToggle view={view} setView={setView}/>
        <span style={{ flex: 1 }}/>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--fg-3)', letterSpacing: '.12em', textTransform: 'uppercase', fontWeight: 500 }}>сегодня</span>
      </div>
      <FilterChipsRow active={filter} onChange={setFilter}/>
      {emptyOverride
        ? <EmptyState glyph="∅" head="ничего не подошло" copy={<>сбрось чипы<br/>чтобы увидеть всё</>}/>
        : (view === 'chat' ? <FilteredChatView filter={filter}/> : <FilteredCardsView filter={filter}/>)
      }
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);

Object.assign(window, { App, MysliVariant });
