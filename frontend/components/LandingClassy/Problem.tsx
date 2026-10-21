export default function Problem() {
  return (
    <section
      className="relative"
      style={{
        background: 'var(--ink)',
        color: '#FFFFFF',
      }}
    >
      <div className="mx-auto max-w-[1100px] px-6 py-32 text-center md:py-40">
        <p
          className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          style={{
            borderColor: 'rgba(255,255,255,0.14)',
            color: 'rgba(255,255,255,0.65)',
            background: 'rgba(255,255,255,0.03)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          The problem
        </p>

        <h2
          className="mx-auto mt-7 max-w-[1000px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(48px, 8vw, 112px)',
            lineHeight: 0.97,
            letterSpacing: '-0.04em',
            color: '#FFFFFF',
          }}
        >
          Your work speaks.
          <br />
          <span style={{ color: 'rgba(255,255,255,0.42)' }}>Your resume doesn&rsquo;t.</span>
        </h2>

        <p
          className="mx-auto mt-7 max-w-[680px]"
          style={{
            color: 'rgba(255,255,255,0.62)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(17px, 1.5vw, 21px)',
            lineHeight: 1.5,
            letterSpacing: '-0.005em',
          }}
        >
          Recruiters give a resume seven seconds. Clients leave your site with
          their real question unasked. The interesting part of your story &mdash;
          the context, the decisions, the why &mdash; never makes it past the PDF.
        </p>

        <p
          className="mx-auto mt-10"
          style={{
            color: '#FFFFFF',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(26px, 3vw, 40px)',
            lineHeight: 1.1,
            letterSpacing: '-0.025em',
            fontWeight: 500,
          }}
        >
          Being found is solved.{' '}
          <span style={{ color: 'rgba(255,255,255,0.42)' }}>Being understood isn&rsquo;t.</span>
        </p>
      </div>
    </section>
  );
}
