/* SuggestionCard — frosted sage tile · editorial italic headline */

function SuggestionCard({ kind='cluster', text, headline, refs=[], onAccept, onDismiss, onSnooze }) {
  /* text can be JSX (with <b>) or string */
  return (
    <div style={{
      position: 'relative', overflow: 'hidden',
      background: 'linear-gradient(160deg, rgba(226,237,226,0.85) 0%, rgba(207,223,207,0.7) 100%)',
      backdropFilter: 'blur(20px) saturate(160%)',
      WebkitBackdropFilter: 'blur(20px) saturate(160%)',
      border: '1px solid rgba(207,223,207,0.7)',
      borderRadius: 22, padding: '18px 20px 16px',
      marginBottom: 12,
      boxShadow: '0 1px 0 rgba(255,255,255,0.5) inset, 0 8px 24px rgba(60,90,60,0.08)',
    }}>
      {/* sage halo */}
      <div style={{
        position: 'absolute', top: '-40%', right: '-20%',
        width: 240, height: 240, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(122,156,122,0.18) 0%, transparent 70%)',
        pointerEvents: 'none',
      }}/>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12,
        position: 'relative',
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%',
          background: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,90,60,0.12)',
        }}>
          <Glyph ch="✦" size={16}/>
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          letterSpacing: '.14em', textTransform: 'uppercase',
          color: 'var(--ai-suggest-fg)', fontWeight: 500,
        }}>brain suggests</div>
        <button onClick={onDismiss} style={{
          marginLeft: 'auto',
          background: 'rgba(255,255,255,0.5)', border: 'none',
          width: 26, height: 26, borderRadius: '50%',
          color: 'var(--fg-3)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{React.cloneElement(Icons.close, { size: 13, sw: 1.8 })}</button>
      </div>

      {/* editorial italic headline */}
      <div style={{
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500,
        fontSize: 22, lineHeight: 1.15, letterSpacing: '-0.005em',
        color: 'var(--fg-1)', marginBottom: refs.length ? 14 : 16,
        position: 'relative', maxWidth: '32ch',
      }}>{headline || text}</div>

      {refs.length > 0 && (
        <div style={{
          background: 'rgba(255,252,246,0.7)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.6)',
          borderRadius: 14, padding: '6px 4px',
          marginBottom: 14, position: 'relative',
        }}>
          {refs.map((r, i) => (
            <div key={i} style={{
              fontSize: 13, color: 'var(--fg-2)', padding: '7px 12px',
              display: 'flex', gap: 10, alignItems: 'center',
              letterSpacing: '-0.005em',
              borderTop: i > 0 ? '1px solid var(--border-1)' : 'none',
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--brand-primary)', letterSpacing: '.06em', minWidth: 18,
              }}>{String(i+1).padStart(2,'0')}</span>
              <span style={{ flex: 1 }}>{r.title || r}</span>
              {r.src && <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--fg-3)', letterSpacing: '.06em', textTransform: 'uppercase',
              }}>{r.src}</span>}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, position: 'relative' }}>
        <button onClick={onAccept} style={{
          background: 'var(--brand-primary)', color: 'var(--fg-on-brand)',
          border: 'none', padding: '10px 18px', borderRadius: 999,
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          fontFamily: 'var(--font-ui)', letterSpacing: '-0.005em',
          boxShadow: '0 1px 0 rgba(255,255,255,0.2) inset, 0 4px 12px rgba(122,156,122,0.25)',
        }}>показать</button>
        <button onClick={onSnooze} style={{
          background: 'rgba(255,252,246,0.7)', color: 'var(--fg-1)',
          border: '1px solid rgba(255,255,255,0.6)',
          padding: '10px 18px', borderRadius: 999,
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          fontFamily: 'var(--font-ui)', letterSpacing: '-0.005em',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        }}>позже</button>
      </div>
    </div>
  );
}

/* Inline recall — single-line glass tile */
function RecallTile({ text, onClick }) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '14px 16px', marginBottom: 8, cursor: 'pointer',
      background: 'rgba(255,252,246,0.55)',
      backdropFilter: 'blur(16px) saturate(140%)',
      WebkitBackdropFilter: 'blur(16px) saturate(140%)',
      border: '1px solid rgba(255,255,255,0.6)',
      borderRadius: 18,
      boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 12px rgba(60,40,25,0.05)',
    }}>
      <div style={{
        width: 26, height: 26, borderRadius: '50%',
        background: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        <Glyph ch="✦" size={14}/>
      </div>
      <div style={{
        flex: 1, minWidth: 0,
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
        fontSize: 14, color: 'var(--fg-1)', lineHeight: 1.35, letterSpacing: 0,
      }}>{text}</div>
      <button style={{
        flexShrink: 0, width: 30, height: 30, borderRadius: '50%',
        background: 'rgba(255,252,246,0.9)',
        border: '1px solid rgba(255,255,255,0.6)',
        color: 'var(--brand-primary)', cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 2px 6px rgba(60,40,25,0.05)',
      }}>{React.cloneElement(Icons.arrow, { size: 14, sw: 1.6 })}</button>
    </div>
  );
}

