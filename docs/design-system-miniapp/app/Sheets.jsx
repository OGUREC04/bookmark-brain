/* Bottom Sheets — 5 variants.
   Each renders OVER an iOS-frame'd screen.
   Anatomy: handle bar · strong-glass body · radius xl 28 · slide-up 320ms. */

function BottomSheet({ children, onDismiss, paddingBottom = 24, height = 'auto' }) {
  return (
    <>
      {/* overlay */}
      <div onClick={onDismiss} style={{
        position: 'absolute', inset: 0,
        background: 'var(--bg-overlay, rgba(28,22,18,0.32))',
        backdropFilter: 'blur(2px)', WebkitBackdropFilter: 'blur(2px)',
        zIndex: 100,
      }}/>
      {/* sheet */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        zIndex: 101,
        height,
        animation: 'sheetUp 320ms var(--ease-out) both',
      }}>
        <div style={{
          background: 'rgba(255,252,246,0.92)',
          backdropFilter: 'blur(32px) saturate(160%)',
          WebkitBackdropFilter: 'blur(32px) saturate(160%)',
          borderTopLeftRadius: 28, borderTopRightRadius: 28,
          borderTop: '1px solid rgba(255,255,255,0.7)',
          padding: `6px 0 ${paddingBottom}px`,
          boxShadow: '0 -8px 30px rgba(60,40,25,0.12), 0 1px 0 rgba(255,255,255,0.6) inset',
        }}>
          {/* handle */}
          <div style={{ display: 'flex', justifyContent: 'center', padding: '6px 0 10px' }}>
            <div style={{ width: 38, height: 4, borderRadius: 999, background: 'var(--border-strong, #C9C0AC)' }}/>
          </div>
          {children}
        </div>
      </div>
    </>
  );
}

/* ── ActionSheet — long-press on bookmark ─────────────────── */
function ActionSheet({ onDismiss }) {
  const items = [
    { id:'remind', icon: ExtraIcons.clock,  label:'напомнить',    sub:'сегодня в 18:00' },
    { id:'star',   glyph:'★',                label:'в избранное',  sub:null },
    { id:'space',  icon: ExtraIcons.folder, label:'в пространство', sub:'выбрать' },
    { id:'del',    icon: ExtraIcons.trash,  label:'удалить',       sub:null, danger:true },
  ];
  return (
    <BottomSheet onDismiss={onDismiss}>
      {/* mini context — what we're acting on */}
      <div style={{
        margin: '0 16px 6px', padding: '10px 14px',
        background: 'rgba(234,227,207,0.45)',
        border: '1px solid var(--border-1)', borderRadius: 14,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: 'linear-gradient(135deg, #8FA888 0%, #4A6648 100%)',
          color: '#fff', display:'flex', alignItems:'center', justifyContent:'center',
          fontFamily:'var(--font-ui)', fontWeight:500, fontSize:13,
        }}>A</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize:13, fontWeight:500, color:'var(--fg-1)', letterSpacing:'-0.01em', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
            Constitutional AI: harmlessness…
          </div>
          <div style={{ fontFamily:'var(--font-mono)', fontSize:10.5, color:'var(--fg-3)', letterSpacing:'.06em' }}>
            anthropic.com · 14:32
          </div>
        </div>
      </div>

      <div style={{ padding: '4px 6px 4px' }}>
        {items.map((it, i) => (
          <button key={it.id} style={{
            display: 'flex', alignItems: 'center', gap: 14,
            width: '100%', padding: '12px 14px',
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: it.danger ? 'var(--semantic-error, #8A2A20)' : 'var(--fg-1)',
            textAlign: 'left',
          }}>
            <span style={{
              width: 34, height: 34, borderRadius: 10,
              background: it.danger ? 'rgba(138,42,32,0.08)' : 'rgba(234,227,207,0.55)',
              display:'flex', alignItems:'center', justifyContent:'center',
              color: it.danger ? 'var(--semantic-error, #8A2A20)' : 'var(--brand-primary-press)',
              flexShrink: 0,
            }}>
              {it.glyph
                ? <Glyph ch={it.glyph} size={18} color="currentColor"/>
                : React.cloneElement(it.icon, { size: 18, sw: 1.6 })}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 500, letterSpacing: '-0.01em' }}>{it.label}</div>
              {it.sub && (
                <div style={{ fontFamily:'var(--font-display)', fontStyle:'italic', fontSize:12.5, color:'var(--fg-3)', letterSpacing:0, marginTop:2 }}>{it.sub}</div>
              )}
            </span>
          </button>
        ))}
      </div>
    </BottomSheet>
  );
}

