/* PhoneFrame — wraps a screen in iOS device with backdrop + bottom nav.
   `nav` controls which tab is active. `sheet` mounts a sheet overlay above the content.
   The brief says the iOS frame is a context harness — it's here only so the design
   reads as a real Mini App, not free-floating UI. */

function PhoneFrame({ children, nav = 'mysli', sheet = null, width = 380, height = 780 }) {
  return (
    <IOSDevice width={width} height={height}>
      <div style={{
        height: '100%', position: 'relative', overflow: 'hidden',
        background: 'var(--backdrop-gradient)',
        fontFamily: 'var(--font-ui)',
        boxSizing: 'border-box',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* spacer below the iOS status bar */}
        <div style={{ height: 54, flexShrink: 0 }}/>

        {/* scrollable content area */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          {children}
        </div>

        {/* sheet overlay (sits above content, below home indicator) */}
        {sheet}

        {/* bottom nav stays on every screen */}
        {nav !== 'none' && (
          <BottomNav current={nav} onChange={() => {}} onFab={() => {}}/>
        )}
      </div>
    </IOSDevice>
  );
}

Object.assign(window, { PhoneFrame });
