/* ЭКРАН 2 — Поиск.  Same SearchBar as Мысли, focused. */

function SearchScreen({ onBack }) {
  const [q, setQ] = React.useState('конституционный ai');
  const hasQuery = q.trim().length > 0;
  const matches = q.toLowerCase().includes('конст') || q.toLowerCase().includes('const');

  return (
    <div style={{ padding: '6px 0 100px' }}>
      {/* nav — telegram-style back affordance is system-level; we just keep a chevron pill */}
      <div style={{ padding: '0 16px', display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <button onClick={onBack} style={{
          background: 'rgba(255,252,246,0.7)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.6)',
          width: 36, height: 36, borderRadius: '50%',
          color: 'var(--fg-1)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)',
        }}>{React.cloneElement(Icons.back, { size: 16, sw: 1.6 })}</button>
        <h2 style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.03em', margin: 0, color: 'var(--fg-1)' }}>поиск</h2>
      </div>

      <div style={{ padding: '0 16px', marginBottom: 14 }}>
        <SearchBar value={q} onChange={setQ} focused/>
      </div>

      {hasQuery && (
        <div style={{ padding: '0 16px', display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <FacetPill label="все" count={matches ? 2 : 0} on/>
          <FacetPill label="ai" count={3}/>
          <FacetPill label="статьи" count={2}/>
          <FacetPill label="за неделю"/>
        </div>
      )}

      {hasQuery && matches && (
        <>
          <div style={{
            padding: '0 20px', marginBottom: 12,
            display: 'flex', alignItems: 'flex-start', gap: 8,
            fontFamily: 'var(--font-display)', fontStyle: 'italic',
            fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.4, letterSpacing: 0,
          }}>
            <Glyph ch="✦" size={14} style={{ marginTop: 2 }}/>
            <span>найдено по смыслу · <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>«constitutional»</b> ≈ <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>«конституционный»</b></span>
          </div>

          {/* AI-summary block · sage tint */}
          <div style={{
            margin: '0 16px 12px',
            background: 'linear-gradient(160deg, rgba(226,237,226,0.7) 0%, rgba(207,223,207,0.55) 100%)',
            backdropFilter: 'blur(18px) saturate(150%)',
            WebkitBackdropFilter: 'blur(18px) saturate(150%)',
            border: '1px solid rgba(207,223,207,0.7)',
            borderRadius: 18, padding: '14px 16px',
            boxShadow: '0 1px 0 rgba(255,255,255,0.5) inset, 0 4px 14px rgba(60,90,60,0.06)',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.14em',
              textTransform: 'uppercase', color: 'var(--ai-suggest-fg)', fontWeight: 500,
            }}>
              <Glyph ch="✦" size={12}/> ответ по сохранённому
            </div>
            <p style={{
              margin: 0,
              fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
              fontSize: 14.5, color: 'var(--fg-1)', lineHeight: 1.45, letterSpacing: 0,
            }}>
              «У тебя 2 сохранения про constitutional AI — статья Anthropic и тред Карпатого.
              Метод обучает через принципы вместо разметки.»
            </p>
            <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
              <SourceChip letter="A" tone="sage"  domain="anthropic.com"/>
              <SourceChip letter="K" tone="honey" domain="x.com"/>
            </div>
          </div>

          <div style={{ padding: '0 16px' }}>
            <SearchResult
              src="anthropic.com" time="14:32" saved="сохранено вчера"
              title={<><mark style={{ background: 'var(--brand-primary-tint)', color: 'var(--brand-primary-press)', padding: '1px 4px', borderRadius: 5 }}>constitutional</mark> ai: harmlessness from <mark style={{ background: 'var(--brand-primary-tint)', color: 'var(--brand-primary-press)', padding: '1px 4px', borderRadius: 5 }}>ai</mark> feedback</>}
              summary="«Метод обучения моделей через набор принципов — без ручной разметки. Самокритика по правилам.»"
            />
            <SearchResult
              src="x.com" time="вчера"
              title="тред @karpathy про эволюцию rlhf"
              summary="От InstructGPT через DPO к нынешним методам — короткая хронология."
            />
          </div>
        </>
      )}

      {!hasQuery && (
        <EmptyState glyph="?" head="о чём подумать?"
          copy={<>«анализ rlhf» · «рецепт идли»<br/>«про что был тот тред»</>}/>
      )}
      {hasQuery && !matches && (
        <EmptyState glyph="∅" head="ничего не нашлось"
          copy={<>попробуй другие слова<br/>или сними фильтры</>}/>
      )}
    </div>
  );
}

function FacetPill({ label, count, on }) {
  return (
    <span style={{
      padding: '7px 13px', borderRadius: 999,
      fontFamily: 'var(--font-ui)', fontSize: 12.5, fontWeight: 500, letterSpacing: '-0.005em',
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: on ? 'var(--brand-primary)' : 'rgba(255,252,246,0.55)',
      color: on ? 'var(--fg-on-brand)' : 'var(--fg-2)',
      border: on ? 'none' : '1px solid rgba(255,255,255,0.6)',
      backdropFilter: on ? 'none' : 'blur(12px)',
      WebkitBackdropFilter: on ? 'none' : 'blur(12px)',
      boxShadow: on ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.2)' : 'none',
      cursor: 'pointer',
    }}>
      {label}
      {count != null && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.06em', opacity: 0.7 }}>{count}</span>
      )}
    </span>
  );
}

function SearchResult({ src, time, saved, title, summary }) {
  return (
    <div style={{
      background: 'rgba(255,252,246,0.72)',
      backdropFilter: 'blur(20px) saturate(160%)',
      WebkitBackdropFilter: 'blur(20px) saturate(160%)',
      border: '1px solid rgba(255,255,255,0.6)',
      borderRadius: 20, padding: '16px 18px', marginBottom: 8,
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 -1px 0 rgba(0,0,0,0.04) inset, 0 6px 18px rgba(60,40,25,0.05)',
      cursor: 'pointer',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10.5,
        color: 'var(--fg-3)', letterSpacing: '.06em', marginBottom: 6,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ color: 'var(--fg-2)', fontWeight: 500, fontFamily: 'var(--font-ui)', fontSize: 11, letterSpacing: 0, textTransform: 'lowercase' }}>{src}</span>
        <span style={{ width: 2.5, height: 2.5, borderRadius: '50%', background: 'var(--fg-4)' }}/>
        <span>{time}</span>
        {saved && (<>
          <span style={{ width: 2.5, height: 2.5, borderRadius: '50%', background: 'var(--fg-4)' }}/>
          <span>{saved}</span>
        </>)}
      </div>
      <div style={{ fontSize: 15.5, fontWeight: 500, letterSpacing: '-0.02em', lineHeight: 1.25, marginBottom: 6, color: 'var(--fg-1)' }}>{title}</div>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
        fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.4, letterSpacing: 0,
      }}>{summary}</div>
    </div>
  );
}

Object.assign(window, { SearchScreen, FacetPill, SearchResult });
