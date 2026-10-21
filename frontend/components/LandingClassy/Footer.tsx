import Link from 'next/link';

export default function Footer() {
  return (
    <footer
      style={{
        background: 'var(--fog-3)',
        color: 'var(--fg-2)',
        borderTop: '1px solid rgba(29,29,31,0.08)',
      }}
    >
      <div className="mx-auto max-w-[1100px] px-6 py-12">
        <p
          className="mb-8 max-w-[640px] text-[12px] leading-[1.55]"
          style={{
            color: 'var(--fg-3)',
            fontFamily: "'Geist', sans-serif",
          }}
        >
          PersonaOn anchors every persona to a real person. Voices are recorded by
          the human they belong to. Answers are sourced from material that person
          has approved. PersonaOn is not a synthetic-avatar product.
        </p>

        <div
          className="mb-8 grid grid-cols-2 gap-y-8 sm:grid-cols-4"
          style={{
            borderTop: '1px solid rgba(29,29,31,0.08)',
            paddingTop: 32,
          }}
        >
          <FooterCol
            title="Product"
            links={[
              { label: 'What it is', href: '#what' },
              { label: 'How it works', href: '#how' },
              { label: 'Who it’s for', href: '#who' },
              { label: 'Marketplace', href: '/marketplace' },
            ]}
          />
          <FooterCol
            title="Account"
            links={[
              { label: 'Sign in', href: '/auth/login' },
              { label: 'Create your persona', href: '#claim' },
            ]}
          />
          <FooterCol
            title="Company"
            links={[
              { label: 'About', href: '/about' },
              { label: 'Contact', href: 'mailto:admin@personaon.com' },
            ]}
          />
          <FooterCol
            title="Legal"
            links={[
              { label: 'Terms', href: '/legal/terms' },
              { label: 'Privacy', href: '/legal/privacy' },
            ]}
          />
        </div>

        <div
          className="flex flex-col gap-3 border-t pt-8 text-[11px] uppercase tracking-[0.18em] sm:flex-row sm:items-center sm:justify-between"
          style={{
            borderColor: 'rgba(29,29,31,0.08)',
            color: 'var(--fg-3)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <span>&copy; {new Date().getFullYear()} PersonaOn</span>
          <span>Maintained by an agent &middot; PersonaOn</span>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({
  title,
  links,
}: {
  title: string;
  links: ReadonlyArray<{ label: string; href: string }>;
}) {
  return (
    <div>
      <p
        className="mb-3 text-[11px] uppercase tracking-[0.2em]"
        style={{
          color: 'var(--fg-3)',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {title}
      </p>
      <ul className="flex flex-col gap-2">
        {links.map((l) => (
          <li key={l.label}>
            <Link
              href={l.href}
              className="text-[13px] transition-opacity hover:opacity-60"
              style={{
                color: 'var(--fg)',
                fontFamily: "'Geist', sans-serif",
                letterSpacing: '-0.005em',
              }}
            >
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