/* ── RemindersSheet — grouped reminders list ────────────── */
function RemindersSheet({ onDismiss }) {
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="напоминания" right="3 · 2 · 1"/>

      <ReminderGroup label="сегодня">
        <ReminderRow
          avatar={{ kind:'letter', tone:'sage', letter:'A' }}
          name="Constitutional AI"
          time="18:00"
          preview="дочитать раздел про red-teaming"
        />
        <ReminderRow
          avatar={{ kind:'task' }}
          name="список покупок"
          time="19:30"
          preview="хлеб, пылесос, корм"
        />
        <ReminderRow
          avatar={{ kind:'icon', tone:'clay', icon: React.cloneElement(ExtraIcons.mic, { size:18, sw:1.6 }) }}
          name="голосовая · 0:47"
          time="22:00"
          preview="«не забыть купить корм для рыбок»"
          isLast
        />
      </ReminderGroup>

      <ReminderGroup label="завтра">
        <ReminderRow
          avatar={{ kind:'letter', tone:'honey', letter:'K' }}
          name="@karpathy · rlhf thread"
          time="9:00"
          preview="перечитать, написать конспект"
        />
        <ReminderRow
          avatar={{ kind:'task' }}
          name="починить кран"
          time="11:00"
          preview="позвонить мастеру"
          isLast
        />
      </ReminderGroup>

      <ReminderGroup label="на неделе">
        <ReminderRow
          avatar={{ kind:'letter', tone:'plum', letter:'И' }}
          name="idli · рецепт"
          time="сб"
          preview="замочить рис вечером в пт"
          isLast
        />
      </ReminderGroup>
    </BottomSheet>
  );
}

function SheetTitle({ title, right }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      padding: '4px 20px 14px',
    }}>
      <h3 style={{ fontSize: 20, fontWeight: 500, letterSpacing: '-0.025em', color: 'var(--fg-1)', margin: 0 }}>{title}</h3>
      {right && (
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--fg-3)', letterSpacing: '.06em', fontWeight: 500,
        }}>{right}</span>
      )}
    </div>
  );
}

function ReminderGroup({ label, children }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        padding: '0 20px 4px',
        fontFamily: 'var(--font-mono)', fontSize: 10,
        letterSpacing: '.12em', textTransform: 'uppercase',
        color: 'var(--brand-primary-press)', fontWeight: 500,
      }}>{label}</div>
      <div>{children}</div>
    </div>
  );
}

