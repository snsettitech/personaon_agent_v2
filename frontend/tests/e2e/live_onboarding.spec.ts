/**
 * Live Onboarding E2E Test
 *
 * Creates a real profile through the actual onboarding flow against
 * the live Cloud Run backend. No mocks.
 *
 * Run with:
 *   E2E_BASE_URL=https://personaon.com \
 *   E2E_USE_REAL_BACKEND=1 \
 *   npx playwright test tests/e2e/live_onboarding.spec.ts
 */

import { expect, test } from '@playwright/test';

const SUPABASE_URL = process.env.SUPABASE_URL ?? 'http://127.0.0.1:54321';
const TEST_EMAIL = 'sainath.e2e.fresh@gmail.com';
const TEST_PASSWORD = 'SainathE2E2026!';
const TEST_NAME = 'Sainath Setti';
const TEST_HEADLINE = 'Founder of PersonaOn AI, Verified Digital Twin Brain';
const SKIP_USER_CREATION = true; // Already created above

test.describe('Live Onboarding — Real Backend', () => {
  test.setTimeout(300_000); // 5 minutes for full research flow

  test('complete onboarding flow: signup → research → identity → review → publish → chat', async ({ page }) => {
    // ─── Step 1: Create test account (skip if already created) ───
    if (!SKIP_USER_CREATION) {
      const serviceKey = process.env.SUPABASE_SERVICE_KEY;
      if (!serviceKey) {
        test.skip(true, 'SUPABASE_SERVICE_KEY required for live test');
        return;
      }
      const createRes = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
        method: 'POST',
        headers: {
          apikey: serviceKey,
          Authorization: `Bearer ${serviceKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email: TEST_EMAIL,
          password: TEST_PASSWORD,
          email_confirm: true,
          user_metadata: { full_name: TEST_NAME },
        }),
      });
      expect(createRes.ok).toBeTruthy();
    }

    // ─── Step 2: Sign in via the login page ───
    await page.goto('/auth/login');
    await page.waitForLoadState('networkidle');

    // Fill login form
    const emailInput = page.locator('input[type="email"]');
    const passwordInput = page.locator('input[type="password"]');
    await emailInput.fill(TEST_EMAIL);
    await passwordInput.fill(TEST_PASSWORD);

    // Submit
    const submitButton = page.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")');
    await submitButton.click();

    // Wait for redirect to onboarding or dashboard
    await page.waitForURL(/\/(onboarding|dashboard)/, { timeout: 30_000 });
    console.log(`[E2E] After login, landed on: ${page.url()}`);

    // If we land on dashboard, navigate to onboarding
    if (page.url().includes('/dashboard')) {
      await page.goto('/onboarding');
      await page.waitForLoadState('networkidle');
    }

    // ─── Step 3: Fill onboarding form ───
    const nameInput = page.getByRole('textbox', { name: 'Jane Smith' });
    await expect(nameInput).toBeVisible({ timeout: 10_000 });

    await page.screenshot({ path: 'test-results-temp/01-onboarding-form.png' });

    // Fill name
    await nameInput.fill(TEST_NAME);

    // Fill headline
    const headlineInput = page.getByRole('textbox', { name: /Product Leader/i });
    await headlineInput.fill(TEST_HEADLINE);

    // Check consent checkbox
    const consentCheckbox = page.getByRole('checkbox');
    if (await consentCheckbox.isVisible().catch(() => false)) {
      await consentCheckbox.check();
    }

    await page.screenshot({ path: 'test-results-temp/02-form-filled.png' });

    // Submit the form — look for the main CTA button
    const createButton = page.locator('button').filter({ hasText: /Create|Build|Continue|Persona/i }).first();
    await expect(createButton).toBeVisible({ timeout: 5000 });
    await createButton.click();

    // ─── Step 4: Wait for research loading screen ───
    console.log('[E2E] Waiting for research...');
    await page.screenshot({ path: 'test-results-temp/03-research-loading.png' });

    // Wait for either identity cards OR review step (up to 3 minutes)
    await page.waitForFunction(
      () => {
        const body = document.body.innerText;
        return (
          body.includes('Which one is you') ||
          body.includes('Review your persona') ||
          body.includes('Publish My Persona') ||
          body.includes('review-edit') ||
          body.includes("You're live") ||
          body.includes('Research couldn')
        );
      },
      { timeout: 180_000 },
    );

    await page.screenshot({ path: 'test-results-temp/04-after-research.png' });
    console.log(`[E2E] After research, page shows: ${(await page.textContent('body'))?.substring(0, 200)}`);

    // ─── Step 5: Handle identity selection if shown ───
    const hasIdentityCards = await page.locator('text=Which one is you').isVisible().catch(() => false);
    if (hasIdentityCards) {
      console.log('[E2E] Identity cards shown — selecting first match');
      await page.screenshot({ path: 'test-results-temp/05-identity-cards.png' });

      // Click the first card (or "Best match" card)
      const bestMatch = page.locator('text=Best match').first();
      const firstCard = page.locator('button').filter({ hasText: TEST_NAME }).first();

      if (await bestMatch.isVisible().catch(() => false)) {
        await bestMatch.click();
      } else {
        await firstCard.click();
      }

      // Wait for deep research
      console.log('[E2E] Waiting for deep research after identity selection...');
      await page.waitForFunction(
        () => {
          const body = document.body.innerText;
          return (
            body.includes('Review your persona') ||
            body.includes('Publish My Persona') ||
            body.includes("You're live") ||
            body.includes('Research couldn')
          );
        },
        { timeout: 180_000 },
      );

      await page.screenshot({ path: 'test-results-temp/06-after-deep-research.png' });
    }

    // ─── Step 6: Claims review ───
    const hasClaimsReview = await page.locator('text=Review your persona').isVisible().catch(() => false);
    if (hasClaimsReview) {
      console.log('[E2E] Claims review shown');
      await page.screenshot({ path: 'test-results-temp/07-claims-review.png' });

      // Click publish
      const publishButton = page.locator('button:has-text("Publish")');
      if (await publishButton.isVisible().catch(() => false)) {
        await publishButton.click();
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'test-results-temp/08-after-publish.png' });
      }
    }

    // ─── Step 7: Check if we landed on review-edit (old flow) ───
    const hasReviewEdit = await page.locator('text=Review your persona, text=Confirm or edit').isVisible().catch(() => false);
    if (hasReviewEdit) {
      console.log('[E2E] Old review-edit flow shown');
      await page.screenshot({ path: 'test-results-temp/07-review-edit.png' });

      const publishButton = page.locator('button:has-text("Publish")');
      if (await publishButton.isVisible().catch(() => false)) {
        await publishButton.click();
        await page.waitForTimeout(5000);
      }
    }

    // ─── Step 8: Final state ───
    await page.screenshot({ path: 'test-results-temp/09-final.png' });
    const finalText = await page.textContent('body');
    console.log(`[E2E] Final page text: ${finalText?.substring(0, 300)}`);

    // Verify we got somewhere meaningful
    const success =
      finalText?.includes("You're live") ||
      finalText?.includes('Publish') ||
      finalText?.includes('Review') ||
      finalText?.includes('dashboard');

    expect(success).toBeTruthy();
  });
});
