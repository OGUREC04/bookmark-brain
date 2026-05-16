/* Screens — Search, Tags, Me */

const seedTags = [
  { name:'ai',         count:47, color:1 },
  { name:'чтиво',      count:38, color:2 },
  { name:'видео',      count:24, color:3 },
  { name:'работа',     count:19, color:4 },
  { name:'дом',        count:14, color:2 },
  { name:'рецепты',    count:11, color:6 },
  { name:'идеи',       count:9,  color:7 },
  { name:'anthropic',  count:7,  color:1 },
  { name:'треды',      count:6,  color:3 },
  { name:'дизайн',     count:5,  color:4 },
];

function SearchView({ onBack }) {
  const [q, setQ] = React.useState('конституционный ai');
  const hasQuery = q.trim().length > 0;
  const matches = q.toLowerCase().includes('конст') || q.toLowerCase().includes('const');

  return (
    <div style={{ padding: '6px 0 100px' }}>
      {/* nav */}
      <div style={{
        padding: '0 16px', display: 'flex', alignItems: 'center', gap: 10,
        marginBottom: 12,
      }}>
        <button onClick={onBack} style={{
          background: 'rgba(255,252,246,0.7)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.6)',
          width: 36, height: 36, borderRadius: '50%',
          color: 'var(--fg-1)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)',
        }}>{React.cloneElement(Icons.back, { size: 16, sw: 1.6 })}</button>
        <h2 style={{
          fontSize: 22, fontWeight: 500, letterSpacing: '-0.03em',
          margin: 0, color: 'var(--fg-1)',
        }}>поиск</h2>
      </div>

      {/* field */}
      <div style={{ padding: '0 16px', marginBottom: 14 }}>
        <SearchBar value={q} onChange={setQ} focused/>
      </div>

      {/* facets */}
      {hasQuery && (
        <div style={{
          padding: '0 16px', display: 'flex', gap: 6, flexWrap: 'wrap',
          marginBottom: 12,
        }}>
          <FacetPill label="все" count={matches ? 2 : 0} on/>
          <FacetPill label="ai" count={3}/>
          <FacetPill label="статьи" count={2}/>
          <FacetPill label="за неделю"/>
        </div>
      )}

      {/* hint */}
      {hasQuery && matches && (
        <div style={{
          padding: '0 20px', marginBottom: 10,
          display: 'flex', alignItems: 'center', gap: 8,
          fontFamily: 'var(--font-display)', fontStyle: 'italic',
          fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.4, letterSpacing: 0,
        }}>
          <Glyph ch="✦" size={14}/>
          <span>найдено по смыслу · <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>«constitutional»</b> ≈ <b style={{fontFamily:'var(--font-ui)',fontStyle:'normal',fontWeight:500,color:'var(--fg-1)'}}>«конституционный»</b></span>
        </div>
      )}

      {/* results */}
      {hasQuery && matches ? (
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
      ) : hasQuery ? (
        <EmptyState
          glyph="∅"
          head="ничего не нашлось"
          copy={<>попробуй другие слова<br/>или сними фильтры</>}
        />
      ) : (
        <EmptyState
          glyph="?"
          head="спроси что-нибудь"
          copy={<>«анализ rlhf» · «рецепт идли»<br/>«про что был тот тред»</>}
        />
      )}
    </div>
  );
}

function FacetPill({ label, count, on }) {
  return (
    <span style={{
      padding: '7px 13px', borderRadius: 999,
      fontFamily: 'var(--font-ui)', fontSize: 12.5, fontWeight: 500,
      letterSpacing: '-0.005em',
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: on ? 'var(--brand-primary)' : 'rgba(255,252,246,0.55)',
      color: on ? 'var(--fg-on-brand)' : 'var(--fg-2)',
      border: on ? 'none' : '1px solid rgba(255,255,255,0.6)',
      backdropFilter: on ? 'none' : 'blur(12px)',
      WebkitBackdropFilter: on ? 'none' : 'blur(12px)',
      boxShadow: on
        ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.2)'
        : 'none',
      cursor: 'pointer',
    }}>
      {label}
      {count != null && (
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          letterSpacing: '.06em', opacity: 0.7,
        }}>{count}</span>
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
        <span style={{
          color: 'var(--fg-2)', fontWeight: 500, fontFamily: 'var(--font-ui)',
          fontSize: 11, letterSpacing: 0, textTransform: 'lowercase',
        }}>{src}</span>
        <span style={{ width: 2.5, height: 2.5, borderRadius: '50%', background: 'var(--fg-4)' }}/>
        <span>{time}</span>
        {saved && (<>
          <span style={{ width: 2.5, height: 2.5, borderRadius: '50%', background: 'var(--fg-4)' }}/>
          <span>{saved}</span>
        </>)}
      </div>
      <div style={{
        fontSize: 15.5, fontWeight: 500, letterSpacing: '-0.02em',
        lineHeight: 1.25, marginBottom: 6, color: 'var(--fg-1)',
      }}>{title}</div>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
        fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.4, letterSpacing: 0,
      }}>{summary}</div>
    </div>
  );
}

