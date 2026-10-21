const TILES = [
  {
    title: 'Publish you.',
    body: 'Your links, your work, your story — in one place that actually represents you. A site of your own, without building one.',
    surface: 'light' as const,
    visual: 'profile' as const,
  },
  {
    title: 'Answer for you.',
    body: 'The questions you keep getting — answered in your voice, on demand. Coffee chats sorted before they land on your calendar.',
    surface: 'dark' as const,
    visual: 'chat' as const,
  },
  {
    title: 'Meet, when it’s worth it.',
    body: 'The conversations that actually matter still happen — better prepped, better matched, better used. PersonaOn kills the bad coffee chat. Not the good one.',
    surface: 'light' as const,
    visual: 'calendar' as const,
  },
  {
    title: 'Know who’s at your door.',
    body: 'Every visitor. Every question. Every interest. The internet finally tells you who’s been reading you — not just that someone was.',
    surface: 'dark' as const,
    visual: 'analytics' as const,
  },
];

export default function Jobs() {
  return (
    <section id="how" className="relative" style={{ background: 'var(--fog)' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-32 md:py-40">
        <div className="text-center">
          <p
            className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
            style={{
              borderColor: 'rgba(29,29,31,0.10)',
              color: 'var(--fg-2)',
              background: 'var(--fog-2)',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            What it does
          </p>

          <h2
            className="mx-auto mt-7 max-w-[1000px]"
            style={{
              fontFamily: "'Geist', sans-serif",
              fontWeight: 600,
              fontSize: 'clamp(48px, 8vw, 112px)',
              lineHeight: 0.97,
              letterSpacing: '-0.04em',
              color: 'var(--ink)',
            }}
          >
            Four jobs.
            <br />
            <span style={{ color: 'var(--fg-3)' }}>One page.</span>
          </h2>
        </div>

        <div className="mt-20 grid grid-cols-1 gap-5 md:grid-cols-2">
          {TILES.map((t, i) => (
            <Tile key={t.title} index={i} {...t} />
          ))}
        </div>
      </div>
    </section>
  );
}

function Tile({
  index,
  title,
  body,
  surface,
  visual,
}: {
  index: number;
  title: string;
  body: string;
  surface: 'light' | 'dark';
  visual: 'profile' | 'chat' | 'calendar' | 'analytics';
}) {
  const isDark = surface === 'dark';
  const bg = isDark ? 'var(--ink)' : 'var(--fog-2)';
  const fg = isDark ? '#FFFFFF' : 'var(--ink)';
  const fg2 = isDark ? 'rgba(255,255,255,0.62)' : 'var(--fg-2)';
  const fg3 = isDark ? 'rgba(255,255,255,0.38)' : 'var(--fg-3)';
  const border = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(29,29,31,0.06)';

  return (
    <div
      className="relative flex flex-col overflow-hidden"
      style={{
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 32,
        minHeight: 480,
      }}
    >
      <div className="p-9 md:p-12">
        <p
          className="text-[11px] uppercase tracking-[0.2em]"
          style={{
            color: fg3,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          0{index + 1}
        </p>

        <p
          className="mt-5"
          style={{
            color: fg,
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(28px, 3.4vw, 44px)',
            lineHeight: 1.04,
            letterSpacing: '-0.028em',
            fontWeight: 600,
          }}
        >
          {title}
        </p>

        <p
          className="mt-4 max-w-[420px] text-[15.5px] leading-[1.6]"
          style={{
            color: fg2,
            fontFamily: "'Geist', sans-serif",
            letterSpacing: '-0.005em',
          }}
        >
          {body}
        </p>
      </div>

      <div className="mt-auto px-6 pb-6 md:px-10 md:pb-10">
        <TileVisual kind={visual} dark={isDark} />
      </div>
    </div>
  );
}

function TileVisual({
  kind,
  dark,
}: {
  kind: 'profile' | 'chat' | 'calendar' | 'analytics';
  dark: boolean;
}) {
  const cardBg = dark ? 'rgba(255,255,255,0.04)' : 'var(--fog)';
  const cardBorder = dark ? 'rgba(255,255,255,0.08)' : 'rgba(29,29,31,0.08)';
  const text = dark ? '#FFFFFF' : 'var(--ink)';
  const muted = dark ? 'rgba(255,255,255,0.5)' : 'var(--fg-2)';

  if (kind === 'profile') {
    return (
      <div
        className="rounded-[20px] p-5"
        style={{ background: cardBg, border: `1px solid ${cardBorder}` }}
      >
        <div className="flex items-center gap-3">
          <div
            className="h-10 w-10 rounded-full"
            style={{ background: 'var(--ink)' }}
          />
          <div className="flex-1">
            <div
              className="h-2.5 w-32 rounded-full"
              style={{ background: text, opacity: 0.85 }}
            />
            <div
              className="mt-1.5 h-2 w-24 rounded-full"
              style={{ background: muted, opacity: 0.5 }}
            />
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="aspect-[4/3] rounded-[10px]"
              style={{
                background: dark
                  ? 'rgba(255,255,255,0.08)'
                  : 'rgba(29,29,31,0.08)',
              }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (kind === 'chat') {
    return (
      <div className="space-y-2">
        <div
          className="ml-auto max-w-[60%] rounded-[14px] px-4 py-2.5 text-[12px]"
          style={{
            background: 'rgba(255,255,255,0.10)',
            color: '#FFFFFF',
            fontFamily: "'Geist', sans-serif",
          }}
        >
          What kind of advice do you give?
        </div>
        <div
          className="max-w-[78%] rounded-[14px] px-4 py-2.5 text-[12px]"
          style={{
            background: '#FFFFFF',
            color: 'var(--ink)',
            fontFamily: "'Geist', sans-serif",
          }}
        >
          Mostly the kind I wish someone had given me at your stage…
        </div>
        <div className="flex items-center gap-1 px-1 pt-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="h-1.5 w-1.5 rounded-full"
              style={{
                background: 'rgba(255,255,255,0.45)',
                animation: `voice-bar-${(i % 3) + 1} 1.2s ease-in-out infinite`,
                animationDelay: `${i * 120}ms`,
              }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (kind === 'calendar') {
    return (
      <div
        className="rounded-[20px] p-5"
        style={{ background: cardBg, border: `1px solid ${cardBorder}` }}
      >
        <p
          className="text-[10px] uppercase tracking-[0.18em]"
          style={{
            color: muted,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          Booked &mdash; this week
        </p>
        <div className="mt-4 space-y-2.5">
          {[
            { day: 'Tue', time: '10:30', label: 'Coffee w/ Kira' },
            { day: 'Wed', time: '14:00', label: 'Office hours' },
            { day: 'Fri', time: '09:00', label: 'Mentor call' },
          ].map((row) => (
            <div
              key={row.label}
              className="flex items-center gap-3 rounded-[10px] px-3 py-2"
              style={{
                background: dark
                  ? 'rgba(255,255,255,0.06)'
                  : 'rgba(29,29,31,0.04)',
              }}
            >
              <span
                className="text-[10px] uppercase tracking-[0.16em]"
                style={{
                  color: muted,
                  fontFamily: "'JetBrains Mono', monospace",
                  width: 26,
                }}
              >
                {row.day}
              </span>
              <span
                className="text-[12px]"
                style={{
                  color: text,
                  fontFamily: "'Geist', sans-serif",
                }}
              >
                {row.time}
              </span>
              <span
                className="text-[12px]"
                style={{
                  color: muted,
                  fontFamily: "'Geist', sans-serif",
                }}
              >
                {row.label}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // analytics
  return (
    <div
      className="rounded-[20px] p-5"
      style={{ background: cardBg, border: `1px solid ${cardBorder}` }}
    >
      <div className="flex items-end justify-between gap-3">
        <div>
          <p
            className="text-[10px] uppercase tracking-[0.18em]"
            style={{
              color: muted,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Visitors this week
          </p>
          <p
            className="mt-1 text-[28px]"
            style={{
              color: text,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.02em',
              fontWeight: 600,
            }}
          >
            1,284
          </p>
        </div>
        <div className="flex h-12 items-end gap-1">
          {[34, 22, 56, 41, 78, 64, 92].map((h, i) => (
            <span
              key={i}
              className="rounded-[3px]"
              style={{
                width: 8,
                height: `${h}%`,
                background: dark
                  ? 'rgba(255,255,255,0.55)'
                  : 'var(--ink)',
                opacity: i === 6 ? 1 : 0.6,
              }}
            />
          ))}
        </div>
      </div>
      <div
        className="mt-4 flex items-center justify-between rounded-[10px] px-3 py-2"
        style={{
          background: dark
            ? 'rgba(255,255,255,0.06)'
            : 'rgba(29,29,31,0.04)',
        }}
      >
        <span
          className="text-[12px]"
          style={{ color: text, fontFamily: "'Geist', sans-serif" }}
        >
          Top question
        </span>
        <span
          className="text-[12px]"
          style={{ color: muted, fontFamily: "'Geist', sans-serif" }}
        >
          “How do I get into…”
        </span>
      </div>
    </div>
  );
}
