'use client';

import React, { useState } from 'react';
import { API_ENDPOINTS } from '@/lib/constants';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { useToast } from '@/components/ui';

interface ExtractionReviewCardProps {
  issues: string[];
  twinId: string;
  onDismissed: () => void;
}

const RE_UNDERSTATED = /'([^']+)'\s+but.*?~([\d.]+)y.*?~([\d.]+)y/i;
const RE_SINGLE_YEAR = /'([^']+?)\s+at\s+([^']+)'.*?(\d{4})-(\d{4})/i;
const RE_DATE_INVERTED = /'([^']+)'/i;

function roundYears(value: string): string {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return value;
  return String(Math.round(parsed));
}

/** Translate a raw issue string into owner-friendly copy. Falls back to the raw string. */
function friendlyMessage(raw: string): string {
  const trimmed = raw.trim();
  const colonIdx = trimmed.indexOf(':');
  const prefix = colonIdx >= 0 ? trimmed.slice(0, colonIdx).trim() : '';

  if (prefix === 'understated_tenure') {
    const match = trimmed.match(RE_UNDERSTATED);
    if (match) {
      const [, company, bioYears, listedYears] = match;
      return `Your time at ${company} may be understated — your bio suggests ~${roundYears(bioYears)} years but your listed roles add up to ~${roundYears(listedYears)}. Check your work history below.`;
    }
    return trimmed;
  }

  if (prefix === 'single_year_span') {
    const match = trimmed.match(RE_SINGLE_YEAR);
    if (match) {
      const [, role, company, startYear, endYear] = match;
      return `'${role.trim()} at ${company.trim()}' shows just one year (${startYear}–${endYear}). If it lasted longer, add the real start/end years.`;
    }
    return trimmed;
  }

  if (prefix === 'date_inverted') {
    const detail = colonIdx >= 0 ? trimmed.slice(colonIdx + 1).trim() : trimmed;
    const match = detail.match(RE_DATE_INVERTED);
    if (match) {
      return `'${match[1].trim()}' has its end year before its start year — please fix the dates.`;
    }
    return trimmed;
  }

  return trimmed;
}

export function ExtractionReviewCard({ issues, twinId, onDismissed }: ExtractionReviewCardProps) {
  const { showToast } = useToast();
  const [submitting, setSubmitting] = useState(false);

  if (!issues || issues.length === 0) return null;

  const messages = issues.map((issue) => friendlyMessage(issue));

  const handleDismiss = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const endpoint = `${API_ENDPOINTS.TWIN_PROFILE_INSIGHTS(twinId)}/dismiss-review`;
      const response = await authFetchStandalone(endpoint, { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Dismiss request failed (status ${response.status})`);
      }
      // Narrow the JSON body at the fetch boundary.
      const body: unknown = await response.json().catch(() => null);
      const dismissed =
        typeof body === 'object' &&
        body !== null &&
        'status' in body &&
        (body as { status: unknown }).status === 'ok';
      if (!dismissed) {
        throw new Error('Dismiss response was not acknowledged');
      }
      showToast('Thanks — those details are confirmed.', 'success');
      onDismissed();
    } catch (error: unknown) {
      console.error('[ExtractionReviewCard] Failed to dismiss review:', error);
      showToast('Could not dismiss the review. Please try again.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mb-5 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-900 shadow-sm md:p-6">
      <div className="flex items-start gap-3">
        <svg className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01M5.07 19h13.86a2 2 0 001.74-2.99L13.74 4a2 2 0 00-3.48 0L3.33 16.01A2 2 0 005.07 19z" />
        </svg>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">A few details to confirm</h2>
          <p className="mt-1 text-sm text-amber-800">
            PersonaOn flagged a few things from your auto-built profile that only you can confirm.
          </p>
          <ul className="mt-3 space-y-2">
            {messages.map((message, idx) => (
              <li key={idx} className="flex gap-2 text-sm leading-relaxed text-amber-900">
                <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                <span>{message}</span>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleDismiss}
              disabled={submitting}
              className="inline-flex items-center justify-center rounded-xl bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Dismissing…' : 'Looks right — dismiss'}
            </button>
            <span className="text-xs text-amber-700">Or edit your work history below to correct anything.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ExtractionReviewCard;
