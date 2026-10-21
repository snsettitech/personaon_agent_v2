import type { Metadata } from 'next';
import Link from 'next/link';
import Nav from '@/components/LandingClassy/Nav';
import Footer from '@/components/LandingClassy/Footer';

export const metadata: Metadata = {
  title: 'About PersonaOn — We bet on humans.',
  description:
    'PersonaOn is built on a simple bet: in a world full of synthetic AI, real people get more valuable, not less. We help real humans become more reachable — without becoming synthetic.',
  alternates: { canonical: '/about' },
  openGraph: {
    title: 'About PersonaOn — We bet on humans.',
    description:
      'In a world full of synthetic everything, the thing that becomes more valuable is a real person.',
    type: 'website',
    url: '/about',
  },
};

export default function AboutPage(): React.JSX.Element {
  return (
    <div
      className="min-h-screen antialiased"
      style={{ backgroundColor: 'var(--fog)' }}
    >
      <Nav />
      <main>
        <Manifesto />
        <Why />
        <Beliefs />
        <ClosingCta />
      </main>
      <Footer />
    </div>
  );
}

function Manifesto() {
  return (
    <section
      className="relative overflow-hidden"
      style={{ background: 'var(--fog)' }}
    >
      <div className="mx-auto max-w-[1024px] px-6 pt-40 text-center md:pt-48">
        <p
          className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          style={{
            borderColor: 'rgba(29,29,31,0.10)',
            color: 'var(--fg-2)',
            background: 'rgba(255,255,255,0.6)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: 'var(--ink)' }}
          />
          About PersonaOn
        </p>

        <h1
          className="mx-auto mt-7 max-w-[1000px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(56px, 9.8vw, 132px)',
            lineHeight: 0.96,
            letterSpacing: '-0.045em',
            color: 'var(--ink)',
          }}
        >
          We bet on{' '}
          <span style={{ color: 'var(--fg-3)' }}>humans.</span>
        </h1>
      </div>

      <div className="mx-auto mt-16 max-w-[760px] space-y-8 px-6 pb-32 md:pb-40">
        <P>
          The internet is filling up with people who are not people. Faces that
          are not real. Voices that are not real. Experts who do not exist. AI
          that can speak fluently, sell confidently, and sound convincing
          without anyone being accountable for what it says.
        </P>
        <P>
          We think the bet most people are making is wrong.
        </P>
        <P>
          In a world full of synthetic everything, the thing that becomes more
          valuable is a real person &mdash; with a real voice, real judgment,
          and a name behind what they say.
        </P>
        <p
          style={{
            color: 'var(--ink)',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(22px, 2.4vw, 32px)',
            lineHeight: 1.25,
            letterSpacing: '-0.022em',
            fontWeight: 500,
          }}
        >
          PersonaOn is built for that.
        </p>
        <P>
          We do not generate people. We help real people become more reachable.
        </P>
      </div>
    </section>
  );
}

function Why() {
  return (
    <section style={{ background: 'var(--ink)', color: '#FFFFFF' }}>
      <div className="mx-auto max-w-[1024px] px-6 py-32 text-center md:py-40">
        <p
          className="mx-auto inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          style={{
            borderColor: 'rgba(255,255,255,0.14)',
            color: 'rgba(255,255,255,0.65)',
            background: 'rgba(255,255,255,0.03)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          The why
        </p>

        <h2
          className="mx-auto mt-7 max-w-[940px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(40px, 6.2vw, 76px)',
            lineHeight: 0.98,
            letterSpacing: '-0.035em',
            color: '#FFFFFF',
          }}
        >
          Why we built{' '}
          <span style={{ color: 'rgba(255,255,255,0.42)' }}>PersonaOn.</span>
        </h2>
      </div>

      <div className="mx-auto -mt-12 max-w-[760px] space-y-7 px-6 pb-32 md:-mt-16 md:pb-40">
        <p
          style={{
            color: '#FFFFFF',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(22px, 2.4vw, 30px)',
            lineHeight: 1.25,
            letterSpacing: '-0.022em',
            fontWeight: 500,
          }}
        >
          The internet gave people profiles. It did not give them presence.
        </p>
        <PInk>
          A profile can list where you work, what you have done, and what you
          care about. But it cannot answer the questions you get every week. It
          cannot explain your thinking. It cannot help someone understand
          whether they should talk to you, learn from you, hire you, or
          collaborate with you.
        </PInk>
        <PInk>So everyone starts from zero.</PInk>
        <PInk>
          PersonaOn changes that. It gives people a page that can represent
          them, answer in their voice, and help others understand them before a
          meeting ever happens.
        </PInk>
        <PInk>The goal is not to replace the human conversation.</PInk>
        <p
          style={{
            color: '#FFFFFF',
            fontFamily: "'Geist', sans-serif",
            fontSize: 'clamp(22px, 2.4vw, 30px)',
            lineHeight: 1.25,
            letterSpacing: '-0.022em',
            fontWeight: 500,
          }}
        >
          The goal is to make the human conversations better.
        </p>
      </div>
    </section>
  );
}

