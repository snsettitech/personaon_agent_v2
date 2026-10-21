export default function RealNotSynthetic() {
  return (
    <section
      id="voice"
      className="relative"
      style={{ background: 'var(--fog)' }}
    >
      <div className="mx-auto max-w-[1100px] px-6 py-24 md:py-32">
        <div
          className="relative overflow-hidden"
          style={{
            background: 'var(--ink)',
            color: '#FFFFFF',
            borderRadius: 'var(--r-card)',
            padding: '64px 56px',
          }}
        >
          {/* radial glow */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                'radial-gradient(560px 320px at 80% 0%, rgba(0,102,204,.32), transparent 70%)',
            }}
          />

          <p
            className="relative text-[11px] uppercase tracking-[0.2em]"
            style={{
              color: 'rgba(255,255,255,0.6)',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            Persona, not personality engine
          </p>

          <h2
            className="relative mt-5 max-w-[640px]"
            style={{
              fontFamily: "'Geist', sans-serif",
              fontWeight: 600,
              fontSize: 'clamp(32px, 4.6vw, 56px)',
              lineHeight: 1.05,
              letterSpacing: '-0.03em',
              color: '#FFFFFF',
            }}
          >
            Real you. Real voice.
            <br />
            <span
              style={{
                color: 'rgba(255,255,255,0.55)',
                fontFamily: "'Newsreader', Georgia, serif",
                fontStyle: 'italic',
                fontWeight: 400,
              }}
            >
              Not synthetic.
            </span>
          </h2>

          <p
            className="relative mt-6 max-w-[620px] text-[16.5px] leading-[1.6]"
            style={{
              color: 'rgba(255,255,255,0.72)',
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.005em',
            }}
          >
            Some teams call this a digital twin. We call it your persona &mdash;
            because every word it says traces back to your resume, an edit you
            made, or material you approved. No hallucinated personality, no AI
            voice gimmick. The answers are in your phrasing. The persona defers
            when it doesn&rsquo;t know. You&rsquo;re accountable &mdash; your
            persona is not synthetic, and never claims to be you when it
            isn&rsquo;t sure.
          </p>
        </div>
      </div>
    </section>
  );
}
