/**
 * Shared meaningfulness validation for user-authored profile text (bio, headline).
 *
 * Mirrors `backend/modules/text_quality.py` — keep both in sync (same
 * thresholds, same messages). Root cause (PRD R1, execution-board 0.2): a
 * live persona page shipped with headline "software engineer" and bio
 * literally "nill" because nothing checked whether the text was meaningful,
 * only HTML/injection sanitization existed.
 *
 * Client-side checks here are a UX nicety (fail fast, inline message before
 * the round-trip) — the backend validators in text_quality.py are the real
 * enforcement boundary and must never be relaxed to match a looser client
 * check.
 */

// Bio-style free text ("at least a sentence") — the PRD's explicit bar.
export const BIO_MIN_LENGTH = 40;

// Headlines are legitimately short and often a single word ("CEO",
// "Founder"), so they don't get the bio's 40-char/2-word bar.
export const HEADLINE_MIN_LENGTH = 3;

interface MeaningfulTextOptions {
  minLength?: number;
  minWords?: number;
}

function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, '');
}

// Whole string is 2+ back-to-back copies of the same 1-20 char chunk, e.g.
// "aaaa", "asdfasdfasdf", "abab". Applied after whitespace is stripped so
// "asdf asdf asdf" is caught the same way as "asdfasdfasdf".
const REPEATING_PATTERN_RE = /^(.{1,20}?)\1+$/;

function isLowEntropy(candidate: string, words: string[]): boolean {
  const collapsed = collapseWhitespace(candidate).toLowerCase();
  if (!collapsed) return true;

  if (REPEATING_PATTERN_RE.test(collapsed)) return true;

  const lowerWords = words.map((word) => word.toLowerCase());
  if (lowerWords.length >= 3 && new Set(lowerWords).size <= 2) return true;

  if (collapsed.length >= 12 && new Set(collapsed).size <= 3) return true;

  return false;
}

/**
 * Return a user-facing, inline-message-worthy error if `text` fails the
 * meaningfulness bar, else null. Mirrors
 * `backend/modules/text_quality.py::meaningful_text_error`.
 */
export function meaningfulTextError(
  text: string | null | undefined,
  options: MeaningfulTextOptions = {},
): string | null {
  const { minLength = BIO_MIN_LENGTH, minWords = 2 } = options;
  const candidate = (text ?? '').trim();

  if (!candidate) {
    return 'Tell us a bit more — at least a sentence.';
  }
  if (candidate.length < minLength) {
    return `Tell us a bit more — at least a sentence (${minLength}+ characters).`;
  }

  const words = candidate.split(/\s+/).filter(Boolean);
  if (minWords > 1 && words.length < minWords) {
    return 'Tell us a bit more — at least a sentence, not a single word.';
  }

  if (isLowEntropy(candidate, words)) {
    return "That doesn't look like real content — please write a genuine sentence about yourself.";
  }

  return null;
}

export function isMeaningfulText(
  text: string | null | undefined,
  options: MeaningfulTextOptions = {},
): boolean {
  return meaningfulTextError(text, options) === null;
}

/**
 * Headline-specific wrapper: same low-entropy/whitespace checks as bio, but a
 * much lower length floor and single-word input allowed (real headlines are
 * often one word — "CEO", "Founder").
 */
export function headlineTextError(text: string | null | undefined): string | null {
  return meaningfulTextError(text, { minLength: HEADLINE_MIN_LENGTH, minWords: 1 });
}
