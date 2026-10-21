import { test, expect, type Page } from '@playwright/test';

// E2E: Publish-tab ("Share" page) Layout-card save UX.
//
// Guards the regression where the "Save & Publish" button rendered
// white-on-white — a global glass `button` rule in globals.css overrode the
// Tailwind background, so the button was invisible exactly when enabled.
// `toBeVisible()` does NOT catch that (a white-on-white button is still "visible"
// in the layout), so we assert the COMPUTED background is actually dark.
//
// Auth is bypassed via playwright.config.ts (E2E_BYPASS_AUTH=1 + the TwinContext
// fake-twin path). ThemePicker fetches /profile client-side — stubbed here.

async function saveButtonBg(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const b = Array.from(document.querySelectorAll('button')).find(
      (x) => (x.textContent || '').trim() === 'Save & Publish',
    );
    return b ? getComputedStyle(b).backgroundColor : null;
  });
}

// luminance < 0.4 → a genuinely dark button (rules out the translucent-white glass bg)
function isDark(rgb: string | null): boolean {
  if (!rgb) return false;
  const m = rgb.match(/(\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return false;
  const r = Number(m[1]);
  const g = Number(m[2]);
  const b = Number(m[3]);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.4;
}

test.describe('Publish-tab Layout save UX', () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/\/profile(\?|$)/, (route) => {
      if (route.request().method() === 'PATCH') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
      }
      // GET: a published persona currently on the default Classic theme.
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ theme_id: 'classic', accent: null, handle: 'e2e-persona' }),
      });
    });
  });

  test('Save & Publish is dark + legible in every state, and saves', async ({ page }) => {
    await page.goto('/dashboard/share');
    const card = page.getByRole('heading', { name: 'Layout', level: 2 }).locator('../../..');
    await expect(card).toBeVisible({ timeout: 30000 });
    const saveBtn = card.getByRole('button', { name: 'Save & Publish' });

    // On load (saved): button present, ENABLED, and DARK (not white-on-white). Status saved.
    await expect(saveBtn).toBeVisible();
    await expect(saveBtn).toBeEnabled();
    expect(isDark(await saveButtonBg(page)), 'save button must have a dark background').toBe(true);
    await expect(card.getByText('All changes saved')).toBeVisible();

    // Pick Editorial (reveals the Accent row) → status flips, button stays dark + visible.
    await card.getByRole('button', { name: /Editorial/ }).click();
    await expect(card.getByText('Unsaved changes')).toBeVisible();
    await expect(saveBtn).toBeVisible();
    await expect(saveBtn).toBeEnabled();
    expect(isDark(await saveButtonBg(page)), 'save button stays dark after the accent row appears').toBe(true);

    // Pick Site → still dark + visible (the original "no save button" case).
    await card.getByRole('button', { name: /Site/ }).click();
    await expect(saveBtn).toBeVisible();
    expect(isDark(await saveButtonBg(page)), 'save button is dark on the Site layout').toBe(true);

    // Save → PATCH /profile (stubbed 200) → status returns to "All changes saved".
    await saveBtn.click();
    await expect(card.getByText('All changes saved')).toBeVisible();
  });
});
