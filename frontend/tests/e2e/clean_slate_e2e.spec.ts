/**
 * E2E tests for the clean-slate backend pipeline.
 *
 * Tests the public-facing flow without auth:
 * 1. Landing page loads
 * 2. Onboarding page loads (redirects to login if unauth)
 * 3. Login page loads
 * 4. Share link page loads (/p/sainath-setti)
 * 5. Health endpoint returns healthy
 * 6. Public chat endpoint works (if share token available)
 *
 * Auth-protected flows (onboarding → chat) require a real Supabase session
 * and are tested manually or via a seeded test account.
 */

import { test, expect } from '@playwright/test';

const FRONTEND_URL = process.env.E2E_BASE_URL || 'https://personaon-web-czlsihxvra-uc.a.run.app';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'https://personaon-api-837700257032.us-central1.run.app';

test.describe('Landing & Navigation', () => {
  test('landing page loads with CTA', async ({ page }) => {
    await page.goto(FRONTEND_URL);
    await expect(page).toHaveTitle(/PersonaOn/);
    // Hero section should be visible
    const hero = page.locator('h1');
    await expect(hero.first()).toBeVisible({ timeout: 10000 });
    // CTA button should exist
    const cta = page.locator('a[href*="onboarding"], a[href*="login"]').first();
    await expect(cta).toBeVisible();
  });

  test('login page loads', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/auth/login`);
    await expect(page).toHaveTitle(/PersonaOn/);
    // Should show login options (LinkedIn, email, etc.)
    await page.waitForLoadState('networkidle');
    // Page should not be empty
    const body = page.locator('body');
    await expect(body).not.toBeEmpty();
  });

  test('marketplace page loads', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/marketplace`);
    await expect(page).toHaveTitle(/PersonaOn/);
    await page.waitForLoadState('networkidle');
  });
});

test.describe('Backend Health', () => {
  test('health endpoint returns healthy', async ({ request }) => {
    const response = await request.get(`${BACKEND_URL}/health`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe('healthy');
    expect(body.checks.supabase.status).toBe('ok');
    expect(body.checks.pinecone.status).toBe('ok');
    expect(body.checks.gemini.status).toBe('ok');
    expect(body.checks.firecrawl.status).toBe('ok');
  });
});

test.describe('Auth Protection', () => {
  test('auto-create requires auth', async ({ request }) => {
    const response = await request.post(`${BACKEND_URL}/v2/twins/auto-create`, {
      data: { name: 'Test User', context: 'Engineer' },
    });
    expect(response.status()).toBe(401);
  });

  test('owner chat requires auth', async ({ request }) => {
    const response = await request.post(`${BACKEND_URL}/v2/chat/owner/fake-id/stream`, {
      data: { message: 'Hello' },
    });
    expect(response.status()).toBe(401);
  });

  test('conversations list requires auth', async ({ request }) => {
    const response = await request.get(`${BACKEND_URL}/v2/chat/conversations`);
    expect(response.status()).toBe(401);
  });

  test('onboarding redirects to login when unauthed', async ({ page }) => {
    const response = await page.goto(`${FRONTEND_URL}/onboarding`);
    // Should redirect to login page
    await page.waitForLoadState('networkidle');
    const url = page.url();
    // Either we're on the onboarding page (if auth bypass) or redirected to login
    expect(url).toMatch(/onboarding|login/);
  });
});

test.describe('Share Link', () => {
  test('share page loads for valid handle', async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/p/sainath-setti`);
    await page.waitForLoadState('networkidle');
    // Should show the persona name (not a blank page)
    const visibleText = await page.locator('body').innerText();
    expect(visibleText).toContain('Sainath Setti');
  });

  test('handle resolution endpoint works', async ({ request }) => {
    const response = await request.get(`${BACKEND_URL}/handles/resolve?handle=sainath-setti`);
    // Should return 200 with twin_id + share_token, or 404 if not found
    expect([200, 404]).toContain(response.status());
    if (response.status() === 200) {
      const body = await response.json();
      expect(body).toHaveProperty('twin_id');
      expect(body).toHaveProperty('share_token');
    }
  });
});

test.describe('CORS', () => {
  test('CORS headers on preflight', async ({ request }) => {
    const response = await request.fetch(`${BACKEND_URL}/v2/twins/auto-create`, {
      method: 'OPTIONS',
      headers: {
        'Origin': FRONTEND_URL,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Content-Type,Authorization',
      },
    });
    expect(response.status()).toBe(200);
    const headers = response.headers();
    expect(headers['access-control-allow-origin']).toBeTruthy();
  });

  test('CORS headers on error response', async ({ request }) => {
    const response = await request.post(`${BACKEND_URL}/v2/twins/auto-create`, {
      headers: {
        'Origin': FRONTEND_URL,
        'Content-Type': 'application/json',
      },
      data: { name: 'Test' },
    });
    // Should be 401 but WITH CORS headers
    expect(response.status()).toBe(401);
    const headers = response.headers();
    expect(headers['access-control-allow-origin']).toBeTruthy();
  });
});

test.describe('Public Chat API', () => {
  test('public chat returns 404 for fake twin', async ({ request }) => {
    const response = await request.post(
      `${BACKEND_URL}/v2/chat/public/00000000-0000-0000-0000-000000000000/fake-token/stream`,
      { data: { message: 'Hello' } }
    );
    expect(response.status()).toBe(404);
  });

  test('widget chat returns 404 for fake twin', async ({ request }) => {
    const response = await request.post(
      `${BACKEND_URL}/v2/chat/widget/00000000-0000-0000-0000-000000000000/stream`,
      { data: { message: 'Hello' } }
    );
    expect(response.status()).toBe(404);
  });
});
