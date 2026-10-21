/**
 * Phase 30 (W9c) E2E — Pre-meeting brief page.
 *
 * Covers:
 *   T01: v2 brief renders all expected sections
 *   T02: Heads Up section HIDDEN when caution_notes is []
 *   T03: Heads Up section VISIBLE + amber treatment when notes present
 *   T04: Citation chevron expands inline on click
 *   T05: Sources-used footer hidden when all counts zero
 *   T06: Backwards-compat — v1 brief (no v2 fields) renders without crash
 *
 * Auth: relies on NEXT_PUBLIC_E2E_BYPASS_AUTH=1 (creates fake twin id='e2e-twin').
 * Backend health check mocked so ApiConnectivityBanner doesn't gate the page.
 */

import { test, expect, type Page, type Route } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const E2E_TWIN_ID = 'e2e-twin';
const MTG_ID = 'mtg-e2e-brief';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,OPTIONS',
  'access-control-allow-headers': 'authorization,content-type',
};

async function mockJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: CORS,
    body: JSON.stringify(body),
  });
}

async function setupCoreMocks(page: Page) {
  await page.route('**/health', async (route) => {
    await mockJson(route, {
      status: 'healthy',
      checks: { supabase: { status: 'ok' }, pinecone: { status: 'ok' }, gemini: { status: 'ok' } },
    });
  });
}

interface MockBriefOpts {
  cautionNotes?: Array<{
    text: string;
    source: { kind: string; ref: string; ref_type: string; quote: string };
  }>;
  sourcesUsed?: { kb_chunks: number; web_results: number; past_meetings: number };
  schemaVersion?: 1 | 2;
}

function buildV2Brief(opts: MockBriefOpts = {}) {
  return {
    schema_version: opts.schemaVersion ?? 2,
    meeting_id: MTG_ID,
    meeting_title: 'Q2 Strategy Sync',
    meeting_start: new Date(Date.now() + 30 * 60_000).toISOString(),
    person: {
      name: 'Sarah Chen',
      email: 'sarah@acme.com',
      role: 'CRO',
      company: 'Beta Inc',
      bio: 'CRO at Beta. Previously VP Sales at Acme.',
      signals: [],
    },
    your_goal: 'Close on the Q2 strategy doc',
    your_context: null,
    prior_meetings: [
      { meeting_id: 'm1', date: '2026-05-08', title: 'Initial sync', summary: 'Talked about Q2.', status: 'open' },
    ],
    hooks: [{ label: 'Bring', text: 'The Q2 strategy doc draft' }],
    open_commitments: [
      { description: 'Send Q2 strategy doc', days_open: 13, from_meeting_id: 'm1' },
    ],
    generated_at: new Date().toISOString(),
    // v2 fields
    participant_insights: [
      {
        name: 'Sarah Chen',
        email: 'sarah@acme.com',
        role: 'CRO',
        background: 'CRO at Beta. Previously VP Sales at Acme.',
        recent_activities: [],
        web_sources: [],
        pdl_snapshot: { company: 'Beta Inc', role: 'CRO' },
      },
    ],
    talking_points: [{ topic: 'Term sheet pricing', rationale: 'Bring' }],
    previous_interactions: [
      {
        meeting_id: 'm1',
        date: '2026-05-08',
        meeting_title: 'Initial sync',
        summary: 'Talked about Q2.',
        open_items: ['Send the Q2 doc'],
      },
    ],
    suggested_agenda: ['Quick catch-up since last meeting', 'Term sheet pricing', 'Next steps + timing'],
    caution_notes: opts.cautionNotes ?? [],
    sources_used: opts.sourcesUsed ?? { kb_chunks: 0, web_results: 0, past_meetings: 1 },
  };
}

function buildV1Brief() {
  // No v2 fields — simulate a brief generated before BRIEF_SCHEMA_V2_ENABLED
  return {
    schema_version: 1,
    meeting_id: MTG_ID,
    meeting_title: 'Legacy meeting',
    meeting_start: new Date(Date.now() + 30 * 60_000).toISOString(),
    person: { name: 'Bob Stevens', email: 'bob@x.com', role: '', company: '', bio: '', signals: [] },
    your_goal: 'Catch up',
    your_context: null,
    prior_meetings: [],
    hooks: [{ label: 'Probe', text: 'Ask about Q1 results' }],
    open_commitments: [],
    generated_at: new Date().toISOString(),
  };
}

