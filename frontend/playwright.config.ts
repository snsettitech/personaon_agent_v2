import { defineConfig, devices } from '@playwright/test';

const localPort = process.env.E2E_PORT || '3000';
const baseURL = process.env.E2E_BASE_URL || `http://localhost:${localPort}`;
const useExternalBaseUrl = Boolean(process.env.E2E_BASE_URL);
const traceMode = process.env.PW_TRACE_MODE || (process.env.CI ? 'retain-on-failure' : 'on-first-retry');
const reporter = process.env.PW_REPORTER || 'html';

export default defineConfig({
    testDir: './tests/e2e',
    outputDir: './playwright-test-results',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: 1,
    reporter,
    use: {
        baseURL,
        trace: traceMode as 'on-first-retry' | 'retain-on-failure' | 'on' | 'off',
        screenshot: 'only-on-failure',
    },

    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
        // Cross-browser coverage for launch surfaces. Most LinkedIn-referred
        // traffic opens in iOS WebKit — Safari behavior is not optional.
        {
            name: 'webkit',
            use: { ...devices['Desktop Safari'] },
        },
        {
            name: 'firefox',
            use: { ...devices['Desktop Firefox'] },
        },
        {
            name: 'mobile-safari',
            use: { ...devices['iPhone 13'] },
        },
    ],

    webServer: useExternalBaseUrl
        ? undefined
        : [
              // Mock backend must be up before Next: /p/[handle] fetches its
              // profile pack server-side (SSR), which page.route() in specs
              // cannot intercept — it needs a real HTTP endpoint.
              {
                  command: 'node tests/e2e/mock-api.mjs',
                  url: 'http://localhost:8000/health',
                  reuseExistingServer: false,
                  timeout: 30000,
              },
              {
                  command: `npx next dev --webpack -p ${localPort}`,
                  url: baseURL,
                  reuseExistingServer: false,
                  timeout: 120000,
                  env: {
                      E2E_BYPASS_AUTH: '1',
                      NEXT_PUBLIC_E2E_BYPASS_AUTH: '1',
                      NEXT_PUBLIC_PERSONA_THEMES: '1',
                      NEXT_PUBLIC_BACKEND_URL: 'http://localhost:8000',
                      NEXT_PUBLIC_API_URL: 'http://localhost:8000',
                      NEXT_PUBLIC_DEMO_TWIN_ID: 'demo-twin',
                      NEXT_PUBLIC_DEMO_SHARE_TOKEN: 'demo-token',
                      // Required for /dashboard to render AssistantHome (not redirect to /meetings)
                      NEXT_PUBLIC_FLAG_ASSISTANT_HOME_V1: 'true',
                  },
              },
          ],
});
