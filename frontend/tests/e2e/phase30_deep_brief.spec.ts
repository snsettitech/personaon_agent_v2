/**
 * W9d E2E — DeepResearchButton states + polling.
 *
 * Covers:
 *   D01: Button renders when v2 brief has no deep_generated_at
 *   D02: Button HIDES (rendered as badge) when brief has deep_generated_at
 *   D03: Button HIDES entirely when POST returns 503 (flag off)
 *   D04: 'cached' response from POST flips UI without polling
 *   D05: 'queued' response triggers polling; brief updates when
 *        deep_generated_at appears
 *
 * Mocks the brief endpoint + the deep trigger endpoint so the test
 * doesn't depend on the live backend or real Gemini.
 */

import { test, expect, type Page, type Route } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const E2E_TWIN_ID = 'e2e-twin';
const MTG_ID = 'mtg-e2e-deep';

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
  deepGeneratedAt?: string | null;
  participantBackground?: string;
}

function buildBrief(opts: MockBriefOpts = {}) {
  const brief: Record<string, unknown> = {
    schema_version: 2,
    meeting_id: MTG_ID,
    meeting_title: 'Q2 Strategy Sync',
    meeting_start: new Date(Date.now() + 30 * 60_000).toISOString(),
    person: { name: 'Sarah Chen' },
    your_goal: 'Close on the strategy doc',
    your_context: null,
    prior_meetings: [],
    hooks: [],
    open_commitments: [],
    generated_at: new Date().toISOString(),
    participant_insights: [
      {
        name: 'Sarah Chen',
        email: 's@x.com',
        role: 'CRO',
        background: opts.participantBackground ?? null,
        recent_activities: [],
        web_sources: [],
        pdl_snapshot: null,
      },
    ],
    talking_points: [],
    previous_interactions: [],
    suggested_agenda: [],
    caution_notes: [],
    sources_used: { kb_chunks: 0, web_results: 0, past_meetings: 0 },
  };
  if (opts.deepGeneratedAt) {
    brief.deep_generated_at = opts.deepGeneratedAt;
  }
  return brief;
}

const briefUrl = `${BASE_URL}/dashboard/meetings/${MTG_ID}/brief`;
const briefApiPattern = new RegExp(
  `/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/brief(?:\\?.*)?$`,
);
const deepBriefApiPattern = new RegExp(
  `/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/brief/deep$`,
);

test.describe('Phase 30 (W9d) DeepResearchButton', () => {
  // -------------------------------------------------------------------------
  // D01 + D02: button vs badge based on deep_generated_at
  // -------------------------------------------------------------------------

  test('button renders when brief has no deep_generated_at', async ({ page }) => {
    await setupCoreMocks(page);
    await page.route(briefApiPattern, async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, { status: 'ok', data: buildBrief() });
    });
    await page.goto(briefUrl);
    await expect(page.getByRole('button', { name: /run deep research/i })).toBeVisible({
      timeout: 15_000,
    });
  });

  test('button HIDES (badge shown instead) when brief has deep_generated_at', async ({ page }) => {
    await setupCoreMocks(page);
    await page.route(briefApiPattern, async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, {
        status: 'ok',
        data: buildBrief({
          deepGeneratedAt: new Date(Date.now() - 12 * 3600_000).toISOString(),
        }),
      });
    });
    await page.goto(briefUrl);
    await expect(page.getByText('You ×').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Sarah Chen').first()).toBeVisible();
    // Badge present
    await expect(page.getByText(/Deep research /i).first()).toBeVisible();
    // Button absent
    await expect(page.getByRole('button', { name: /run deep research/i })).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // D03: 503 from POST hides the button (flag off)
  // -------------------------------------------------------------------------

  test('button hides itself when POST returns 503', async ({ page }) => {
    await setupCoreMocks(page);
    await page.route(deepBriefApiPattern, async (route) => {
      const method = route.request().method();
      if (method === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, { detail: 'Deep brief mode is not enabled' }, 503);
    });
    await page.route(briefApiPattern, async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, { status: 'ok', data: buildBrief() });
    });
    await page.goto(briefUrl);
    const button = page.getByRole('button', { name: /run deep research/i });
    await expect(button).toBeVisible({ timeout: 15_000 });
    await button.click();
    // After 503, the component sets state to 'unavailable' and returns null
    await expect(button).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // D04: 'cached' POST response flips UI without polling
  // -------------------------------------------------------------------------

  test("'cached' POST response shows deep badge immediately", async ({ page }) => {
    await setupCoreMocks(page);
    const deepBrief = buildBrief({
      deepGeneratedAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
      participantBackground: 'CRO at Beta; deep-research enriched',
    });
    await page.route(deepBriefApiPattern, async (route) => {
      const method = route.request().method();
      if (method === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, { status: 'cached', data: deepBrief });
    });
    await page.route(briefApiPattern, async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      // First GET — no deep_generated_at
      await mockJson(route, { status: 'ok', data: buildBrief() });
    });
    await page.goto(briefUrl);
    const button = page.getByRole('button', { name: /run deep research/i });
    await expect(button).toBeVisible({ timeout: 15_000 });
    await button.click();
    // After 'cached' response, badge appears and button disappears
    await expect(page.getByText(/Deep research /i).first()).toBeVisible();
    await expect(button).toHaveCount(0);
    // The enriched participant background is rendered
    await expect(page.getByText(/deep-research enriched/i)).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // D05: 'queued' triggers polling; brief updates when ready
  // -------------------------------------------------------------------------

  test("'queued' triggers polling; UI updates when deep_generated_at appears", async ({ page }) => {
    await setupCoreMocks(page);
    let getCount = 0;
    const deepBrief = buildBrief({
      deepGeneratedAt: new Date(Date.now()).toISOString(),
      participantBackground: 'Updated by polling',
    });

    await page.route(deepBriefApiPattern, async (route) => {
      const method = route.request().method();
      if (method === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      await mockJson(route, { status: 'queued', job_id: 'job_e2e' });
    });
    await page.route(briefApiPattern, async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({ status: 204, headers: CORS, body: '' });
        return;
      }
      // GET — first call is the page load; subsequent calls are poll
      getCount += 1;
      if (getCount === 1) {
        await mockJson(route, { status: 'ok', data: buildBrief() });
      } else {
        // Polling sees the deep brief
        await mockJson(route, { status: 'ok', data: deepBrief });
      }
    });
    await page.goto(briefUrl);
    const button = page.getByRole('button', { name: /run deep research/i });
    await expect(button).toBeVisible({ timeout: 15_000 });
    await button.click();
    // While running, spinner-style label appears
    await expect(page.getByText(/Researching/i)).toBeVisible({ timeout: 5_000 });
    // After polling completes, badge replaces button
    await expect(page.getByText(/Deep research /i).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Updated by polling/i)).toBeVisible();
  });
});
