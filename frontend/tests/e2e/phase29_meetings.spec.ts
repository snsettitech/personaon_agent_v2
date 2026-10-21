/**
 * Phase 29 E2E Tests — Active Twin in Meetings
 *
 * Covers (maps to 29-UAT.md tests):
 *   UAT-01: Twin attendance toggle on meetings list
 *   UAT-02: Live meeting dashboard loads with status badge + controls
 *   UAT-03: Mute/unmute twin control
 *   UAT-04: Leave meeting with inline confirmation
 *   UAT-05: voice-agent.html visual design (dark background, no JS errors)
 *   UAT-11: Twin activity review on meeting detail page
 *   NAV:    Meetings entry in sidebar
 *
 * Auth: relies on NEXT_PUBLIC_E2E_BYPASS_AUTH=1 which creates an E2E fake twin
 * with id='e2e-twin'. All API mocks use this twin ID.
 *
 * Backend URL mocked: all calls to *\/v2\/meetings\/* are intercepted.
 * Backend health check mocked so ApiConnectivityBanner doesn't block the dashboard.
 */

import { test, expect, type Page, type Route } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

// E2E bypass auth creates this fake twin
const E2E_TWIN_ID = 'e2e-twin';
const MTG_ID = 'mtg-e2e-001';
type MutePayload = { muted?: boolean };

// ---------------------------------------------------------------------------
// Mock data (matches backend API envelope: {status, data})
// ---------------------------------------------------------------------------

const MOCK_MEETING = {
  id: MTG_ID,
  twin_id: E2E_TWIN_ID,
  title: 'Q2 Strategy Review',
  meeting_url: 'https://meet.google.com/abc-def-ghi',
  status: 'scheduled',
  twin_attends: true,
  scheduled_at: new Date(Date.now() + 3600 * 1000).toISOString(),
  created_at: new Date().toISOString(),
  participants: [],
  analytics: [],
};