function TagsView() {
  return (
    <div style={{ padding: '6px 16px 100px' }}>
      <div style={{ marginBottom: 4, marginTop: 4 }}>
        <h1 style={{
          fontSize: 32, fontWeight: 500, letterSpacing: '-0.035em',
          margin: 0, color: 'var(--fg-1)', lineHeight: 1,
        }}>теги</h1>
      </div>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
        fontSize: 14, color: 'var(--fg-2)', margin: '8px 0 18px', letterSpacing: 0, lineHeight: 1.4,
      }}>10 тегов · AI добавляет автоматически</div>

      <div style={{
        background: 'rgba(255,252,246,0.72)',
        backdropFilter: 'blur(20px) saturate(160%)',
        WebkitBackdropFilter: 'blur(20px) saturate(160%)',
        border: '1px solid rgba(255,255,255,0.6)',
        borderRadius: 22, overflow: 'hidden',
        boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)',
      }}>
        {seedTags.map((t, i) => (
          <div key={t.name} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '13px 16px',
            borderBottom: i < seedTags.length - 1 ? '1px solid var(--border-1)' : 'none',
            cursor: 'pointer',
          }}>
            <TagChip name={t.name} color={t.color}/>
            <span style={{ flex: 1 }}/>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--fg-3)', letterSpacing: '.06em',
            }}>{t.count}</span>
            <span style={{ color: 'var(--fg-4)', display: 'flex' }}>
              {React.cloneElement(Icons.arrow, { size: 14, sw: 1.6 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MeView() {
  return (
    <div style={{ padding: '6px 16px 100px' }}>
      <h1 style={{
        fontSize: 32, fontWeight: 500, letterSpacing: '-0.035em',
        margin: '4px 0 16px', color: 'var(--fg-1)', lineHeight: 1,
      }}>я</h1>

      {/* profile card */}
      <div style={{
        background: 'rgba(255,252,246,0.72)',
        backdropFilter: 'blur(20px) saturate(160%)',
        WebkitBackdropFilter: 'blur(20px) saturate(160%)',
        border: '1px solid rgba(255,255,255,0.6)',
        borderRadius: 22, padding: 16,
        display: 'flex', gap: 14, alignItems: 'center',
        marginBottom: 10,
        boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)',
      }}>
        <div style={{
          width: 52, height: 52, borderRadius: '50%',
          background: 'var(--brand-primary-tint)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.06)',
        }}>
          <Glyph ch="э" size={30}/>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 500, letterSpacing: '-0.02em', color: 'var(--fg-1)' }}>@durov</div>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--fg-3)', letterSpacing: '.06em', marginTop: 2,
          }}>347 закладок · с янв 2024</div>
        </div>
      </div>

      {/* stats glass row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 16 }}>
        <Stat n="347" l="всего"/>
        <Stat n="12" l="на неделе"/>
        <Stat n="4" l="прочитал"/>
      </div>

      {/* settings */}
      <div style={{
        background: 'rgba(255,252,246,0.72)',
        backdropFilter: 'blur(20px) saturate(160%)',
        WebkitBackdropFilter: 'blur(20px) saturate(160%)',
        border: '1px solid rgba(255,255,255,0.6)',
        borderRadius: 22, overflow: 'hidden', marginBottom: 16,
        boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 10px 30px rgba(60,40,25,0.06)',
      }}>
        {[
          { l: 'уведомления',         r: 'редко' },
          { l: 'AI-подсказки',        r: 'вкл' },
          { l: 'архивировать через',  r: '90 дней' },
          { l: 'экспорт в Markdown',  r: '→' },
          { l: 'подключить Notion',   r: '→' },
        ].map((it, i, arr) => (
          <div key={it.l} style={{
            display: 'flex', alignItems: 'center',
            padding: '14px 16px',
            borderBottom: i < arr.length - 1 ? '1px solid var(--border-1)' : 'none',
            fontSize: 14.5, letterSpacing: '-0.01em',
          }}>
            <span style={{ flex: 1, color: 'var(--fg-1)' }}>{it.l}</span>
            <span style={{
              fontFamily: it.r === '→' ? 'var(--font-ui)' : 'var(--font-mono)',
              fontSize: it.r === '→' ? 14 : 11, color: 'var(--fg-3)',
              letterSpacing: '.04em',
            }}>{it.r}</span>
          </div>
        ))}
      </div>

      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic',
        fontSize: 12.5, color: 'var(--fg-3)', textAlign: 'center', letterSpacing: 0,
      }}>v0.4 · собрано вручную</div>
    </div>
  );
}

function Stat({ n, l }) {
  return (
    <div style={{
      background: 'rgba(255,252,246,0.55)',
      backdropFilter: 'blur(16px) saturate(140%)',
      WebkitBackdropFilter: 'blur(16px) saturate(140%)',
      border: '1px solid rgba(255,255,255,0.6)',
      borderRadius: 16, padding: '14px 8px', textAlign: 'center',
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 12px rgba(60,40,25,0.04)',
    }}>
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500,
        fontSize: 28, color: 'var(--brand-primary)', lineHeight: 1, letterSpacing: '-0.01em',
      }}>{n}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10,
        color: 'var(--fg-3)', letterSpacing: '.08em', textTransform: 'uppercase',
        marginTop: 6, fontWeight: 500,
      }}>{l}</div>
    </div>
  );
}

Object.assign(window, { SearchView, TagsView, MeView, seedTags, Stat });