function ReminderRow({ avatar, name, time, preview, isLast }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 16px', cursor: 'pointer',
      position: 'relative',
    }}>
      {!isLast && (
        <span style={{ position:'absolute', left: 70, right: 16, bottom: 0, borderBottom: '0.5px solid var(--border-1)' }}/>
      )}
      <Avatar {...avatar} style={{ width: 38, height: 38, fontSize: 14 }}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--fg-1)', letterSpacing: '-0.01em', flex: 1, minWidth: 0, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--brand-primary)', letterSpacing: '.04em', fontWeight: 500 }}>{time}</span>
        </div>
        <div style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.35, marginTop: 1, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{preview}</div>
      </div>
      {/* snooze / cancel ghost buttons */}
      <div style={{ display: 'flex', gap: 4 }}>
        <button aria-label="отложить" style={{
          width: 32, height: 32, borderRadius: 10,
          background: 'rgba(255,252,246,0.7)', border: '1px solid rgba(255,255,255,0.6)',
          color: 'var(--fg-3)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{React.cloneElement(ExtraIcons.clock, { size: 14, sw: 1.6 })}</button>
        <button aria-label="отменить" style={{
          width: 32, height: 32, borderRadius: 10,
          background: 'transparent', border: '1px solid transparent',
          color: 'var(--fg-4)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{React.cloneElement(Icons.close, { size: 13, sw: 1.6 })}</button>
      </div>
    </div>
  );
}

/* ── ReminderPickerSheet — quick slot pills ─────────────── */
function ReminderPickerSheet({ onDismiss }) {
  const [picked, setPicked] = React.useState('tonight');
  const slots = [
    { id:'tonight',  label:'сегодня вечером', sub:'в 18:00' },
    { id:'morning',  label:'завтра утром',    sub:'в 9:00' },
    { id:'weekend',  label:'на выходные',     sub:'сб, 10:00' },
    { id:'week',     label:'через неделю',    sub:'пт, 9:00' },
    { id:'custom',   label:'выбрать дату…',   sub:null },
  ];
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="напомнить" right="чт, 16 мая"/>

      {/* mini context */}
      <div style={{
        margin: '0 16px 10px', padding: '10px 14px',
        background: 'rgba(234,227,207,0.45)',
        border: '1px solid var(--border-1)', borderRadius: 14,
        display:'flex', alignItems:'center', gap: 10,
      }}>
        <Glyph ch="✦" size={20}/>
        <span style={{ flex: 1,
          fontFamily:'var(--font-display)', fontStyle:'italic', fontWeight:400,
          fontSize:13.5, color:'var(--fg-2)', lineHeight:1.35,
        }}>«Constitutional AI: harmlessness…»</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '0 16px' }}>
        {slots.map(s => {
          const on = picked === s.id;
          return (
            <button key={s.id} onClick={() => setPicked(s.id)} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '13px 16px',
              background: on ? 'var(--brand-primary-tint)' : 'rgba(255,252,246,0.7)',
              border: on ? '1px solid rgba(122,156,122,0.45)' : '1px solid rgba(255,255,255,0.6)',
              borderRadius: 14, cursor: 'pointer', textAlign: 'left',
              color: 'var(--fg-1)',
            }}>
              <span style={{
                width: 18, height: 18, borderRadius: '50%',
                border: on ? 'none' : '1.5px solid var(--border-strong)',
                background: on ? 'var(--brand-primary)' : 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--fg-on-brand)', flexShrink: 0,
              }}>
                {on && React.cloneElement(Icons.check, { size: 11, sw: 2.5 })}
              </span>
              <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.01em' }}>{s.label}</span>
              {s.sub && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: on ? 'var(--brand-primary-press)' : 'var(--fg-3)', letterSpacing: '.04em' }}>{s.sub}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Telegram MainButton emulation */}
      <div style={{ padding: '16px 16px 0' }}>
        <TelegramMainButton label="напомнить" enabled/>
      </div>
    </BottomSheet>
  );
}

/* ── MoveToSpaceSheet ──────────────────────────────────── */
function MoveToSpaceSheet({ onDismiss }) {
  const [picked, setPicked] = React.useState('reading');
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="в пространство"/>
      <div style={{ padding: '0 12px' }}>
        {seedSpaces.slice(0, 6).map(s => {
          const on = picked === s.id;
          return (
            <button key={s.id} onClick={() => setPicked(s.id)} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              width: '100%', padding: '10px 12px',
              background: on ? 'var(--brand-primary-tint)' : 'transparent',
              border: '1px solid ' + (on ? 'rgba(122,156,122,0.35)' : 'transparent'),
              borderRadius: 12, cursor: 'pointer', textAlign: 'left',
              marginBottom: 2,
            }}>
              <div style={{
                width: 32, height: 32, borderRadius: 10,
                background: 'linear-gradient(135deg, rgba(143,168,136,0.7), rgba(74,102,72,0.7))',
                color: '#fff', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
              }}>
                <Glyph ch={s.glyph || '·'} size={16} color="currentColor"/>
              </div>
              <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.01em', color: 'var(--fg-1)' }}>{s.name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--fg-3)', letterSpacing: '.06em' }}>{s.count}</span>
              {on && (
                <span style={{ color: 'var(--brand-primary)', display: 'flex' }}>
                  {React.cloneElement(Icons.check, { size: 16, sw: 2.2 })}
                </span>
              )}
            </button>
          );
        })}
        <button style={{
          display: 'flex', alignItems: 'center', gap: 12,
          width: '100%', padding: '10px 12px', marginTop: 4,
          background: 'transparent', border: '1px dashed var(--border-strong)',
          borderRadius: 12, cursor: 'pointer', textAlign: 'left',
          color: 'var(--brand-primary)',
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 10,
            background: 'rgba(255,252,246,0.7)',
            border: '1px solid var(--border-2)',
            display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
          }}>
            {React.cloneElement(Icons.plus, { size: 16, sw: 1.8 })}
          </div>
          <span style={{ flex: 1, fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.01em' }}>создать пространство</span>
        </button>
      </div>
    </BottomSheet>
  );
}

