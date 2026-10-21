export default function Category() {
  return (
    <section
      id="what"
      className="relative"
      style={{ background: 'var(--fog-2)' }}
    >
      <div className="mx-auto max-w-[1100px] px-6 py-32 text-center md:py-40">
        <p
          className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          style={{
            borderColor: 'rgba(29,29,31,0.10)',
            color: 'var(--fg-2)',
            background: 'var(--fog)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          What is a persona
        </p>

        <h2
          className="mx-auto mt-7 max-w-[980px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(48px, 8vw, 112px)',
            lineHeight: 0.97,
            letterSpacing: '-0.04em',
            color: 'var(--ink)',
          }}
        >
          More than a profile.
          <br />
          <span style={{ color: 'var(--fg-3)' }}>It answers.</span>
        </h2>

        <p
          className="mx-auto mt-7 max-w-[680px]"
          style={{
            color: 'var(--fg-2)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(17px, 1.5vw, 21px)',
            lineHeight: 1.5,
            letterSpacing: '-0.005em',
          }}
        >
          Not a chatbot. Not an avatar. Not a synthetic clone. A persona is{' '}
          <span style={{ color: 'var(--ink)', fontWeight: 500 }}>you</span>{' '}
          &mdash; your voice, your knowledge, your judgment &mdash; made reachable,
          bookable, and present on your terms.
        </p>

        {/* Contrast triptych */}
        <div className="mt-20 grid grid-cols-1 gap-px overflow-hidden rounded-[28px] text-left md:grid-cols-3"
          style={{ background: 'rgba(29,29,31,0.10)' }}
        >
          {[
            { name: 'Linktree', gives: 'gives you links.', missing: 'But not you.' },
            { name: 'LinkedIn', gives: 'gives you a resume.', missing: 'But not your voice.' },
            { name: 'ChatGPT', gives: 'gives you answers.', missing: 'But not yours.' },
          ].map((row) => (
            <div
              key={row.name}
              className="flex flex-col justify-between p-10 md:p-12"
              style={{ background: 'var(--fog-2)', minHeight: 280 }}
            >
              <p
                className="text-[12px] uppercase tracking-[0.2em]"
                style={{
                  color: 'var(--fg-3)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {row.name}
              </p>
              <div className="mt-12">
                <p
                  style={{
                    color: 'var(--ink)',
                    fontFamily: "'Geist', sans-serif",
                    fontSize: 'clamp(22px, 2.4vw, 30px)',
                    lineHeight: 1.15,
                    letterSpacing: '-0.022em',
                    fontWeight: 500,
                  }}
                >
                  {row.gives}
                </p>
                <p
                  className="mt-2.5 text-[16px]"
                  style={{
                    color: 'var(--fg-2)',
                    fontFamily: "'Geist', sans-serif",
                    letterSpacing: '-0.005em',
                  }}
                >
                  {row.missing}
                </p>
              </div>
            </div>
          ))}
        </div>

        <p
          className="mx-auto mt-12 max-w-[520px]"
          style={{
            color: 'var(--ink)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(20px, 1.8vw, 26px)',
            lineHeight: 1.3,
            letterSpacing: '-0.018em',
            fontWeight: 500,
          }}
        >
          PersonaOn gives you all three. As one page. As you.
        </p>
      </div>
    </section>
  );
}
