/**
 * Onboarding Full Flow E2E Test
 *
 * Tests the complete unified onboarding flow:
 * - Extended input form with all social URL fields
 * - Animated loading screen (ResearchLoadingScreen)
 * - Review step with handle preview and Publish My Persona CTA
 * - Published success screen ("You're live.")
 *
 * Uses mocked backend responses so the test runs without a real backend.
 * Mocks v2 research routes, handle endpoints, and publish endpoint.
 */

import { expect, test } from '@playwright/test';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const USE_REAL_BACKEND = process.env.E2E_USE_REAL_BACKEND === '1';

const TEST_PERSONA = {
  fullName: 'Jane Smith',
  headline: 'Product Leader at Acme',
  linkedinUrl: 'https://linkedin.com/in/janesmith',
  websiteUrl: 'https://janesmith.com',
};

const MOCK_TWIN_ID = 'e2e-twin-jane';
const MOCK_RESEARCH_RUN_ID = 'e2e-research-run-v2';

test.describe('Onboarding Full Flow — v2 API routes', () => {
  test.beforeEach(async ({ page }) => {
    test.setTimeout(90000);
    if (USE_REAL_BACKEND) return;

    // Mock GET /auth/connected-accounts
    await page.route('**/auth/connected-accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accounts: [] }),
      });
    });

    // Mock POST /profile - create profile
    await page.route('**/profile', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: { 'x-profile-created': 'true' },
          body: JSON.stringify({
            id: MOCK_TWIN_ID,
            name: TEST_PERSONA.fullName,
            status: 'draft',
            settings: {},
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock GET /twins/:id (profile data for review step) and PATCH /twins/:id (profile save)
    // Combined into one handler to prevent the second registration from shadowing the first.
    await page.route(new RegExp(`.*/twins/${MOCK_TWIN_ID}$`), async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: MOCK_TWIN_ID,
            name: TEST_PERSONA.fullName,
            status: 'draft',
            settings: {
              public_profile: {
                display_name: TEST_PERSONA.fullName,
                headline: TEST_PERSONA.headline,
                bio: 'Product leader with 10 years of experience in B2B SaaS.',
                short_description: 'PM at Acme',
                areas_of_expertise: ['Product Strategy', 'Team Leadership'],
                pinned_questions: ['How do you prioritize features?'],
              },
              public_profile_meta: { completeness_score: 75 },
            },
          }),
        });
      } else if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ id: MOCK_TWIN_ID, status: 'draft' }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock POST /v2/research/runs - create research run
    await page.route('**/v2/research/runs', async (route) => {
      if (route.request().method() === 'POST') {
        // Verify request body uses subject_name
        const body = route.request().postDataJSON() as Record<string, unknown>;
        expect(body).toHaveProperty('subject_name');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: MOCK_RESEARCH_RUN_ID,
            status: 'pending',
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock GET /v2/research/runs/:id - status polling
    await page.route(new RegExp(`.*/v2/research/runs/${MOCK_RESEARCH_RUN_ID}$`), async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: MOCK_RESEARCH_RUN_ID,
            status: 'completed',
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock POST /v2/research/runs/:id/compile
    await page.route(new RegExp(`.*/v2/research/runs/${MOCK_RESEARCH_RUN_ID}/compile$`), async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok' }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock GET /handles/check - handle availability check
    await page.route(new RegExp(`.*/handles/check`), async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ available: true }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock POST /handles/claim
    await page.route('**/handles/claim', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ handle: 'jane-smith', url: '/p/jane-smith' }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock POST /profile/publish
    await page.route('**/profile/publish', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            url: '/p/jane-smith',
            handle: 'jane-smith',
            share_token: 'mock-share-token',
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock mode-a (resume)
    await page.route('**/persona/link-compile/jobs/mode-a', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'e2e-job-a', status: 'pending' }),
      });
    });

    // Mock mode-c (URLs)
    await page.route('**/persona/link-compile/jobs/mode-c', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'e2e-job-c', status: 'pending' }),
      });
    });

    // Mock Wikipedia (return 404 to skip fast-index)
    await page.route('**/wikipedia.org/**', async (route) => {
      await route.fulfill({ status: 404 });
    });
  });

  // ---------------------------------------------------------------------------
  // Test 1: Form renders all fields
  // ---------------------------------------------------------------------------
  test('UI: onboarding form shows all social URL fields', async ({ page }) => {
    await page.goto('/onboarding', { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Heading per UI-SPEC
    await expect(page.getByRole('heading', { name: /Build your digital persona/i })).toBeVisible();

    // All URL fields visible at once
    await expect(page.getByPlaceholder('https://linkedin.com/in/yourname')).toBeVisible();
    await expect(page.getByPlaceholder('https://yoursite.com')).toBeVisible();
    await expect(page.getByPlaceholder('https://x.com/yourhandle')).toBeVisible();
    await expect(page.getByPlaceholder('https://github.com/yourname')).toBeVisible();
    await expect(page.getByPlaceholder('https://yourname.substack.com')).toBeVisible();
    await expect(page.getByPlaceholder('https://youtube.com/@yourchannel')).toBeVisible();

    // Submit button
    await expect(page.getByRole('button', { name: /Start Building/i })).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Test 2: DOCX/TXT upload acceptance
  // ---------------------------------------------------------------------------
  test('UI: file input accepts .docx and .txt', async ({ page }) => {
    await page.goto('/onboarding', { waitUntil: 'domcontentloaded', timeout: 60000 });

    const fileInput = page.locator('input[type="file"]');
    const acceptAttr = await fileInput.getAttribute('accept');
    expect(acceptAttr).toContain('.docx');
    expect(acceptAttr).toContain('.txt');
    expect(acceptAttr).toContain('.pdf');
  });

  // ---------------------------------------------------------------------------
  // Test 3: Full onboarding -> publish flow (ONBD-05)
  // ---------------------------------------------------------------------------
  test('full flow: onboarding form -> loading screen -> review -> publish', async ({ page }) => {
    test.setTimeout(USE_REAL_BACKEND ? 900000 : 120000);

    page.on('dialog', async (dialog) => {
      console.error('[E2E] Dialog:', dialog.message());
      await dialog.dismiss();
    });

    await page.goto('/onboarding', { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Step 1: Fill the form
    await page.getByPlaceholder('Jane Smith').fill(TEST_PERSONA.fullName);
    await page.getByPlaceholder('Product Leader at Acme - Ex-Google - 3x Founder').fill(TEST_PERSONA.headline);
    await page.getByPlaceholder('https://linkedin.com/in/yourname').fill(TEST_PERSONA.linkedinUrl);
    await page.getByPlaceholder('https://yoursite.com').fill(TEST_PERSONA.websiteUrl);

    // Check consent
    await page.getByRole('checkbox').check();

    // Submit
    await page.getByRole('button', { name: /Start Building/i }).click();

    // Step 2: Research loading screen should appear
    await expect(page.getByText('Building your digital persona')).toBeVisible({ timeout: 10000 });

    // Step 3: Wait for review step (after mocked research completes quickly)
    await expect(page.getByText('Review your persona')).toBeVisible({ timeout: 30000 });

    // Step 4: Handle preview should show /p/ prefix
    await expect(page.locator('text=/\\/p\\//')).toBeVisible({ timeout: 5000 });

    // Step 5: Publish My Persona CTA should be present
    await expect(page.getByRole('button', { name: /Publish My Persona/i })).toBeVisible();

    // Step 6: Click publish
    await page.getByRole('button', { name: /Publish My Persona/i }).click();

    // Step 7: "You're live." success screen
    await expect(page.getByText("You're live.")).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: /Copy your link/i })).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Test 4: Name validation
  // ---------------------------------------------------------------------------
  test('UI: shows name error when submitting without a name', async ({ page }) => {
    await page.goto('/onboarding', { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Click submit without filling name
    await page.getByRole('button', { name: /Start Building/i }).click();

    // Should show inline name error
    await expect(page.getByText('Please enter your name to continue.')).toBeVisible({ timeout: 5000 });
  });
});
