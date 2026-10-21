/**
 * W9c — Single source of truth for ``brief_json`` shape on the frontend.
 *
 * Mirrors the backend ``_empty_brief_contract`` in
 * ``backend/adk_core/services/persona_core/brief.py``.
 *
 * v1 fields stay populated for one release cycle (per the W9a plan) so
 * older briefs in storage continue to render unchanged. v2 fields are all
 * optional with safe defaults so the page can read them with ``?? []`` /
 * ``?? null`` and never crash on a v1 brief.
 */

export interface BriefPerson {
  name?: string | null;
  email?: string | null;
  role?: string | null;
  company?: string | null;
  bio?: string | null;
  signals?: string[];
  // v1 person block can carry additional enrichment fields — keep
  // permissive at the boundary so renames downstream don't break the UI.
  [key: string]: unknown;
}

export interface BriefHook {
  label: string;
  text: string;
}

export interface PriorMeeting {
  meeting_id: string;
  date: string;
  title: string;
  summary: string;
  status: 'open' | 'done';
}

export interface OpenCommitment {
  description: string;
  days_open: number;
  from_meeting_id?: string;
  from_meeting_date?: string;
  source_quote?: string;
}

// ---------------------------------------------------------------------------
// v2 fields
// ---------------------------------------------------------------------------

export interface PDLSnapshot {
  company?: string | null;
  role?: string | null;
  as_of?: string;
}

export interface ParticipantInsight {
  name: string;
  email: string;
  role: string | null;
  background: string | null;
  recent_activities: string[];
  web_sources: string[];
  pdl_snapshot: PDLSnapshot | null;
}

export interface TalkingPoint {
  topic: string;
  rationale: string;
}

export interface PreviousInteraction {
  meeting_id: string;
  date: string;
  meeting_title: string;
  summary: string;
  open_items: string[];
}

export type CautionSourceRefType =
  | 'meeting_id'
  | 'note_id'
  | 'source_id'
  | 'date'
  | 'none';

export interface CautionSource {
  kind: string;
  ref: string;
  ref_type: CautionSourceRefType;
  quote: string;
}

export interface CautionNote {
  text: string;
  source: CautionSource;
}

export interface SourcesUsed {
  kb_chunks: number;
  web_results: number;
  past_meetings: number;
}

// ---------------------------------------------------------------------------
// Top-level contract
// ---------------------------------------------------------------------------

export interface BriefContract {
  schema_version?: 1 | 2;
  meeting_id: string;
  meeting_title: string;
  meeting_start?: string | null;

  // v1 keys — always present after the backend writes a brief
  person: BriefPerson | null;
  your_goal: string | null;
  your_context: string | null;
  prior_meetings: PriorMeeting[];
  hooks: BriefHook[];
  open_commitments: OpenCommitment[];
  generated_at?: string;

  // v2 keys — optional with safe defaults for backward compat
  participant_insights?: ParticipantInsight[];
  talking_points?: TalkingPoint[];
  previous_interactions?: PreviousInteraction[];
  suggested_agenda?: string[];
  caution_notes?: CautionNote[];
  sources_used?: SourcesUsed;

  // W9d — opt-in deep research mode. Set when a deep ReAct run has
  // merged into this brief. The frontend uses it both as a cache key
  // (don't re-trigger when fresh) and as a footer indicator ("Deep
  // research from {time}").
  deep_generated_at?: string;
}

// ---------------------------------------------------------------------------
// Display helpers — single source of truth so all sections agree.
// ---------------------------------------------------------------------------

/**
 * Did this brief come from the v2 engine? Drives v2-specific rendering
 * (Heads Up, multi-attendee insights, etc.). v1 briefs render unchanged.
 */
export function isV2(brief: BriefContract): boolean {
  return brief.schema_version === 2;
}

/**
 * The primary attendee's display name for the hero "You × X" line.
 *
 * v2: read from ``participant_insights[0].name`` first — for v2 briefs
 * without PDL enrichment, ``person.name`` is null but the insight stub
 * still has the calendar display name.
 *
 * v1: fall back to ``person.name``.
 *
 * Last-resort fallback is "this person" rather than empty, so the hero
 * line never reads "You ×  ".
 */
export function primaryDisplayName(brief: BriefContract): string {
  const first = (brief.participant_insights || [])[0];
  if (first?.name) return first.name;
  if (brief.person?.name) return brief.person.name;
  return 'this person';
}

/**
 * Just the first word of the primary display name — used in section
 * eyebrows like "Your history with Sarah".
 */
export function shortFirstName(brief: BriefContract): string {
  const full = primaryDisplayName(brief);
  return full.split(/\s+/)[0] || full;
}
