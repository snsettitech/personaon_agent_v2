import type { IngestionResponse } from '@/lib/ingestionApi';

/**
 * What the owner says an uploaded file is.
 * - `knowledge`: general material the persona can cite (default).
 * - `resume`: the owner's own resume/CV. The backend labels it `identity` and
 *   proposes Passport profile claims from it (PON-8) — nothing is approved
 *   automatically.
 */
export type UploadKind = 'knowledge' | 'resume';

export interface UploadLabelFields {
  label: 'identity' | 'knowledge';
  identityConfirmed: boolean;
}

export function uploadLabelFields(kind: UploadKind): UploadLabelFields {
  return kind === 'resume'
    ? { label: 'identity', identityConfirmed: true }
    : { label: 'knowledge', identityConfirmed: false };
}

export const RESUME_PROPOSED_NOTICE =
  'Resume uploaded. Profile facts found in it were added as proposals — they stay off your persona until you review and approve them.';

export const RESUME_DUPLICATE_NOTICE =
  'This file was already uploaded, so no new profile facts were proposed.';

export const RESUME_NO_FACTS_NOTICE =
  'Resume uploaded, but no new profile facts were found to propose.';

export function resumeProposedCountNotice(count: number): string {
  const facts = count === 1 ? '1 profile fact' : `${count} profile facts`;
  return `Resume uploaded. ${facts} added as proposals — they stay off your persona until you review and approve them.`;
}

/** Owner-facing notice after a resume upload, or null for knowledge uploads. */
export function resumeUploadNotice(
  kind: UploadKind,
  result: IngestionResponse
): string | null {
  if (kind !== 'resume') return null;
  const count = result.proposed_count;
  if (typeof count === 'number') {
    if (count > 0) return resumeProposedCountNotice(count);
    return result.duplicate ? RESUME_DUPLICATE_NOTICE : RESUME_NO_FACTS_NOTICE;
  }
  // Older backends do not report a count.
  return result.duplicate ? RESUME_DUPLICATE_NOTICE : RESUME_PROPOSED_NOTICE;
}
