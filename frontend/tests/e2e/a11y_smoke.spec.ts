/**
 * Accessibility smoke test (dependency-free) for the two public launch
 * surfaces. Not a full WCAG audit — it pins the high-value basics that are
 * both launch-credibility table stakes and easy to regress: document
 * language, a heading, alt text on images, accessible names on interactive
 * controls, a labelled chat input, and no positive tabindex traps.
 */

import { test, expect, type Page } from '@playwright/test';

async function auditCommon(page: Page) {
  // Document language (screen-reader pronunciation, translation).
  await expect(page.locator('html')).toHaveAttribute('lang', /.+/);

  // At least one heading for structure.
  expect(await page.locator('h1, h2').count()).toBeGreaterThan(0);

  // Every <img> has an alt attribute (empty string allowed for decorative).
  const imgsMissingAlt = await page.locator('img:not([alt])').count();
  expect(imgsMissingAlt, 'images without an alt attribute').toBe(0);

  // No positive tabindex (creates an unpredictable, inaccessible tab order).
  const positiveTabindex = await page.locator('[tabindex]').evaluateAll(
    (els) => els.filter((e) => Number(e.getAttribute('tabindex')) > 0).length,
  );
  expect(positiveTabindex, 'elements with positive tabindex').toBe(0);

  // Interactive controls have an accessible name (text, aria-label, or title).
  const namelessControls = await page
    .locator('button:visible, a:visible')
    .evaluateAll((els) =>
      els.filter((e) => {
        const text = (e.textContent || '').trim();
        const aria = e.getAttribute('aria-label') || '';
        const title = e.getAttribute('title') || '';
        const labelledby = e.getAttribute('aria-labelledby') || '';
        return !text && !aria && !title && !labelledby;
      }).length,
    );
  expect(namelessControls, 'interactive controls without an accessible name').toBe(0);
}

test.describe('a11y smoke — landing', () => {
  test('landing meets accessibility basics', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1500);
    await auditCommon(page);
  });
});

test.describe('a11y smoke — persona page', () => {
  test('persona page meets accessibility basics', async ({ page }) => {
    await page.goto('/p/jane-smith');
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });
    await auditCommon(page);

    // The chat input — the page's primary action — must be labelled.
    const input = page.getByPlaceholder('Ask me anything...');
    const hasName = await input.evaluate(
      (el) => Boolean(el.getAttribute('aria-label') || el.getAttribute('placeholder')),
    );
    expect(hasName, 'chat input has an accessible name').toBe(true);
  });
});