Object.assign(window, { SuggestionCard, RecallTile, SuggestionCompact, SuggestionPager });

/* ─── SuggestionPager ───────────────────────────────────
   Houzz / Riot pattern:
   cards peek ~14% on the right so swipe affordance is obvious.
   Each card has italic headline + source chips + meta footer.
*/
function SuggestionPager({ items, onDismissAll }) {
  const [idx, setIdx] = React.useState(0);
  const scrollerRef = React.useRef(null);

  const onScroll = () => {
    const el = scrollerRef.current; if (!el) return;
    const child = el.firstElementChild;
    if (!child) return;
    const step = child.getBoundingClientRect().width + 10; // card width + gap
    const i = Math.round(el.scrollLeft / step);
    if (i !== idx) setIdx(Math.min(items.length - 1, Math.max(0, i)));
  };

  return (
    <div style={{ marginBottom: 16 }}>
      {/* section header — sits on 16px rail */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '0 16px', marginBottom: 10,
      }}>
        <div style={{
          fontFamily: 'var(--font-ui)', fontSize: 11,
          letterSpacing: '.12em', textTransform: 'uppercase',
          color: 'var(--ai-suggest-fg)', fontWeight: 500,
        }}>
          подсказки
        </div>
        <span style={{ flex: 1 }}/>
        {items.length > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            {items.map((_, i) => (
              <span key={i} style={{
                width: i === idx ? 14 : 5, height: 5,
                borderRadius: 999,
                background: i === idx ? 'var(--brand-primary)' : 'var(--fg-4)',
                opacity: i === idx ? 1 : 0.5,
                transition: 'width 240ms var(--ease-out), opacity 240ms',
              }}/>
            ))}
          </div>
        )}
      </div>

      {/* scroller — cards 86% wide so next peeks 14% on right */}
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        style={{
          display: 'flex', gap: 10,
          overflowX: 'auto', overflowY: 'hidden',
          scrollSnapType: 'x mandatory',
          padding: '0 16px 4px',
          scrollPaddingLeft: 16,
          scrollbarWidth: 'none',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {items.map((item, i) => (
          <SuggestionSlide key={i} {...item}/>
        ))}
      </div>
    </div>
  );
}

function SuggestionSlide({ text, sources=[], meta, onAccept }) {
  return (
    <div style={{
      flexShrink: 0,
      // 86% of the scroller's content box — leaves 14% peek on the right
      width: 'calc(86% - 16px * 0.86)',
      minWidth: 280, maxWidth: 340,
      scrollSnapAlign: 'start', scrollSnapStop: 'always',
      position: 'relative', overflow: 'hidden',
      background: 'linear-gradient(160deg, rgba(226,237,226,0.88) 0%, rgba(207,223,207,0.75) 100%)',
      backdropFilter: 'blur(20px) saturate(160%)',
      WebkitBackdropFilter: 'blur(20px) saturate(160%)',
      border: '1px solid rgba(207,223,207,0.7)',
      borderRadius: 22,
      padding: '18px 18px 16px',
      boxShadow: '0 1px 0 rgba(255,255,255,0.5) inset, 0 8px 22px rgba(60,90,60,0.08)',
      display: 'flex', flexDirection: 'column', gap: 14,
    }}>
      {/* sage halo */}
      <div style={{
        position: 'absolute', top: '-50%', right: '-25%',
        width: 220, height: 220, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(122,156,122,0.18) 0%, transparent 70%)',
        pointerEvents: 'none',
      }}/>

      {/* italic headline */}
      <div style={{
        position: 'relative',
        fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 500,
        fontSize: 19, color: 'var(--fg-1)', lineHeight: 1.25, letterSpacing: '-0.005em',
      }}>{text}</div>

      {/* source chips */}
      {sources.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          position: 'relative', flexWrap: 'nowrap', overflow: 'hidden',
        }}>
          {sources.slice(0, 3).map((s, i) => <SourceChip key={i} {...s}/>)}
          {sources.length > 3 && (
            <span style={{
              flexShrink: 0,
              fontFamily: 'var(--font-mono)', fontSize: 10.5,
              color: 'var(--ai-suggest-fg)', letterSpacing: '.06em',
              padding: '4px 8px', borderRadius: 999,
              background: 'rgba(255,252,246,0.6)',
              border: '1px solid rgba(255,255,255,0.6)',
            }}>+{sources.length - 3}</span>
          )}
        </div>
      )}

      {/* footer — meta on left, arrow on right */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        marginTop: 'auto', position: 'relative',
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10.5,
          color: 'var(--ai-suggest-fg)', letterSpacing: '.08em',
          textTransform: 'uppercase', fontWeight: 500,
        }}>{meta || `${sources.length} ${sources.length === 1 ? 'ссылка' : 'ссылки'}`}</span>
        <span style={{ flex: 1 }}/>
        <button onClick={onAccept} aria-label="показать" style={{
          flexShrink: 0,
          background: 'rgba(255,252,246,0.92)',
          backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(255,255,255,0.7)',
          width: 34, height: 34, borderRadius: '50%',
          color: 'var(--brand-primary)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.7) inset, 0 3px 10px rgba(60,90,60,0.12)',
        }}>{React.cloneElement(Icons.arrow, { size: 15, sw: 1.8 })}</button>
      </div>
    </div>
  );
}