/* ── QuickCreateSheet — FAB+ ───────────────────────────── */
function QuickCreateSheet({ onDismiss }) {
  const [v, setV] = React.useState('');
  return (
    <BottomSheet onDismiss={onDismiss}>
      <SheetTitle title="новая мысль" right="enter — сохранить"/>

      <div style={{ padding: '0 16px' }}>
        <div style={{
          background: 'rgba(255,252,246,0.85)',
          border: '1px solid rgba(255,255,255,0.7)',
          borderRadius: 18, padding: '14px 16px',
          boxShadow: '0 1px 0 rgba(255,255,255,0.6) inset, 0 4px 12px rgba(60,40,25,0.05)',
          minHeight: 110,
        }}>
          {!v && (
            <span style={{
              fontFamily: 'var(--font-display)', fontStyle: 'italic',
              fontSize: 16, color: 'var(--fg-3)', lineHeight: 1.4, letterSpacing: 0,
              pointerEvents: 'none', display: 'block',
            }}>пиши мысль · вставь ссылку · бот разберёт сам</span>
          )}
          {v && (
            <div style={{ fontSize: 16, color: 'var(--fg-1)', lineHeight: 1.4, letterSpacing: '-0.005em' }}>{v}</div>
          )}
          {/* fake cursor */}
          <span style={{
            display: 'inline-block', width: 1.5, height: 18,
            background: 'var(--brand-primary)', verticalAlign: 'middle',
            marginLeft: v ? 2 : 0,
            animation: 'mPulse 1.2s ease-in-out infinite',
          }}/>
        </div>

        {/* attachment row · disabled */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 4px 6px',
        }}>
          <button aria-label="вложение" disabled style={{
            width: 36, height: 36, borderRadius: 12,
            background: 'rgba(234,227,207,0.4)',
            border: '1px solid var(--border-1)',
            color: 'var(--fg-4)', cursor: 'not-allowed',
            display:'flex', alignItems:'center', justifyContent:'center',
          }}>{React.cloneElement(ExtraIcons.paperclip, { size: 16, sw: 1.6 })}</button>
          <button aria-label="голос" disabled style={{
            width: 36, height: 36, borderRadius: 12,
            background: 'rgba(234,227,207,0.4)',
            border: '1px solid var(--border-1)',
            color: 'var(--fg-4)', cursor: 'not-allowed',
            display:'flex', alignItems:'center', justifyContent:'center',
          }}>{React.cloneElement(ExtraIcons.mic, { size: 16, sw: 1.6 })}</button>
          <span style={{
            flex: 1,
            fontFamily: 'var(--font-display)', fontStyle: 'italic',
            fontSize: 12, color: 'var(--fg-3)', letterSpacing: 0,
          }}>вложения — в боте</span>
        </div>

        <div style={{ marginTop: 8 }}>
          <TelegramMainButton label="сохранить" enabled={false}/>
        </div>
      </div>
    </BottomSheet>
  );
}

function TelegramMainButton({ label, enabled }) {
  return (
    <button disabled={!enabled} style={{
      width: '100%', padding: '14px 18px', borderRadius: 14,
      background: enabled ? 'var(--brand-primary)' : 'rgba(122,156,122,0.35)',
      color: 'var(--fg-on-brand)', border: 'none',
      fontFamily: 'var(--font-ui)', fontSize: 15, fontWeight: 500, letterSpacing: '-0.005em',
      cursor: enabled ? 'pointer' : 'not-allowed',
      boxShadow: enabled
        ? '0 1px 0 rgba(255,255,255,0.2) inset, 0 4px 12px rgba(122,156,122,0.25)'
        : 'none',
    }}>{label}</button>
  );
}

/* sheet anim */
if (typeof document !== 'undefined' && !document.getElementById('sheet-anim')) {
  const s = document.createElement('style');
  s.id = 'sheet-anim';
  s.textContent = `@keyframes sheetUp{from{transform:translateY(20%);opacity:0}to{transform:translateY(0);opacity:1}}`;
  document.head.appendChild(s);
}

Object.assign(window, {
  BottomSheet, ActionSheet, RemindersSheet, ReminderPickerSheet,
  MoveToSpaceSheet, QuickCreateSheet, TelegramMainButton, SheetTitle,
});
