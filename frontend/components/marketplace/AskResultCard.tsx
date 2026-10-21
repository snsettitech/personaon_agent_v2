'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import type { AskResult } from '@/lib/hooks/useMarketplaceAsk';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function relevanceColor(score: number): string {
  if (score >= 85) return 'var(--accent-emerald)';
  if (score >= 70) return 'var(--accent-trust)';
  return 'var(--text-tertiary)';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface AskResultCardProps {
  result: AskResult;
  rank: number;
}

export default function AskResultCard({ result, rank }: AskResultCardProps) {
  const { persona, snippet, relevance } = result;
  const href = persona.public_url || '/marketplace';
  const color = relevanceColor(relevance);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: rank * 0.06 }}
    >
      <Link
        href={href}
        className="group flex items-start gap-5 rounded-[24px] p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg"
        style={{
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        {/* Rank badge */}
        <div className="flex flex-col items-center gap-2 pt-1">
          {rank === 0 && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest"
              style={{ backgroundColor: 'rgba(5,150,105,0.12)', color: 'var(--accent-emerald)' }}
            >
              Best
            </span>
          )}
          {/* Avatar */}
          {persona.avatar_url ? (
            <img
              src={persona.avatar_url}
              alt={persona.display_name}
              className="h-14 w-14 rounded-2xl object-cover"
            />
          ) : (
            <div
              className="flex h-14 w-14 items-center justify-center rounded-2xl text-base font-semibold text-white"
              style={{ background: 'linear-gradient(135deg, #F59E0B, #EA580C)' }}
            >
              {getInitials(persona.display_name) || 'P'}
            </div>
          )}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {/* Name + occupation row */}
          <div className="flex flex-wrap items-center gap-2">
            <h3
              className="text-lg font-semibold leading-tight"
              style={{ color: 'var(--text-primary)' }}
            >
              {persona.display_name}
            </h3>
            {persona.verified_profile && (
              <span
                className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]"
                style={{ backgroundColor: '#d1fae5', color: '#059669' }}
              >
                Verified
              </span>
            )}
            <span
              className="text-sm"
              style={{ color: 'var(--text-tertiary)' }}
            >
              {persona.occupation}
            </span>
          </div>

          {/* Snippet preview */}
          <p
            className="mt-2 text-sm leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            &ldquo;{snippet}&rdquo;
          </p>

          {/* Bottom row: relevance bar + CTA */}
          <div className="mt-3 flex items-center justify-between gap-4">
            {/* Relevance indicator */}
            <div className="flex items-center gap-2.5">
              <div
                className="h-1.5 w-24 overflow-hidden rounded-full"
                style={{ backgroundColor: 'var(--bg-surface)' }}
              >
                <motion.div
                  className="h-full rounded-full"
                  style={{ backgroundColor: color }}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(relevance, 100)}%` }}
                  transition={{ duration: 0.5, delay: rank * 0.06 + 0.2 }}
                />
              </div>
              <span
                className="text-xs font-medium tabular-nums"
                style={{ color }}
              >
                {relevance.toFixed(0)}% match
              </span>
            </div>

            {/* CTA */}
            <span
              className="shrink-0 text-sm font-medium transition-colors group-hover:opacity-80"
              style={{ color: 'var(--primary-600)' }}
            >
              Talk to {persona.display_name.split(' ')[0]} &rarr;
            </span>
          </div>
        </div>
      </Link>
    </motion.div>
  );
}