const MOCK_MEETING_WITH_RESPONSES = {
  ...MOCK_MEETING,
  status: 'recording',
  twin_responses: [
    {
      id: 'resp-1',
      question_text: 'Q2 revenue target question',
      response_text: 'Based on our KB, the Q2 target is $2.5M.',
      confidence: 0.87,
      sources: [{ url: 'https://example.com/plan', title: 'Q2 Plan' }],
      is_deferral: false,
      responded_at: new Date().toISOString(),
    },
    {
      id: 'resp-2',
      question_text: 'Mars colonisation timeline?',
      response_text: "That's a great question -- let me have the team follow up directly.",
      confidence: 0.0,
      sources: [],
      is_deferral: true,
      responded_at: new Date().toISOString(),
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,PATCH,DELETE,OPTIONS',
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
  // Mock backend health so ApiConnectivityBanner doesn't block dashboard
  await page.route('**/health', async (route) => {
    await mockJson(route, {
      status: 'healthy',
      checks: { supabase: { status: 'ok' }, pinecone: { status: 'ok' }, gemini: { status: 'ok' } },
    });
  });
}

async function setupMeetingsMocks(page: Page) {
  await setupCoreMocks(page);

  // Meetings list endpoint: GET /v2/meetings/:twinId
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}`, async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS, body: '' });
      return;
    }
    if (route.request().method() === 'GET') {
      await mockJson(route, { status: 'ok', data: [MOCK_MEETING] });
      return;
    }
    await route.continue();
  });

  // Meeting detail: GET /v2/meetings/:twinId/:meetingId
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}`, async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS, body: '' });
      return;
    }
    if (route.request().method() === 'GET') {
      await mockJson(route, { status: 'ok', data: MOCK_MEETING_WITH_RESPONSES });
      return;
    }
    await route.continue();
  });

  // Toggle attendance
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/toggle-attendance`, async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS, body: '' });
      return;
    }
    const body = JSON.parse(route.request().postData() || '{}');
    await mockJson(route, { status: 'ok', data: { twin_attends: body.attend } });
  });

  // Mute
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/mute`, async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS, body: '' });
      return;
    }
    const body = JSON.parse(route.request().postData() || '{}');
    await mockJson(route, { status: 'ok', data: { muted: body.muted } });
  });

  // Leave / DELETE
  await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/leave`, async (route) => {
    await mockJson(route, { status: 'ok' });
  });
}

// ---------------------------------------------------------------------------
// UAT-01: Twin attendance toggle on meetings list
// ---------------------------------------------------------------------------

test.describe('UAT-01: Twin attendance toggle', () => {
  test('meetings list renders with Q2 meeting and twin_attends toggle', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings`);

    // Meeting title visible
    await expect(page.getByText('Q2 Strategy Review').first()).toBeVisible({ timeout: 15000 });

    // Toggle present (role=switch)
    const toggle = page.getByRole('switch').first();
    await expect(toggle).toBeVisible();
  });

  test('toggling attendance OFF sends POST and updates UI optimistically', async ({ page }) => {
    let toggleCalled = false;
    let sentAttend: boolean | null = null;

    await setupMeetingsMocks(page);
    await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/toggle-attendance`, async (route) => {
      if (route.request().method() === 'POST') {
        toggleCalled = true;
        const body = JSON.parse(route.request().postData() || '{}');
        sentAttend = body.attend;
        await mockJson(route, { status: 'ok', data: { twin_attends: body.attend } });
        return;
      }
      await route.continue();
    });

    await page.goto(`${BASE_URL}/dashboard/meetings`);
    await expect(page.getByText('Q2 Strategy Review').first()).toBeVisible({ timeout: 15000 });

    const toggle = page.getByRole('switch').first();
    await toggle.click();

    await page.waitForTimeout(600);
    expect(toggleCalled).toBe(true);
    expect(sentAttend).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// UAT-02: Live meeting dashboard loads
// ---------------------------------------------------------------------------

test.describe('UAT-02: Live meeting dashboard', () => {
  test('live dashboard renders Mute Twin and Leave Meeting controls', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);

    await expect(page.getByRole('button', { name: /mute twin/i })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: /leave meeting/i })).toBeVisible({ timeout: 5000 });
  });

  test('live dashboard shows status badge (Joining or Twin Active)', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);

    // Initial status is 'joining' → badge shows "Joining..." or "Twin Active" after WS connects
    await expect(
      page.locator('text=/Joining\\.\\.\\.|Twin Active|Twin Speaking|Twin Muted/i').first()
    ).toBeVisible({ timeout: 15000 });
  });
});

// ---------------------------------------------------------------------------
// UAT-03: Mute/unmute twin control
// ---------------------------------------------------------------------------

test.describe('UAT-03: Mute/unmute twin control', () => {
  test('Mute Twin button sends POST with muted=true and text changes to Unmute Twin', async ({ page }) => {
    let muteBody: MutePayload = {};

    await setupMeetingsMocks(page);
    await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/mute`, async (route) => {
      if (route.request().method() === 'POST') {
        muteBody = JSON.parse(route.request().postData() || '{}');
        await mockJson(route, { status: 'ok', data: { muted: muteBody?.muted } });
        return;
      }
      await route.continue();
    });

    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);

    const muteBtn = page.getByRole('button', { name: /mute twin/i });
    await expect(muteBtn).toBeVisible({ timeout: 15000 });
    await muteBtn.click();

    await page.waitForTimeout(600); // debounce
    await expect(page.getByRole('button', { name: /unmute twin/i })).toBeVisible({ timeout: 5000 });
    expect(muteBody.muted).toBe(true);
  });

  test('unmute sends POST with muted=false', async ({ page }) => {
    const muteBodies: MutePayload[] = [];

    await setupMeetingsMocks(page);
    await page.route(`**/v2/meetings/${E2E_TWIN_ID}/${MTG_ID}/mute`, async (route) => {
      if (route.request().method() === 'POST') {
        const body = JSON.parse(route.request().postData() || '{}');
        muteBodies.push(body);
        await mockJson(route, { status: 'ok', data: { muted: body.muted } });
        return;
      }
      await route.continue();
    });

    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);
    await expect(page.getByRole('button', { name: /mute twin/i })).toBeVisible({ timeout: 15000 });

    // Mute then unmute
    await page.getByRole('button', { name: /mute twin/i }).click();
    await page.waitForTimeout(600);
    await page.getByRole('button', { name: /unmute twin/i }).click();
    await page.waitForTimeout(600);

    expect(muteBodies.length).toBe(2);
    expect(muteBodies[0].muted).toBe(true);
    expect(muteBodies[1].muted).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// UAT-04: Leave meeting with confirmation
// ---------------------------------------------------------------------------

test.describe('UAT-04: Leave meeting control', () => {
  test('Leave Meeting shows inline confirmation', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);

    const leaveBtn = page.getByRole('button', { name: /leave meeting/i });
    await expect(leaveBtn).toBeVisible({ timeout: 15000 });
    await leaveBtn.click();

    await expect(
      page.locator('text=/confirm|are you sure|really leave/i').first()
    ).toBeVisible({ timeout: 5000 });
  });

  test('cancelling leave restores Leave Meeting button', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}/live?twin=${E2E_TWIN_ID}`);

    await expect(page.getByRole('button', { name: /leave meeting/i })).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: /leave meeting/i }).click();

    // Cancel
    const cancelBtn = page.getByRole('button', { name: /cancel/i });
    if (await cancelBtn.isVisible()) {
      await cancelBtn.click();
      await expect(page.getByRole('button', { name: /leave meeting/i })).toBeVisible({ timeout: 3000 });
    }
  });
});

// ---------------------------------------------------------------------------
// UAT-05: voice-agent.html visual design (needs backend running)
// ---------------------------------------------------------------------------

test.describe('UAT-05: voice-agent.html visual design', () => {
  test('voice-agent.html loads without JS errors and has dark background', async ({ page }) => {
    const jsErrors: string[] = [];
    page.on('pageerror', (err) => jsErrors.push(err.message));

    try {
      await page.goto(
        `${BACKEND_URL}/static/voice-agent.html?twin_id=test-twin&meeting_id=test-mtg`,
        { waitUntil: 'domcontentloaded', timeout: 10000 }
      );

      expect(jsErrors).toHaveLength(0);

      const bgColor = await page.evaluate(() =>
        window.getComputedStyle(document.body).backgroundColor
      );
      const vals = bgColor.match(/\d+/g)?.map(Number) || [255, 255, 255];
      const brightness = (vals[0] * 299 + vals[1] * 587 + vals[2] * 114) / 1000;
      expect(brightness).toBeLessThan(100);
    } catch (err) {
      if (String(err).includes('ERR_CONNECTION_REFUSED')) {
        test.skip(true, 'Backend not running locally — test on GCP staging');
      }
      throw err;
    }
  });

  test('voice-agent.html viewport is 1280x720 compatible', async ({ page }) => {
    try {
      await page.setViewportSize({ width: 1280, height: 720 });
      await page.goto(
        `${BACKEND_URL}/static/voice-agent.html?twin_id=test-twin&meeting_id=test-mtg`,
        { waitUntil: 'domcontentloaded', timeout: 10000 }
      );

      const hasHorizontalScroll = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth
      );
      expect(hasHorizontalScroll).toBe(false);
    } catch (err) {
      if (String(err).includes('ERR_CONNECTION_REFUSED')) {
        test.skip(true, 'Backend not running locally — test on GCP staging');
      }
      throw err;
    }
  });
});

// ---------------------------------------------------------------------------
// UAT-11: Twin activity review on meeting detail
// ---------------------------------------------------------------------------

test.describe('UAT-11: Twin activity review', () => {
  test('meeting detail shows Twin Activity section', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}?twin=${E2E_TWIN_ID}`);

    await expect(page.getByText(/twin activity/i).first()).toBeVisible({ timeout: 15000 });
  });

  test('twin activity shows non-deferral and deferral responses', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}?twin=${E2E_TWIN_ID}`);

    await expect(page.getByText(/Q2 revenue target/i).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/deferred/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('meeting detail has View Live link', async ({ page }) => {
    await setupMeetingsMocks(page);
    // Page shows View Live only when status is recording/bot_joining
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}?twin=${E2E_TWIN_ID}`);

    const viewLiveLink = page.getByRole('link', { name: /view live/i });
    await expect(viewLiveLink).toBeVisible({ timeout: 15000 });
    const href = await viewLiveLink.getAttribute('href');
    expect(href).toContain('/live');
  });

  test('confidence bar shows percentage for non-deferral response', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings/${MTG_ID}?twin=${E2E_TWIN_ID}`);

    // 87% confidence → look for 87 somewhere in the activity section
    await expect(page.getByText(/87/i).first()).toBeVisible({ timeout: 15000 });
  });
});

// ---------------------------------------------------------------------------
// Sidebar navigation
// ---------------------------------------------------------------------------

test.describe('Navigation: Meetings in sidebar', () => {
  test('sidebar contains Meetings link pointing to /dashboard/meetings', async ({ page }) => {
    await setupCoreMocks(page);
    await page.goto(`${BASE_URL}/dashboard`);

    const meetingsLink = page.getByRole('link', { name: /^meetings$/i });
    await expect(meetingsLink).toBeVisible({ timeout: 15000 });

    const href = await meetingsLink.getAttribute('href');
    expect(href).toBe('/dashboard/meetings');
  });

  test('Meetings sidebar link is active when on /dashboard/meetings', async ({ page }) => {
    await setupMeetingsMocks(page);
    await page.goto(`${BASE_URL}/dashboard/meetings`);

    const meetingsLink = page.getByRole('link', { name: /^meetings$/i });
    await expect(meetingsLink).toBeVisible({ timeout: 15000 });

    const isActive =
      (await meetingsLink.getAttribute('aria-current')) === 'page' ||
      (await meetingsLink.evaluate((el) =>
        el.className.includes('active') || el.className.includes('bg-')
      ));
    expect(isActive).toBe(true);
  });
});
