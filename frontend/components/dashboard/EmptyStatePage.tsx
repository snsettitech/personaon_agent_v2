'use client';

import React from 'react';
import Link from 'next/link';

function ShieldIcon(): React.JSX.Element {
  return (
    <svg
      className="w-5 h-5 text-teal-600"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l8 4v5c0 5.25-3.438 9.688-8 11-4.562-1.312-8-5.75-8-11V7l8-4z" />
    </svg>
  );
}

function CheckmarkIcon(): React.JSX.Element {
  return (
    <svg
      className="w-5 h-5 text-teal-600"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function LightningIcon(): React.JSX.Element {
  return (
    <svg
      className="w-5 h-5 text-teal-600"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>
  );
}

function PersonaOnLogo(): React.JSX.Element {
  return (
    <div className="w-12 h-12 bg-teal-600 rounded-2xl flex items-center justify-center">
      <svg
        className="w-7 h-7 text-white"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    </div>
  );
}

export function EmptyStatePage(): React.JSX.Element {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--bg-base)] px-6">
      {/* Logo */}
      <PersonaOnLogo />

      {/* Headline */}
      <h1 className="font-display text-3xl md:text-4xl font-bold text-[var(--text-primary)] mt-8 text-center">
        Let&apos;s build your AI persona
      </h1>

      {/* Subtext */}
      <p className="text-lg text-stone-500 mt-4 text-center max-w-md">
        Your approved sources, always available. It takes about 2 minutes to get started.
      </p>

      {/* CTA */}
      <Link
        href="/onboarding"
        className="btn-cta mt-8 text-lg px-8 py-4 w-full sm:w-auto text-center"
      >
        Create Your Persona
      </Link>

      {/* Trust indicators */}
      <div className="mt-12 flex flex-col sm:flex-row gap-6 items-center">
        <div className="flex items-center gap-3">
          <ShieldIcon />
          <span className="text-sm text-stone-500">Your data stays private</span>
        </div>
        <div className="flex items-center gap-3">
          <CheckmarkIcon />
          <span className="text-sm text-stone-500">Sources only</span>
        </div>
        <div className="flex items-center gap-3">
          <LightningIcon />
          <span className="text-sm text-stone-500">Live in under 10 minutes</span>
        </div>
      </div>
    </div>
  );
}

export default EmptyStatePage;