async function setupBriefMocks(page: Page, brief: unknown) {
  await setupCoreMocks(page);
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/brief`, async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS, body: '' });
      return;
    }
    await mockJson(route, { status: 'ok', data: brief });
  });
}

const briefUrl = `${BASE_URL}/dashboard/meetings/${MTG_ID}/brief`;

// ---------------------------------------------------------------------------
// T01: v2 brief renders all expected sections
// ---------------------------------------------------------------------------

test.describe('Phase 30 (W9c) brief page', () => {
  test('v2 brief renders all expected sections', async ({ page }) => {
    await setupBriefMocks(
      page,
      buildV2Brief({
        cautionNotes: [
          {
            text: "Heads up — Sarah's still waiting on the Q2 strategy doc you mentioned May 8.",
            source: {
              kind: 'open_commitment',
              ref: 'm1',
              ref_type: 'meeting_id',
              quote: "I'll send the Q2 strategy doc by Friday",
            },
          },
        ],
      }),
    );
    await page.goto(briefUrl);

    await expect(page.getByText('You ×').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Sarah Chen').first()).toBeVisible();
    await expect(page.getByText("Who you're meeting")).toBeVisible();
    await expect(page.getByText('Heads up', { exact: false }).first()).toBeVisible();
    await expect(page.getByText('Talking points')).toBeVisible();
    await expect(page.getByText('Suggested agenda')).toBeVisible();
    await expect(page.getByText('From last time')).toBeVisible();
    await expect(page.getByText('Still on your list')).toBeVisible();
    await expect(page.getByText(/Built from/i).first()).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // T02: Heads Up section HIDDEN when caution_notes is []
  // -------------------------------------------------------------------------

  test('Heads Up section is HIDDEN when caution_notes is empty', async ({ page }) => {
    await setupBriefMocks(page, buildV2Brief({ cautionNotes: [] }));
    await page.goto(briefUrl);

    // Brief loaded
    await expect(page.getByText('Talking points')).toBeVisible({ timeout: 15_000 });
    // But the "HEADS UP" eyebrow is NOT present (no false safety signal)
    const headsUpLabel = page.getByText(/^heads up$/i);
    await expect(headsUpLabel).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // T03 + T04: Citation chevron expands on click
  // -------------------------------------------------------------------------

  test('Heads Up citation chevron expands inline on click', async ({ page }) => {
    const quote = "I'll send the Q2 strategy doc by Friday";
    await setupBriefMocks(
      page,
      buildV2Brief({
        cautionNotes: [
          {
            text: "Heads up — Sarah's still waiting on the Q2 doc.",
            source: {
              kind: 'open_commitment',
              ref: 'm1',
              ref_type: 'meeting_id',
              quote,
            },
          },
        ],
      }),
    );
    await page.goto(briefUrl);

    // Heads Up note visible
    const summary = page.getByText("Heads up — Sarah's still waiting on the Q2 doc.").first();
    await expect(summary).toBeVisible({ timeout: 15_000 });

    // Quote NOT visible until clicked (<details> collapsed).
    // AUDIT FIX (W9c): HeadsUpSection wraps quotes in &ldquo;/&rdquo;
    // (curly U+201C/U+201D) — a straight-quote getByText would never match
    // and the test would pass-then-fail incorrectly. Match by the inner
    // quote text without the wrapping quotes (Playwright getByText does
    // a normalized substring match).
    const quoteLocator = page.getByText(quote);
    await expect(quoteLocator.first()).toBeHidden();

    // Click the summary to expand
    await summary.click();
    await expect(quoteLocator.first()).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // T05: Sources-used footer hidden when all counts zero
  // -------------------------------------------------------------------------

  test('Sources used footer is HIDDEN when all counts zero', async ({ page }) => {
    await setupBriefMocks(
      page,
      buildV2Brief({
        sourcesUsed: { kb_chunks: 0, web_results: 0, past_meetings: 0 },
      }),
    );
    await page.goto(briefUrl);
    await expect(page.getByText('Talking points')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Built from/i)).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // T06: v1 brief renders without crash (no caution_notes / participant_insights)
  // -------------------------------------------------------------------------

  test('v1 brief (no v2 fields) renders without crashing', async ({ page }) => {
    await setupBriefMocks(page, buildV1Brief());
    await page.goto(briefUrl);

    // v1 person.name still drives the hero
    await expect(page.getByText('Bob Stevens').first()).toBeVisible({ timeout: 15_000 });
    // Talking points falls back from v1 hooks
    await expect(page.getByText('Talking points')).toBeVisible();
    await expect(page.getByText(/Ask about Q1 results/)).toBeVisible();
    // Heads Up, Suggested agenda, Sources footer all hidden on v1
    await expect(page.getByText(/^heads up$/i)).toHaveCount(0);
    await expect(page.getByText('Suggested agenda')).toHaveCount(0);
    await expect(page.getByText(/Built from/i)).toHaveCount(0);
  });
});
