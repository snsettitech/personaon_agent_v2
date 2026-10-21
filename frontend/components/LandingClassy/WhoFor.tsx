interface Role {
  num: string;
  category: string;
  headline: string;
  pain: string;
  loop: string;
}

const ROLES: ReadonlyArray<Role> = [
  {
    num: '01',
    category: 'Job seekers',
    headline: 'The 7-second resume',
    pain: 'Hundreds of applications, each judged in seconds. The follow-up questions that would set you apart never get asked.',
    loop: 'Your page answers them — projects, decisions, results, in your voice — and books the intro call while they’re still curious.',
  },
  {
    num: '02',
    category: 'Freelancers & consultants',
    headline: 'Every lead asks the same 10 questions',
    pain: 'Scope, rates, availability, past work — answered by email, one lead at a time, often days too late.',
    loop: 'Your page qualifies the lead, answers the FAQ from your real work, and books the call while interest is hot.',
  },
  {
    num: '03',
    category: 'Founders',
    headline: 'Investors check you out at midnight',
    pain: 'Diligence happens when you’re not in the room — a thin LinkedIn and a stale deck speak for you.',
    loop: 'Your page tells the story you’d tell: traction, thesis, background — and turns quiet interest into a booked meeting.',
  },
  {
    num: '04',
    category: 'Coaches & experts',
    headline: 'Trust is the product',
    pain: 'Prospects want to know how you think before they pay; static testimonials never answer their actual question.',
    loop: 'Your page lets them ask, answers from your published material, and converts the curious into booked sessions.',
  },
];

export default function WhoFor() {
  return (
    <section
      id="who"
      className="relative"
      style={{ background: 'var(--fog-2)' }}
    >
      <div className="mx-auto max-w-[1200px] px-6 py-32 md:py-40">
        <div className="text-center">
          <p
            className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
            style={{
              borderColor: 'rgba(29,29,31,0.10)',
              color: 'var(--fg-2)',
              background: 'var(--fog)',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Who it&rsquo;s for
          </p>

          <h2
            className="mx-auto mt-7 max-w-[1000px]"
            style={{
              fontFamily: "'Geist', sans-serif",
              fontWeight: 600,
              fontSize: 'clamp(40px, 6.6vw, 88px)',
              lineHeight: 1.02,
              letterSpacing: '-0.03em',
              color: 'var(--ink)',
            }}
          >
            Built for people whose{' '}
            <span
              style={{
                fontFamily: "'Newsreader', Georgia, serif",
                fontStyle: 'italic',
                fontWeight: 400,
              }}
            >
              story
            </span>{' '}
            is the product.
          </h2>

          <p
            className="mx-auto mt-7 max-w-[660px]"
            style={{
              color: 'var(--fg-2)',
              fontFamily: "'Geist', sans-serif",
              fontSize: 'clamp(17px, 1.5vw, 21px)',
              lineHeight: 1.5,
              letterSpacing: '-0.005em',
            }}
          >
            If people keep asking the same questions about your work &mdash; your
            page should be the one answering them.
          </p>
        </div>

        <div className="mt-16 grid grid-cols-1 gap-5 sm:grid-cols-2">
          {ROLES.map((role) => (
            <article
              key={role.num}
              className="flex flex-col p-8 md:p-10"
              style={{
                background: 'var(--fog-2)',
                borderRadius: 24,
                boxShadow:
                  '0 6px 24px rgba(0,0,0,.05), 0 1px 0 rgba(29,29,31,.04)',
              }}
            >
              <p
                className="text-[10.5px] uppercase tracking-[0.18em]"
                style={{
                  color: 'var(--fg-3)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {role.num} &mdash; {role.category.toUpperCase()}
              </p>
              <p
                className="mt-3"
                style={{
                  color: 'var(--ink)',
                  fontFamily: "'Geist', sans-serif",
                  fontSize: 22,
                  lineHeight: 1.2,
                  letterSpacing: '-0.02em',
                  fontWeight: 600,
                }}
              >
                {role.headline}
              </p>

              <div className="mt-5 flex flex-col gap-3">
                <RoleLine label="Pain" body={role.pain} />
                <RoleLine label="Loop" body={role.loop} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function RoleLine({ label, body }: { label: string; body: string }) {
  return (
    <div className="flex items-start gap-3">
      <span
        className="flex-shrink-0 pt-[2px] text-[10.5px] uppercase tracking-[0.12em]"
        style={{
          color: 'var(--fg-2)',
          fontFamily: "'JetBrains Mono', monospace",
          width: 56,
        }}
      >
        {label}
      </span>
      <span
        className="flex-1 text-[13.5px] leading-[1.6]"
        style={{
          color: 'var(--ink-2)',
          fontFamily: "'Geist', sans-serif",
          letterSpacing: '-0.005em',
        }}
      >
        {body}
      </span>
    </div>
  );
}
