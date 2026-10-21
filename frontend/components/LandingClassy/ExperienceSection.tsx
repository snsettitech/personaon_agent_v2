'use client';

import Link from 'next/link';
import { FileText, MessageCircle, Sparkles } from 'lucide-react';

import { analytics } from '@/lib/analytics/events';

const MONO = "'JetBrains Mono', monospace";
const SANS = "'Geist', sans-serif";
const SERIF = "'Instrument Serif', Georgia, serif";

const STEPS = [
  { icon: FileText, tag: '01', label: 'Drop your resume', detail: 'PDF or DOCX — read in seconds.' },
  { icon: Sparkles, tag: '02', label: 'We compile your twin', detail: 'Your background, in your voice.' },
  { icon: MessageCircle, tag: '03', label: 'Chat with it live', detail: 'Ask it anything, right away.' },
];

export default function ExperienceSection() {
  return (
    <section className="relative" style={{ backgroundColor: 'var(--fog)' }} id="experience">
      <div className="mx-auto max-w-[1100px] px-6 py-28 md:py-36">
        <div
          className="overflow-hidden"
          style={{
            borderRadius: 32,
            border: '1px solid rgba(29,29,31,0.08)',
            background: 'linear-gradient(180deg, var(--fog-2) 0%, var(--fog-3) 100%)',
            boxShadow: '0 50px 110px rgba(29,29,31,0.10), 0 8px 24px rgba(29,29,31,0.05)',
          }}
        >
          <div className="px-8 py-14 text-center md:px-16 md:py-20">
            <p className="inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-2)', fontFamily: MONO }}>
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: '#2BB673' }} />
              Try it on yourself — no signup
            </p>

            <h2
              className="mx-auto mt-6 max-w-[760px]"
              style={{ color: 'var(--ink)', fontFamily: SERIF, fontSize: 'clamp(36px, 5.4vw, 64px)', lineHeight: 1.02, letterSpacing: '-0.01em' }}
            >
              See your own AI twin
              <br />
              before you sign up.
            </h2>

            <p className="mx-auto mt-6 max-w-[540px] text-[17px]" style={{ color: 'var(--fg-2)', fontFamily: SANS, lineHeight: 1.45 }}>
              Upload your resume, answer two quick questions, and chat with the persona PersonaOn would build for
              you — live, in about a minute.
            </p>

            <div className="mx-auto mt-12 grid max-w-[820px] grid-cols-1 gap-3.5 sm:grid-cols-3">
              {STEPS.map(({ icon: Icon, tag, label, detail }) => (
                <div
                  key={tag}
                  className="flex flex-col items-start p-5 text-left"
                  style={{ borderRadius: 18, border: '1px solid rgba(29,29,31,0.08)', background: 'var(--fog-2)' }}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-full" style={{ background: 'var(--ink)', color: '#fff' }}>
                      <Icon size={16} />
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.2em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
                      {tag}
                    </span>
                  </div>
                  <p className="mt-4 text-[15px]" style={{ color: 'var(--ink)', fontFamily: SANS, fontWeight: 600 }}>
                    {label}
                  </p>
                  <p className="mt-1 text-[13.5px]" style={{ color: 'var(--fg-2)', fontFamily: SANS }}>
                    {detail}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-12 flex flex-col items-center gap-3">
              <Link
                href="/experience"
                onClick={() => analytics.landingCtaClicked({ cta_type: 'try_demo', position: 'experience_section' })}
                className="inline-flex items-center gap-2 rounded-full px-7 transition-opacity hover:opacity-90"
                style={{ height: 50, background: 'var(--ink)', color: '#fff', fontFamily: SANS, fontSize: 15, fontWeight: 500 }}
              >
                Build my twin — free
                <span aria-hidden style={{ fontSize: 17, lineHeight: 1 }}>
                  &rsaquo;
                </span>
              </Link>
              <p className="text-[12px] uppercase tracking-[0.18em]" style={{ color: 'var(--fg-3)', fontFamily: MONO }}>
                Resume processed in memory · discarded after · nothing stored
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
