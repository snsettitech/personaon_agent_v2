'use client';

import React from 'react';
import Link from 'next/link';
import type { HomeStatus } from '@/lib/hooks/useHomeStatus';

/**
 * "What's happening" cards for the Assistant Home (plan step A3).
 *
 * A compact 3-up grid shown under the hero's suggestion chips on the empty
 * state. Every card is backed by a real read and renders ONLY when it has data
 * — no placeholders, no zero-state theatre. If nothing has data, the whole
 * section is absent.
 */
export function HomeStatusCards({ status }: { status: HomeStatus }) {
  const { readiness, pending, conversationCount } = status;

  const waiting = pending
    ? (pending.to_review || 0) + (pending.follow_ups || 0) + (pending.visitor_questions || 0)
    : 0;

  const cards: React.ReactNode[] = [];

  if (readiness) {
    const pct = readiness.max > 0 ? Math.round((readiness.score / readiness.max) * 100) : 0;
    cards.push(
      <Card key="readiness" label="Readiness">
        <div className="text-2xl font-semibold text-neutral-900">{pct}%</div>
        <div className="mt-1 text-sm text-neutral-500">{readiness.label}</div>
      </Card>,
    );
  }

  if (waiting > 0 && pending) {
    const parts: string[] = [];
    if (pending.follow_ups) parts.push(`${pending.follow_ups} follow-up${pending.follow_ups === 1 ? '' : 's'}`);
    if (pending.to_review) parts.push(`${pending.to_review} to review`);
    if (pending.visitor_questions) {
      parts.push(`${pending.visitor_questions} question${pending.visitor_questions === 1 ? '' : 's'}`);
    }
    cards.push(
      <Card key="awaiting" label="Awaiting you" accent>
        <div className="text-2xl font-semibold text-amber-700">{waiting}</div>
        <div className="mt-1 text-sm text-neutral-600">{parts.join(' · ')}</div>
        <Link
          href="/dashboard/conversations"
          className="mt-2 inline-block text-sm font-medium text-amber-700 hover:underline"
        >
          review →
        </Link>
      </Card>,
    );
  }

  if (conversationCount && conversationCount > 0) {
    cards.push(
      <Card key="recent" label="Recent">
        <div className="text-2xl font-semibold text-neutral-900">{conversationCount}</div>
        <div className="mt-1 text-sm text-neutral-500">
          recent conversation{conversationCount === 1 ? '' : 's'}
        </div>
        <Link
          href="/dashboard/conversations"
          className="mt-2 inline-block text-sm font-medium text-blue-600 hover:underline"
        >
          open →
        </Link>
      </Card>,
    );
  }

  if (cards.length === 0) return null;

  return (
    <div>
      <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-neutral-400">
        What&apos;s happening
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{cards}</div>
    </div>
  );
}

function Card({
  label,
  accent,
  children,
}: {
  label: string;
  accent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-2xl border px-4 py-4 ${
        accent ? 'border-amber-200 bg-amber-50/50' : 'border-neutral-200 bg-white'
      }`}
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="mt-2">{children}</div>
    </div>
  );
}