const BELIEFS = [
  {
    title: 'Real over synthetic.',
    body: 'Every persona is anchored to a real human. We do not generate fake people.',
  },
  {
    title: 'Voice belongs to you.',
    body: 'Your persona should sound like you, stay inside your boundaries, and reflect what you have actually said, written, or approved.',
  },
  {
    title: 'Reach without burnout.',
    body: 'Your time is scarce. We help you scale access without giving all of it away.',
  },
  {
    title: 'Show up when it matters.',
    body: 'A persona does not replace meetings. It makes the meetings that happen more useful.',
  },
];

function Beliefs() {
  return (
    <section style={{ background: 'var(--fog-2)' }}>
      <div className="mx-auto max-w-[1100px] px-6 py-32 md:py-40">
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
            What we believe
          </p>

          <h2
            className="mx-auto mt-7 max-w-[920px]"
            style={{
              fontFamily: "'Geist', sans-serif",
              fontWeight: 600,
              fontSize: 'clamp(40px, 6.2vw, 76px)',
              lineHeight: 0.98,
              letterSpacing: '-0.035em',
              color: 'var(--ink)',
            }}
          >
            Four lines we don&rsquo;t cross.
          </h2>
        </div>

        <div
          className="mt-20 grid grid-cols-1 gap-px overflow-hidden rounded-[28px] sm:grid-cols-2"
          style={{ background: 'rgba(29,29,31,0.10)' }}
        >
          {BELIEFS.map((b, i) => (
            <div
              key={b.title}
              className="flex flex-col p-10 md:p-12"
              style={{ background: 'var(--fog-2)', minHeight: 240 }}
            >
              <span
                className="text-[10px] uppercase tracking-[0.2em]"
                style={{
                  color: 'var(--fg-3)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                0{i + 1}
              </span>
              <p
                className="mt-6"
                style={{
                  color: 'var(--ink)',
                  fontFamily: "'Geist', sans-serif",
                  fontSize: 'clamp(24px, 2.6vw, 34px)',
                  lineHeight: 1.15,
                  letterSpacing: '-0.025em',
                  fontWeight: 600,
                }}
              >
                {b.title}
              </p>
              <p
                className="mt-3 text-[15.5px] leading-[1.6]"
                style={{
                  color: 'var(--fg-2)',
                  fontFamily: "'Geist', sans-serif",
                  letterSpacing: '-0.005em',
                }}
              >
                {b.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ClosingCta() {
  return (
    <section style={{ background: 'var(--fog)' }}>
      <div className="mx-auto max-w-[1024px] px-6 py-32 text-center md:py-40">
        <h2
          className="mx-auto max-w-[900px]"
          style={{
            fontFamily: "'Geist', sans-serif",
            fontWeight: 600,
            fontSize: 'clamp(48px, 8vw, 112px)',
            lineHeight: 0.96,
            letterSpacing: '-0.04em',
            color: 'var(--ink)',
          }}
        >
          Reachable{' '}
          <span style={{ color: 'var(--fg-3)' }}>without being available.</span>
        </h2>

        <div className="mt-12 flex flex-wrap items-center justify-center gap-x-7 gap-y-3">
          <Link
            href="/auth/signup"
            className="inline-flex items-center gap-2 rounded-full px-7 transition-opacity hover:opacity-90"
            style={{
              height: 50,
              background: 'var(--ink)',
              color: '#FFFFFF',
              fontSize: 15,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.01em',
              fontWeight: 500,
            }}
          >
            Create your persona
          </Link>
          <a
            href="mailto:admin@personaon.com"
            className="inline-flex items-center gap-1 transition-opacity hover:opacity-60"
            style={{
              color: 'var(--ink)',
              fontSize: 15,
              fontFamily: "'Geist', sans-serif",
              letterSpacing: '-0.01em',
              fontWeight: 500,
            }}
          >
            Talk to a human first
            <span aria-hidden style={{ fontSize: 18, lineHeight: 1 }}>
              &rsaquo;
            </span>
          </a>
        </div>

        <p
          className="mt-8 text-[12px] uppercase tracking-[0.2em]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          admin@personaon.com
        </p>
      </div>
    </section>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="text-left text-[18px] leading-[1.65]"
      style={{
        color: 'var(--fg-2)',
        fontFamily: "'Geist', sans-serif",
        letterSpacing: '-0.005em',
      }}
    >
      {children}
    </p>
  );
}

function PInk({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="text-left text-[18px] leading-[1.65]"
      style={{
        color: 'rgba(255,255,255,0.74)',
        fontFamily: "'Geist', sans-serif",
        letterSpacing: '-0.005em',
      }}
    >
      {children}
    </p>
  );
}
