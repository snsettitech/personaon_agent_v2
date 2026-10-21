/**
 * Hostile-content & thin-profile edge cases — the "embarrassment layer".
 *
 * Fixtures live in tests/e2e/mock-api.mjs:
 *   /p/edge-hostile — XSS payloads in every field, javascript: links,
 *                     RTL + emoji names, 300+ char unbroken tokens, 12 jobs.
 *   /p/edge-empty   — a profile with nothing but a name.
 *
 * The page must render hostile content inert (no script execution, no
 * javascript: hrefs) and unbroken (no horizontal overflow), and must not
 * print "undefined"/"null" for missing data.
 */

import { test, expect } from '@playwright/test';

test.describe('hostile persona content', () => {
  test.setTimeout(60000);

  test('XSS payloads render inert — no dialogs, no javascript: links', async ({ page }) => {
    const dialogs: string[] = [];
    page.on('dialog', (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });

    await page.goto('/p/edge-hostile');
    await expect(page.getByText('Ünïcôdé').first()).toBeVisible({ timeout: 10000 });
    // Give any injected onload/onerror handlers a chance to fire
    await page.waitForTimeout(1500);

    // The definitive security signal: no injected handler executed. The
    // fixture's payloads all use executable hooks (script alert(1),
    // img onerror=alert(2), svg onload=alert(4)); if React had failed to
    // escape any field into text, at least one dialog would have fired.
    // (The string "alert(1)" still appears inside Next's inert RSC data
    // payload — that's serialized data, not a live element, so counting
    // raw <script> text would false-positive. A fired dialog is the only
    // thing that proves an actual XSS.)
    expect(dialogs, 'no script payload may execute').toHaveLength(0);

    // No live injected element survived in the rendered body (proof React
    // escaped the markup to text rather than parsing it as HTML).
    expect(await page.locator('body img[onerror]').count()).toBe(0);
    expect(await page.locator('body svg[onload]').count()).toBe(0);

    // No anchor may carry a javascript: href (hero prefixes non-http URLs).
    const jsHrefs = await page.locator('a').evaluateAll(
      (as) => as.map((a) => a.getAttribute('href') || '').filter((h) => h.toLowerCase().startsWith('javascript:')),
    );
    expect(jsHrefs).toHaveLength(0);

    // No injected iframe from the bio.
    expect(await page.locator('iframe[src*="evil.example"]').count()).toBe(0);
  });

  test('long unbroken tokens do not break the layout (mobile)', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/p/edge-hostile');
    await expect(page.getByText('Ünïcôdé').first()).toBeVisible({ timeout: 10000 });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, 'horizontal overflow in px').toBeLessThanOrEqual(2);
  });

  test('hostile og card still renders a PNG', async ({ page }) => {
    const res = await page.request.get('/p/edge-hostile/opengraph-image');
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('image/png');
  });
});

test.describe('thin persona profile', () => {
  test('name-only profile renders without crashes or undefined text', async ({ page }) => {
    await page.goto('/p/edge-empty');
    await expect(page.getByText('Min Imal').first()).toBeVisible({ timeout: 10000 });

    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).not.toContain('undefined');
    expect(body).not.toMatch(/(^|\s)null(\s|$)/);

    // Chat is still usable — the page's core function survives an empty profile.
    await expect(page.getByPlaceholder('Ask me anything...')).toBeVisible();
  });

  test('thin og card still renders a PNG', async ({ page }) => {
    const res = await page.request.get('/p/edge-empty/opengraph-image');
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('image/png');
  });
});
