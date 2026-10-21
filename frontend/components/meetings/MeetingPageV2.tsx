'use client';

/**
 * Phase B — the unified, phase-aware meeting page (one URL, tabs, highlights-first,
 * conditional sections, honest no-transcript states). Rendered only when the
 * `meetings_v2` flag is on; the legacy layout is untouched.
 * See docs/product/meetings-spec-and-plan.md.
 */
import React, { useEffect, useState } from 'react';
import BriefTabContent from '@/components/meetings/BriefTabContent';
import NotesTabContent from '@/components/meetings/NotesTabContent';
import TwinAttendanceToggle from '@/components/meetings/TwinAttendanceToggle';
import SpeakerAnalyticsSection, { type SpeakerAnalytics } from '@/components/meetings/SpeakerAnalyticsSection';
import TwinActivityReview, { type TwinResponse } from '@/components/meetings/TwinActivityReview';
import ShareRecapModal from '@/components/meetings/ShareRecapModal';
import LiveTabContent from '@/components/meetings/LiveTabContent';

interface ActionItem { owner: string; description: string; due?: string | null; }
interface Commitment { by: string; to: string; what: string; due?: string | null; }
interface PersonObserved { name: string; role_hint?: string | null; }
interface IntentOutcome { intent: string | null; outcome: string | null; }

export interface MeetingV2Data {
  id: string;
  title: string | null;
  status: string;
  meeting_start: string | null;
  duration_seconds: number | null;
  recap: string | null;
  intent_vs_outcome?: IntentOutcome | null;
  action_items?: ActionItem[] | null;
  commitments?: Commitment[] | null;
  decisions?: string[] | null;
  topics?: string[] | null;
  unanswered_questions?: string[] | null;
  people_observed?: PersonObserved[] | null;
  user_goal?: string | null;
  user_context?: string | null;
  transcript_text?: string | null;
  twin_attends?: boolean | null;
  recall_bot_id?: string | null;
  meet_link?: string | null;
  // Completed-meeting panels (Phase B-final). Already present on the fetched
  // meeting object from /v2/meetings/{twin}/{id}; declared here so the Recap tab
  // can render Speaker Analytics + Twin Activity.
  analytics?: SpeakerAnalytics[] | null;
  twin_responses?: TwinResponse[] | null;
}

interface MeetingPageV2Props {
  meeting: MeetingV2Data;
  twinId: string;
  otherPersonName?: string;
  onBack: () => void;
  // Share, Brief, and Live are all owned internally now (ShareRecapModal,
  // BriefTabContent, LiveTabContent) — no href/handler props needed.
}

type Phase = 'scheduled' | 'live' | 'completed';

function phaseOf(status: string): Phase {
  // Live set kept in sync with partitionMeetings() on the list page so a meeting
  // is "live" in both places (includes 'joining').
  if (['recording', 'bot_joining', 'joining', 'live', 'in_progress'].includes(status)) return 'live';
  // completed/processing/failed/cancelled all land on the "after" view so the recap
  // tab (and its phase-aware empty states) is what the user sees.
  if (['completed', 'processing', 'failed', 'cancelled', 'canceled'].includes(status)) return 'completed';
  return 'scheduled';
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return '';
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `· ${mins} min`;
  const hrs = Math.floor(mins / 60); const rem = mins % 60;
  return rem > 0 ? `· ${hrs} hr ${rem} min` : `· ${hrs} hr`;
}

function hasArr<T>(a: T[] | null | undefined): a is T[] { return Array.isArray(a) && a.length > 0; }

/** Collapsible detail section — only rendered by callers when it has content. */
function Section({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-black/[0.06]" style={{ backgroundColor: 'var(--bg-card, #fff)' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left text-sm font-semibold"
        style={{ color: 'var(--text-primary, #111)' }}
      >
        <span>{title}</span>
        <span style={{ color: 'var(--text-muted, #888)' }}>{open ? '–' : '+'}</span>
      </button>
      {open && <div className="px-5 pb-4 text-sm" style={{ color: 'var(--text-secondary, #444)' }}>{children}</div>}
    </div>
  );
}

