'use client';

import React from 'react';
import { useRouter } from 'next/navigation';

interface PrefillChip {
  key: string;
  emoji: string;
  label: string;
  prompt: string;
}

/**
 * The four-job entry chips for the Assistant Home (plan step A4).
 *
 * Improve / Respond / Show PREFILL the assistant input (via ChatInterface's
 * reactive `initialInput`) so the owner can edit before sending — they never
 * auto-send. Meet DEEP-LINKS to the meetings surface, since it's a different
 * page, not a chat action. Every chip points at something real.
 */
const PREFILLS: PrefillChip[] = [
  { key: 'improve', emoji: '✨', label: 'Improve', prompt: 'What should I add to make my persona answer better?' },
  { key: 'respond', emoji: '✉️', label: 'Respond', prompt: 'Who is waiting on a reply from me, and can you help me draft one?' },
  { key: 'show', emoji: '📊', label: 'Show', prompt: 'How has my persona been doing lately?' },
];

const CHIP_CLASS =
  'inline-flex items-center gap-1.5 rounded-full border border-neutral-200 bg-white px-3 py-1.5 ' +
  'text-sm font-medium text-neutral-700 transition hover:border-neutral-300 hover:bg-neutral-50 ' +
  'dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-800';

export function HomeJobChips({ onPrefill }: { onPrefill: (prompt: string) => void }) {
  const router = useRouter();

  return (
    <div className="mb-4 flex flex-wrap gap-2">
      {PREFILLS.map((chip) => (
        <button key={chip.key} type="button" onClick={() => onPrefill(chip.prompt)} className={CHIP_CLASS}>
          <span aria-hidden>{chip.emoji}</span> {chip.label}
        </button>
      ))}
      <button type="button" onClick={() => router.push('/dashboard/meetings')} className={CHIP_CLASS}>
        <span aria-hidden>📅</span> Meet
      </button>
    </div>
  );
}
