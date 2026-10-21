interface PaneBullet {
  text: string;
}

interface PaneProps {
  label: string;
  heading: string;
  when: string;
  bullets: ReadonlyArray<PaneBullet>;
  tag: {
    text: string;
    variant: 'ok' | 'warn';
  };
}

const BEFORE: PaneProps = {
  label: 'Before · your resume today',
  heading: 'A PDF in someone’s inbox',
  when: 'Opened for 7 seconds · no questions possible',
  bullets: [
    { text: 'One static page trying to speak to every audience' },
    { text: 'Can’t answer the follow-up: "tell me about that launch"' },
    { text: 'No idea who read it, or what they cared about' },
  ],
  tag: { text: '○ Answers nothing', variant: 'warn' },
};

const AFTER: PaneProps = {
  label: 'After · personaon.com/you',
  heading: 'Your page, answering a recruiter',
  when: 'Tuesday 9:14 PM · while you slept',
  bullets: [
    { text: 'Answered "What did you ship at Acme?" — in your voice, from your material' },
    { text: 'Booked a Thursday intro call straight into your calendar' },
    {
      text: 'Every question they asked is on your dashboard next morning',
    },
  ],
  tag: { text: '✓ Answered 12 questions this week', variant: 'ok' },
};

export default function BeforeAfter() {
  return (
    <section className="mx-auto max-w-[1180px] px-6 pt-12 md:pt-16">
      <div
        className="grid items-stretch gap-8 p-8 md:p-10"
        style={{
          background: 'var(--fog-2)',
          borderRadius: 'var(--r-card)',
          boxShadow: 'var(--shadow-hero)',
          gridTemplateColumns: '1fr',
        }}
      >
        <div className="grid items-center gap-8 md:grid-cols-[1fr_auto_1fr]">
          <Pane {...BEFORE} />
          <Arrow />
          <Pane {...AFTER} />
        </div>
      </div>
      <p
        className="mt-5 text-center text-[13.5px]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'Geist', sans-serif",
          letterSpacing: '-0.005em',
        }}
      >
        Not a chatbot widget. A portfolio that speaks for you &mdash; grounded in
        what you actually did.
      </p>
    </section>
  );
}

function Pane({ label, heading, when, bullets, tag }: PaneProps) {
  const tagStyles =
    tag.variant === 'ok'
      ? { background: 'rgba(43,182,115,.10)', color: '#2BB673' }
      : { background: 'rgba(224,162,26,.10)', color: '#E0A21A' };

  return (
    <div
      className="p-7"
      style={{
        background: 'var(--fog)',
        border: '1px solid var(--fog-line)',
        borderRadius: 22,
      }}
    >
      <p
        className="text-[10.5px] uppercase tracking-[0.18em]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {label}
      </p>
      <h3
        className="mt-3.5 text-[17px]"
        style={{
          color: 'var(--ink)',
          fontFamily: "'Geist', sans-serif",
          fontWeight: 600,
          letterSpacing: '-0.012em',
          lineHeight: 1.2,
        }}
      >
        {heading}
      </h3>
      <p
        className="mt-1 text-[12.5px]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {when}
      </p>
      <ul className="mt-4 list-none space-y-1">
        {bullets.map((b) => (
          <li
            key={b.text}
            className="relative pl-[18px] text-[13.5px] leading-[1.55]"
            style={{
              color: 'var(--ink-2)',
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.003em',
            }}
          >
            <span
              aria-hidden
              className="absolute"
              style={{
                left: 4,
                top: 9,
                width: 5,
                height: 5,
                borderRadius: 9999,
                background: 'var(--signal)',
              }}
            />
            {b.text}
          </li>
        ))}
      </ul>
      <span
        className="mt-3 inline-block rounded-full px-2.5 py-[2px] text-[10.5px]"
        style={{
          ...tagStyles,
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 500,
          letterSpacing: '-0.005em',
        }}
      >
        {tag.text}
      </span>
    </div>
  );
}

function Arrow() {
  return (
    <span
      aria-hidden
      className="block text-center"
      style={{
        color: 'var(--fog-line-2)',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 32,
        userSelect: 'none',
      }}
    >
      &rarr;
    </span>
  );
}
