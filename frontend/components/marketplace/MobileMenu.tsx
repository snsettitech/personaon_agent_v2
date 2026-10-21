'use client';

import { useState } from 'react';
import Link from 'next/link';
import NavAuthButtons from './NavAuthButtons';

interface MobileMenuProps {
  navLinks: Array<{ label: string; href: string }>;
}

export default function MobileMenu({ navLinks }: MobileMenuProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="md:hidden">
      {/* Hamburger button */}
      <button
        className="cursor-pointer p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors duration-150"
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Toggle menu"
        aria-expanded={isOpen}
        aria-controls="mobile-menu"
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          {isOpen ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>

      {/* Mobile dropdown */}
      {isOpen && (
        <div
          id="mobile-menu"
          className="absolute top-full left-0 right-0 mt-1 border-t border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-5 py-4 space-y-3 shadow-lg rounded-b-2xl"
        >
          {navLinks.map(({ label, href }) => (
            <Link
              key={href}
              href={href}
              className="block text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors duration-150"
              onClick={() => setIsOpen(false)}
            >
              {label}
            </Link>
          ))}

          <div className="pt-2 border-t border-[var(--border-subtle)]">
            <NavAuthButtons />
          </div>
        </div>
      )}
    </div>
  );
}