export default function MeetingPageV2({
  meeting, twinId, otherPersonName, onBack,
}: MeetingPageV2Props): React.JSX.Element {
  const phase = phaseOf(meeting.status);
  const title = meeting.title || (otherPersonName ? `Meeting with ${otherPersonName}` : 'Untitled meeting');
  const [shareOpen, setShareOpen] = useState(false);

  const tabs: string[] =
    phase === 'completed' ? ['Summary', 'Notes', 'Transcript']
      : phase === 'scheduled' ? ['Brief', 'Notes']
        : ['Live', 'Notes'];
  const [tab, setTab] = useState<string>(tabs[0]);
  // Read ?view= AFTER mount (SSR-safe: server + first client paint both use tabs[0],
  // then the client syncs to the URL — no hydration mismatch). Re-runs on route change.
  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get('view');
    const cap = v ? v.charAt(0).toUpperCase() + v.slice(1) : '';
    if (cap && tabs.includes(cap)) setTab(cap);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Guard against a stale selection if the phase (and thus the tab set) changes.
  const activeTab = tabs.includes(tab) ? tab : tabs[0];

  function selectTab(t: string) {
    setTab(t);
    if (typeof window !== 'undefined') {
      const u = new URL(window.location.href);
      u.searchParams.set('view', t.toLowerCase());
      window.history.replaceState({}, '', u.toString());
    }
  }

  const statusLabel =
    phase === 'live' ? '● Live · Your persona is taking notes'
      : meeting.status === 'cancelled' || meeting.status === 'canceled' ? 'Cancelled'
        : meeting.status === 'failed' ? 'Recording failed'
          : meeting.status === 'processing' ? 'Processing summary…'
            : phase === 'completed' ? '✓ Completed'
              : 'Scheduled';

  const actionItems = meeting.action_items ?? [];
  // The narrative + action items are the "above the fold" highlights card.
  const hasHighlights = Boolean((meeting.recap && meeting.recap.trim()) || hasArr(actionItems));
  // A recap "exists" if ANY structured recap field is populated — not just the
  // narrative. A meeting can have decisions/commitments/topics/etc. without a
  // prose recap; treating those as "no recording" was hiding real data.
  const hasRecap = hasHighlights
    || Boolean(meeting.intent_vs_outcome?.intent)
    || hasArr(meeting.decisions)
    || hasArr(meeting.commitments)
    || hasArr(meeting.unanswered_questions)
    || hasArr(meeting.people_observed)
    || hasArr(meeting.topics);
  const hasTranscript = Boolean(meeting.transcript_text && meeting.transcript_text.trim());

  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-4 space-y-4">
      {/* ── Status header + single back ───────────────────────────────── */}
      <div className="flex items-center justify-between">
        <button type="button" onClick={onBack} className="text-sm font-medium hover:underline" style={{ color: 'var(--text-secondary, #555)' }}>
          ← Upcoming
        </button>
        {phase === 'completed' && hasRecap && twinId && (
          <button
            type="button"
            onClick={() => setShareOpen(true)}
            className="text-sm font-semibold hover:underline"
            style={{ color: 'var(--brand-primary, #0066cc)' }}
          >
            Share summary
          </button>
        )}
      </div>
      <div>
        <h1 className="text-xl font-bold tracking-tight" style={{ color: 'var(--text-primary, #111)' }}>{title}</h1>
        <p className="mt-0.5 text-sm" style={{ color: 'var(--text-secondary, #666)' }}>
          {statusLabel} · {fmtWhen(meeting.meeting_start)} {fmtDuration(meeting.duration_seconds)}
        </p>
      </div>

      {/* ── Tabs ──────────────────────────────────────────────────────── */}
      <div className="flex gap-2 border-b border-black/[0.06] pb-2" role="tablist">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={activeTab === t}
            onClick={() => selectTab(t)}
            className={`rounded-full px-4 py-1.5 text-sm font-semibold ${activeTab === t ? 'bg-[#1d1d1f] text-white' : 'text-[#555] hover:bg-black/[0.04]'}`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Tab content ───────────────────────────────────────────────── */}
      {activeTab === 'Summary' && (
        <div className="space-y-3">
          {hasRecap ? (
          <div className="space-y-3">
            {/* HIGHLIGHTS (above the fold) — only when there's a narrative or action items */}
            {hasHighlights && (
            <div className="rounded-3xl p-5" style={{ backgroundColor: 'var(--bg-card, #fff)', border: '1px solid var(--border-subtle, #eee)' }}>
              {meeting.recap && (
                <p className="text-lg leading-relaxed" style={{ color: 'var(--text-primary, #111)', fontFamily: 'var(--font-serif, Georgia, serif)' }}>
                  {meeting.recap}
                </p>
              )}
              {hasArr(actionItems) && (
                <div className="mt-4">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted, #888)' }}>Action items</p>
                  <ul className="space-y-1.5">
                    {actionItems.map((a, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-primary, #111)' }}>
                        <span>☐</span>
                        <span><span className="font-medium">{a.owner}:</span> {a.description}{a.due ? ` · ${a.due}` : ''}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            )}

            {/* DETAIL — conditional, collapsed (progressive disclosure). NO "my positions". */}
            {meeting.intent_vs_outcome?.intent && (
              <Section title="Intent → outcome">
                <p><strong>You went in for:</strong> {meeting.intent_vs_outcome.intent}</p>
                {meeting.intent_vs_outcome.outcome && <p className="mt-1"><strong>What happened:</strong> {meeting.intent_vs_outcome.outcome}</p>}
              </Section>
            )}
            {hasArr(meeting.decisions) && (
              <Section title="Decisions">
                <ul className="space-y-1">{meeting.decisions!.map((d, i) => <li key={i}>◆ {d}</li>)}</ul>
              </Section>
            )}
            {hasArr(meeting.commitments) && (
              <Section title="Commitments">
                <ul className="space-y-1">{meeting.commitments!.map((c, i) => <li key={i}>{c.by} → {c.to}: {c.what}{c.due ? ` · ${c.due}` : ''}</li>)}</ul>
              </Section>
            )}
            {hasArr(meeting.unanswered_questions) && (
              <Section title="Open questions">
                <ul className="space-y-1">{meeting.unanswered_questions!.map((q, i) => <li key={i}>? {q}</li>)}</ul>
              </Section>
            )}
            {hasArr(meeting.people_observed) && (
              <Section title="People">
                <div className="flex flex-wrap gap-2">
                  {meeting.people_observed!.map((p, i) => (
                    <span key={i} className="rounded-full px-3 py-1 text-xs" style={{ backgroundColor: 'var(--fog, #f3f4f6)' }}>{p.name}{p.role_hint ? ` · ${p.role_hint}` : ''}</span>
                  ))}
                </div>
              </Section>
            )}
            {hasArr(meeting.topics) && (
              <Section title="Topics">
                <div className="flex flex-wrap gap-2">
                  {meeting.topics!.map((t, i) => <span key={i} className="rounded-full bg-[#e8f2ff] px-3 py-1 text-xs text-[#0066cc]">{t}</span>)}
                </div>
              </Section>
            )}
          </div>
          ) : meeting.status === 'processing' ? (
          /* Still generating — never claim "no recording" mid-pipeline. */
          <div className="rounded-3xl p-6 text-center" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)' }}>
            <p className="text-sm font-semibold" style={{ color: 'var(--text-primary, #111)' }}>Generating your summary…</p>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary, #666)' }}>This usually takes a minute after the meeting ends. Check back shortly.</p>
            {hasTranscript && (
              <button type="button" onClick={() => selectTab('Transcript')} className="mt-3 rounded-xl px-4 py-1.5 text-xs font-medium" style={{ border: '1px solid var(--border-default, #ddd)', color: 'var(--text-secondary, #555)' }}>
                View transcript
              </button>
            )}
          </div>
          ) : (
          /* HONEST empty state — never fabricate. Copy adapts to what actually happened:
             a transcript with no recap is NOT "no recording". */
          <div className="rounded-3xl p-6 text-center" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)' }}>
            <p className="text-sm font-semibold" style={{ color: 'var(--text-primary, #111)' }}>
              {hasTranscript ? 'No summary was generated.'
                : meeting.status === 'failed' ? 'Recording failed.'
                  : 'No recording for this meeting.'}
            </p>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary, #666)' }}>
              {hasTranscript ? 'The full transcript is available on the Transcript tab.'
                : meeting.status === 'failed' || meeting.recall_bot_id ? "We couldn't capture this meeting."
                  : 'Your persona didn’t attend — nothing was recorded.'}
            </p>
            <button type="button" onClick={() => selectTab(hasTranscript ? 'Transcript' : 'Notes')} className="mt-3 rounded-xl px-4 py-1.5 text-xs font-medium" style={{ border: '1px solid var(--border-default, #ddd)', color: 'var(--text-secondary, #555)' }}>
              {hasTranscript ? 'View transcript' : '+ Add your own notes'}
            </button>
          </div>
          )}
          {/* Ported panels — render whenever their data exists, INDEPENDENT of recap
              text: a recap can fail (e.g. Gemini 429) while analytics/responses
              succeed, and hiding them would falsely claim "nothing was captured".
              SpeakerAnalyticsSection self-suppresses when empty; Twin Activity is
              gated so the "did not participate" card only shows when the AI was
              actually sent (twin_attends) or did respond — no noise otherwise. */}
          <SpeakerAnalyticsSection analytics={meeting.analytics} />
          {(hasArr(meeting.twin_responses) || meeting.twin_attends) && (
            <TwinActivityReview responses={meeting.twin_responses ?? []} status={meeting.status} />
          )}
        </div>
      )}

      {activeTab === 'Notes' && (
        <NotesTabContent
          twinId={twinId}
          meetingId={meeting.id}
          initialGoal={meeting.user_goal ?? ''}
          initialContext={meeting.user_context ?? ''}
        />
      )}

      {activeTab === 'Transcript' && (
        meeting.transcript_text ? (
          <div className="rounded-3xl p-5 text-sm whitespace-pre-wrap" style={{ backgroundColor: 'var(--bg-card, #fff)', border: '1px solid var(--border-subtle, #eee)', color: 'var(--text-secondary, #444)' }}>
            {meeting.transcript_text}
          </div>
        ) : (
          <div className="rounded-3xl p-6 text-center text-sm" style={{ backgroundColor: 'var(--fog-2, #f7f7f8)', color: 'var(--text-secondary, #666)' }}>
            No transcript was captured for this meeting.
          </div>
        )
      )}

      {activeTab === 'Brief' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            {meeting.meet_link && (
              <a href={meeting.meet_link} target="_blank" rel="noreferrer" className="inline-block rounded-xl px-4 py-2 text-sm font-semibold text-white" style={{ backgroundColor: 'var(--brand-primary, #0066cc)' }}>
                Join meeting
              </a>
            )}
            {twinId && (
              <TwinAttendanceToggle
                twinId={twinId}
                meetingId={meeting.id}
                initialAttend={meeting.twin_attends ?? false}
                disabled={!meeting.meet_link}
                disabledReason="Add a meeting link to send your persona"
              />
            )}
          </div>
          <BriefTabContent twinId={twinId} meetingId={meeting.id} />
        </div>
      )}

      {activeTab === 'Live' && (
        <LiveTabContent
          twinId={twinId}
          meetingId={meeting.id}
          meetLink={meeting.meet_link}
          enabled={phase === 'live'}
          recallBotId={meeting.recall_bot_id}
        />
      )}

      {twinId && (
        <ShareRecapModal
          open={shareOpen}
          onClose={() => setShareOpen(false)}
          twinId={twinId}
          meetingId={meeting.id}
        />
      )}
    </div>
  );
}