function SourceChip({ letter, tone='sage', domain }) {
  const grads = {
    sage:  'linear-gradient(135deg, #8FA888 0%, #4A6648 100%)',
    honey: 'linear-gradient(135deg, #DAC8B0 0%, #B8946A 100%)',
    slate: 'linear-gradient(135deg, #9BB0BE 0%, #4F6A7A 100%)',
    plum:  'linear-gradient(135deg, #B5A8C0 0%, #6E5A80 100%)',
    clay:  'linear-gradient(135deg, #D9907F 0%, #A04934 100%)',
  };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 10px 3px 3px', borderRadius: 999,
      background: 'rgba(255,252,246,0.7)',
      backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
      border: '1px solid rgba(255,255,255,0.65)',
      minWidth: 0,
    }}>
      <span style={{
        width: 18, height: 18, borderRadius: '50%',
        background: grads[tone] || grads.sage,
        color: tone === 'honey' ? '#2B1F12' : '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'var(--font-ui)', fontWeight: 500, fontSize: 10,
        letterSpacing: '-0.01em', flexShrink: 0,
        boxShadow: '0 1px 0 rgba(255,255,255,0.4) inset',
      }}>{letter}</span>
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 10.5,
        color: 'var(--fg-2)', letterSpacing: '.04em',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{domain}</span>
    </span>
  );
}

/* ─── SuggestionCompact ─────────────────────────────────
   one-row glass tile. headline + count + show / × .
   expandable on tap.
*/
function SuggestionCompact({ text, count, onDismiss, onAccept }) {
  const [expanded, setExpanded] = React.useState(false);
  return (
    <div style={{
      position: 'relative', overflow: 'hidden',
      background: 'linear-gradient(160deg, rgba(226,237,226,0.85) 0%, rgba(207,223,207,0.7) 100%)',
      backdropFilter: 'blur(20px) saturate(160%)',
      WebkitBackdropFilter: 'blur(20px) saturate(160%)',
      border: '1px solid rgba(207,223,207,0.7)',
      borderRadius: 18,
      boxShadow: '0 1px 0 rgba(255,255,255,0.5) inset, 0 4px 14px rgba(60,90,60,0.06)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 8px 10px 14px',
      }}>
        <div style={{
          width: 26, height: 26, borderRadius: '50%',
          background: '#fff', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 1px 4px rgba(60,90,60,0.1)',
        }}>
          <Glyph ch="✦" size={14}/>
        </div>

        <div style={{
          flex: 1, minWidth: 0,
          fontFamily: 'var(--font-display)', fontStyle: 'italic', fontWeight: 400,
          fontSize: 14, color: 'var(--fg-1)', lineHeight: 1.3, letterSpacing: 0,
        }}>{text}</div>

        <button onClick={onAccept || (()=>setExpanded(v=>!v))} style={{
          flexShrink: 0,
          background: 'var(--brand-primary)', color: 'var(--fg-on-brand)',
          border: 'none', padding: '6px 12px', borderRadius: 999,
          fontSize: 11.5, fontWeight: 500, cursor: 'pointer',
          fontFamily: 'var(--font-ui)', letterSpacing: '-0.005em',
          display: 'inline-flex', alignItems: 'center', gap: 5,
          boxShadow: '0 1px 0 rgba(255,255,255,0.2) inset, 0 2px 6px rgba(122,156,122,0.2)',
        }}>
          показать
          {count != null && <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            opacity: 0.85, letterSpacing: 0,
          }}>{count}</span>}
        </button>

        <button onClick={onDismiss} aria-label="закрыть" style={{
          flexShrink: 0,
          background: 'transparent', border: 'none',
          width: 22, height: 22, borderRadius: '50%',
          color: 'var(--fg-3)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {React.cloneElement(Icons.close, { size: 12, sw: 1.8 })}
        </button>
      </div>
    </div>
  );
}
