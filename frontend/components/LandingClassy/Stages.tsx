interface Stage {
  num: string;
  phase: string;
  name: string;
  body: string;
  bullets: ReadonlyArray<string>;
  color: string;
}

const STAGES: ReadonlyArray<Stage> = [
  {
    num: '01',
    phase: 'Start',
    name: 'Paste',
    body: 'Paste your resume — or drop the PDF. Your portfolio assembles itself: experience, skills, story. Nothing to design, nothing to write.',
    bullets: [
      '↳ Resume, or your LinkedIn PDF export',
      '↳ Assembled in about a minute',
      '↳ Edit anything before it goes live',
    ],
    color: '#0066cc',
  },
  {
    num: '02',
    phase: 'Publish',
    name: 'Claim',
    body: 'Watch it answer a question about you, then claim your handle. personaon.com/you is live — share it everywhere your name appears.',
    bullets: [
      '↳ personaon.com/yourname',
      '↳ Share card built for LinkedIn',
      '↳ Bio link · email signature · resume header',
    ],
    color: '#2BB673',
  },
  {
    num: '03',
    phase: 'Compound',
    name: 'It answers',
    body: 'Visitors ask; your page answers in your voice, books meetings into your calendar, and captures who was interested — while you sleep.',
    bullets: [
      '↳ Grounded in your material — never invents',
      '↳ Calendar booking built in',
      '↳ Every conversation on your dashboard',
    ],
    color: '#E0A21A',
  },
];

export default function Stages() {
  return (
    <section
      id="how"
      className="mx-auto max-w-[1180px] px-6 py-32 text-center md:py-40"
    >
      <p
        className="text-[11px] uppercase tracking-[0.2em]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        The loop
      </p>

      <h2
        className="mx-auto mt-5 max-w-[760px]"
        style={{
          fontFamily: "'Geist', sans-serif",
          fontWeight: 600,
          fontSize: 'clamp(32px, 4.4vw, 54px)',
          lineHeight: 1.05,
          letterSpacing: '-0.025em',
          color: 'var(--ink)',
        }}
      >
        One page. Three minutes.{' '}
        <span
          style={{
            fontFamily: "'Newsreader', Georgia, serif",
            fontStyle: 'italic',
            fontWeight: 400,
          }}
        >
          Working for you.
        </span>
      </h2>

      <p
        className="mx-auto mt-5 max-w-[580px] text-[17px] leading-[1.55]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'Geist', sans-serif",
          letterSpacing: '-0.005em',
        }}
      >
        Website builders give you another static page. This one talks back.
      </p>

      <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
        {STAGES.map((stage) => (
          <StageCard key={stage.num} stage={stage} />
        ))}
      </div>
    </section>
  );
}

function StageCard({ stage }: { stage: Stage }) {
  return (
    <article
      className="relative overflow-hidden p-9 text-left"
      style={{
        background: 'var(--fog-2)',
        borderRadius: 'var(--r-card)',
        boxShadow: '0 6px 24px rgba(0,0,0,.05), 0 1px 0 rgba(29,29,31,.04)',
      }}
    >
      <span
        aria-hidden
        className="absolute left-0 top-0 h-full"
        style={{ width: 4, background: stage.color }}
      />
      <p
        className="text-[10.5px] uppercase tracking-[0.2em]"
        style={{
          color: stage.color,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {stage.num} · {stage.phase}
      </p>
      <h3
        className="mt-5"
        style={{
          fontFamily: "'Geist', sans-serif",
          fontSize: 28,
          fontWeight: 600,
          letterSpacing: '-0.025em',
          color: 'var(--ink)',
          lineHeight: 1.1,
        }}
      >
        {stage.name}
      </h3>
      <p
        className="mt-3 text-[14.5px] leading-[1.6]"
        style={{
          color: 'var(--ink-2)',
          fontFamily: "'Geist', sans-serif",
          letterSpacing: '-0.005em',
        }}
      >
        {stage.body}
      </p>
      <ul
        className="mt-5 list-none border-t pt-4"
        style={{ borderColor: 'var(--fog-line)' }}
      >
        {stage.bullets.map((b) => (
          <li
            key={b}
            className="py-[4px] text-[11.5px]"
            style={{
              color: 'var(--fg-2)',
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: '.04em',
            }}
          >
            {b}
          </li>
        ))}
      </ul>
    </article>
  );
}
