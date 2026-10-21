/**
 * Auth flow E2E tests — PersonaOn AI
 *
 * Covers:
 *   AUTH-01: User can sign up with email and password
 *   AUTH-02: User can log in and stay logged in across sessions
 *   AUTH-03: User can log out from any page
 *   AUTH-04: User session persists across browser refresh
 *
 * Environment variables required:
 *   PLAYWRIGHT_TEST_EMAIL    — test account email (must exist in Supabase test project)
 *   PLAYWRIGHT_TEST_PASSWORD — test account password
 *   PLAYWRIGHT_BASE_URL      — frontend URL (defaults to http://localhost:3000)
 *
 * Run locally:
 *   PLAYWRIGHT_TEST_EMAIL=test@example.com \
 *   PLAYWRIGHT_TEST_PASSWORD=TestPass123! \
 *   npx playwright test frontend/tests/e2e/auth_flow.spec.ts
 *
 * NOTE: Signup test generates a unique email to avoid "already registered" errors.
 * It verifies the redirect to /dashboard or /onboarding (both are valid for new users).
 */

import { test, expect, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000';
const TEST_EMAIL = process.env.PLAYWRIGHT_TEST_EMAIL || '';
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_PASSWORD || '';

// Helper: log in with known credentials
async function loginWithCredentials(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/auth/login`);
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole('button', { name: /sign in|log in|login/i }).click();
  // Wait for redirect to dashboard or onboarding
  await page.waitForURL(
    (url) => url.pathname.startsWith('/dashboard') || url.pathname.startsWith('/onboarding'),
    { timeout: 15000 }
  );
}

test.describe('AUTH-01: Signup', () => {
  test('user can sign up with a new email and reach an authenticated page', async ({ page }) => {
    // Generate a unique email to avoid "already registered" conflict
    const uniqueEmail = `e2e-test-${Date.now()}@personaon-test.dev`;
    const password = 'E2eTestPass123!';

    await page.goto(`${BASE_URL}/auth/signup`);
    await expect(page).toHaveURL(/signup/);

    await page.getByLabel(/email/i).fill(uniqueEmail);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole('button', { name: /sign up|create account|get started/i }).click();

    // After signup, Supabase sends a confirmation email in production.
    // In test/staging projects with email confirmation disabled, redirect happens immediately.
    // Accept either: redirect to /dashboard or /onboarding, OR a "check your email" message.
    await Promise.race([
      page.waitForURL(
        (url) => url.pathname.startsWith('/dashboard') || url.pathname.startsWith('/onboarding'),
        { timeout: 15000 }
      ),
      expect(page.getByText(/check your email|confirm your email|verification/i)).toBeVisible({ timeout: 15000 }),
    ]);
  });
});

test.describe('AUTH-02 + AUTH-04: Login and session persistence', () => {
  test.skip(!TEST_EMAIL || !TEST_PASSWORD, 'PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD required');

  test('AUTH-02: user can log in and reach dashboard', async ({ page }) => {
    await loginWithCredentials(page, TEST_EMAIL, TEST_PASSWORD);

    // Must be on a protected page after login
    const url = page.url();
    expect(url).toMatch(/\/dashboard|\/onboarding/);
  });

  test('AUTH-04: session persists across page refresh', async ({ page }) => {
    await loginWithCredentials(page, TEST_EMAIL, TEST_PASSWORD);

    // Hard refresh — tests cookie survival across browser reload
    await page.reload();

    // After refresh, must still be on an authenticated page (not redirected to login)
    await page.waitForLoadState('networkidle');
    const urlAfterRefresh = page.url();

    expect(urlAfterRefresh).not.toMatch(/\/auth\/login/);
    expect(urlAfterRefresh).toMatch(/\/dashboard|\/onboarding/);
  });

  test('AUTH-04: authenticated user navigating to / is redirected to dashboard', async ({ page }) => {
    await loginWithCredentials(page, TEST_EMAIL, TEST_PASSWORD);

    // Navigate to root — middleware should redirect authenticated users to /dashboard
    await page.goto(`${BASE_URL}/`);
    await page.waitForURL(
      (url) => url.pathname.startsWith('/dashboard') || url.pathname.startsWith('/onboarding'),
      { timeout: 10000 }
    );

    const url = page.url();
    expect(url).toMatch(/\/dashboard|\/onboarding/);
  });
});

test.describe('AUTH-03: Logout', () => {
  test.skip(!TEST_EMAIL || !TEST_PASSWORD, 'PLAYWRIGHT_TEST_EMAIL and PLAYWRIGHT_TEST_PASSWORD required');

  test('AUTH-03: user can log out and is redirected to login page', async ({ page }) => {
    await loginWithCredentials(page, TEST_EMAIL, TEST_PASSWORD);

    // Find and click the logout button (may be in a dropdown or sidebar)
    // Try common logout button patterns
    const logoutButton = page.getByRole('button', { name: /log out|sign out|logout/i })
      .or(page.getByRole('link', { name: /log out|sign out|logout/i }));

    await logoutButton.click();

    // After logout: must be redirected to login or root (which then redirects to login)
    await page.waitForURL(
      (url) => url.pathname.startsWith('/auth/login') || url.pathname === '/',
      { timeout: 10000 }
    );

    // Confirm no longer authenticated: try to access dashboard directly
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForURL(/\/auth\/login/, { timeout: 10000 });

    expect(page.url()).toContain('/auth/login');
  });
});

test.describe('Unauthenticated access protection', () => {
  test('unauthenticated user accessing /dashboard is redirected to /auth/login', async ({ page }) => {
    // Clear cookies to ensure unauthenticated state
    await page.context().clearCookies();

    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForURL(/\/auth\/login/, { timeout: 10000 });

    expect(page.url()).toContain('/auth/login');
  });
});
