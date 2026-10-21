'use client';

import Link from 'next/link';
import NavAuthButtons from '@/components/marketplace/NavAuthButtons';
import MobileMenu from '@/components/marketplace/MobileMenu';
import { Wordmark } from '@/components/brand/Wordmark';

const NAV_LINKS = [
  { label: 'Marketplace', href: '/marketplace' },
  { label: 'About', href: '/about' },
  { label: 'Pricing', href: '/pricing' },
];

export default function MarketplaceNav() {
  return (
    <nav
      className="fixed top-4 left-4 right-4 z-50 rounded-2xl backdrop-blur-xl shadow-xl"
      style={{
        backgroundColor: 'rgba(255,255,255,0.9)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      <div className="mx-auto max-w-7xl px-5 lg:px-8 relative">
        <div className="flex items-center justify-between h-14">
          <Wordmark href="/" size="sm" />

          <div className="hidden md:flex items-center gap-7">
            {NAV_LINKS.map(({ label, href }) => (
              <Link
                key={href}
                href={href}
                className="text-sm transition-colors duration-150"
                style={{ color: 'var(--text-secondary)' }}
              >
                {label}
              </Link>
            ))}
            <NavAuthButtons />
          </div>

          <MobileMenu navLinks={NAV_LINKS} />
        </div>
      </div>
    </nav>
  );
}
