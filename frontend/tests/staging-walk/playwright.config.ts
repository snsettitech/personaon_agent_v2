// Post-deploy browser walk of public staging routes (pilot step C3).
//
// Kept apart from frontend/playwright.config.ts (testDir ./tests/e2e) so it
// never runs in the normal e2e set, and with its own package.json so CI
// installs only Playwright, not the whole frontend.
//
// Run: STAGING_WALK_BASE_URL=https://<staging> npx playwright test
import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.STAGING_WALK_BASE_URL;
if (!baseURL) {
    throw new Error('STAGING_WALK_BASE_URL is required (the staging frontend origin)');
}

export default defineConfig({
    testDir: '.',
    // Not *.spec.ts / *.test.ts, so `bun test` never picks it up.
    testMatch: 'staging-walk.pw.ts',
    outputDir: './test-results',
    // Cloud Run cold starts can take several seconds on the first hit.
    timeout: 90_000,
    expect: { timeout: 15_000 },
    // One retry absorbs a cold start or a CDN blip; a real break fails twice.
    retries: process.env.CI ? 1 : 0,
    fullyParallel: true,
    workers: 3,
    reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
    use: {
        baseURL,
        trace: 'retain-on-failure',
        screenshot: 'off',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
