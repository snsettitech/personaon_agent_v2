import { expect, test, type Page, type Response } from '@playwright/test';

type ResearchStatus =
  | 'planning'
  | 'queued'
  | 'crawling'
  | 'awaiting_confirmation'
  | 'ready_for_ingestion'
  | 'ingesting'
  | 'ingestion_completed'
  | 'generating_bio'
  | 'bio_generated'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'timed_out';

interface ResearchRunPayload {
  research_run_id: string;
  status: ResearchStatus;
  checkpoint_data?: {
    warnings?: string[];
    ingestion?: {
      errors?: string[];
    };
  };
}

interface ClaimsStatusPayload {
  status?: string;
  error_message?: string;
}

interface CanaryConfig {
  email: string;
  password: string;
  fullName: string;
  headline?: string;
  location?: string;
  linkedinUrl?: string;
  researchTimeoutMs: number;
  claimsTimeoutMs: number;
  resetProfile: boolean;
}

interface RunObserver {
  runId: string | null;
  seenStatuses: ResearchStatus[];
  latestRun: ResearchRunPayload | null;
  latestClaimsStatus: ClaimsStatusPayload | null;
}

const config: CanaryConfig = {
  email: process.env.E2E_CANARY_EMAIL || '',
  password: process.env.E2E_CANARY_PASSWORD || '',
  fullName: process.env.E2E_CANARY_FULL_NAME || '',
  headline: process.env.E2E_CANARY_HEADLINE || '',
  location: process.env.E2E_CANARY_LOCATION || '',
  linkedinUrl: process.env.E2E_CANARY_LINKEDIN_URL || '',
  researchTimeoutMs: Number(process.env.E2E_CANARY_RESEARCH_TIMEOUT_MS || 180000),
  claimsTimeoutMs: Number(process.env.E2E_CANARY_CLAIMS_TIMEOUT_MS || 60000),
  resetProfile: (process.env.E2E_CANARY_RESET_PROFILE || '1') !== '0',
};

const requiredEnv = [
  'E2E_BASE_URL',
  'E2E_CANARY_EMAIL',
  'E2E_CANARY_PASSWORD',
  'E2E_CANARY_FULL_NAME',
].filter((key) => !process.env[key]);

test.describe('Production research canary', () => {
  test.describe.configure({ mode: 'serial' });

  test('QA onboarding can complete research on production', async ({ page }) => {
    test.skip(
      requiredEnv.length > 0,
      `Missing required env vars: ${requiredEnv.join(', ')}`
    );

    test.setTimeout(config.researchTimeoutMs + config.claimsTimeoutMs + 120000);

    const observer = attachRunObserver(page);

    await login(page);

    if (config.resetProfile) {
      await resetProfileViaUi(page);
    }

    await startOnboarding(page);
    await waitForRunCreation(observer, config.researchTimeoutMs);
    await progressResearchPipeline(page, observer);
    await expect(page.getByText('Research Failed')).toHaveCount(0);
    await handleClaimsReview(page, observer);
    await page.waitForURL(/\/dashboard\/profile/, { timeout: 30000 });
  });
});

function attachRunObserver(page: Page): RunObserver {
  const observer: RunObserver = {
    runId: null,
    seenStatuses: [],
    latestRun: null,
    latestClaimsStatus: null,
  };

  page.on('response', async (response: Response) => {
    try {
      const url = response.url();
      const method = response.request().method();

      if (method === 'POST' && /\/twins\/[^/]+\/research$/.test(url)) {
        const payload = (await response.json()) as Partial<ResearchRunPayload>;
        if (typeof payload.research_run_id === 'string') {
          observer.runId = payload.research_run_id;
        }
        return;
      }

      if (
        method === 'GET' &&
        /\/twins\/[^/]+\/research\/[^/?]+(?:\?.*)?$/.test(url) &&
        !url.includes('/pending-confirmations') &&
        !url.includes('/claims')
      ) {
        const payload = (await response.json()) as ResearchRunPayload;
        observer.latestRun = payload;
        if (payload.status) {
          observer.seenStatuses.push(payload.status);
        }
        if (!observer.runId && typeof payload.research_run_id === 'string') {
          observer.runId = payload.research_run_id;
        }
        return;
      }

      if (method === 'GET' && /\/claims-status(?:\?.*)?$/.test(url)) {
        observer.latestClaimsStatus = (await response.json()) as ClaimsStatusPayload;
      }
    } catch {
      // Ignore non-JSON responses and continue collecting subsequent events.
    }
  });

  return observer;
}

async function login(page: Page): Promise<void> {
  await page.goto('/auth/login?redirect=/dashboard/settings', {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });

  await page.getByPlaceholder('you@example.com').fill(config.email);
  await page.locator('input[type="password"]').fill(config.password);
  await page.getByRole('button', { name: 'Sign in' }).click();

  await page.waitForFunction(() => {
    const path = window.location.pathname;
    return (
      path !== '/auth/login' &&
      (path.startsWith('/onboarding') ||
        path.startsWith('/dashboard/settings') ||
        path.startsWith('/dashboard/profile') ||
        path.startsWith('/dashboard'))
    );
  }, { timeout: 60000 });
}

async function resetProfileViaUi(page: Page): Promise<boolean> {
  await page.goto('/dashboard/settings', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});

  const dangerZoneButton = page.getByRole('button', { name: 'Danger Zone' });
  if (!(await dangerZoneButton.isVisible().catch(() => false))) {
    return false;
  }

  await dangerZoneButton.click();

  const resetButton = page.getByRole('button', { name: /^Reset$/ });
  await expect(resetButton).toBeVisible({ timeout: 30000 });
  await resetButton.click();

  const reviewModal = page.getByRole('heading', { name: 'Reset Profile' });
  await expect(reviewModal).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Continue' }).click();

  const confirmHeading = page.getByRole('heading', { name: 'Confirm Profile Reset' });
  await expect(confirmHeading).toBeVisible({ timeout: 30000 });

  const confirmInput = page.locator('input[type="text"]').last();
  const placeholder = (await confirmInput.getAttribute('placeholder')) || '';
  const confirmValue = placeholder.split(' or ')[0].trim();
  if (!confirmValue) {
    throw new Error('Could not derive reset confirmation text from the modal placeholder.');
  }

  await confirmInput.fill(confirmValue);
  await page.getByRole('button', { name: 'Reset Profile' }).click();
  await expect(confirmHeading).toHaveCount(0, { timeout: 60000 });
  return true;
}

async function startOnboarding(page: Page): Promise<void> {
  await page.goto('/onboarding', { waitUntil: 'domcontentloaded', timeout: 60000 });

  await page.getByPlaceholder('e.g., Sarah Chen').fill(config.fullName);

  if (config.headline) {
    await page.getByPlaceholder('e.g., Founder at Acme').fill(config.headline);
  }

  if (config.location) {
    await page.getByPlaceholder('e.g., San Francisco, CA').fill(config.location);
  }

  if (config.linkedinUrl) {
    await page.getByPlaceholder('https://linkedin.com/in/yourprofile').fill(config.linkedinUrl);
  }

  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create My AI Persona' }).click();
}

async function waitForRunCreation(observer: RunObserver, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!observer.runId && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  if (!observer.runId) {
    throw new Error('Timed out waiting for research run creation.');
  }
}

async function waitForResearchState(
  page: Page,
  observer: RunObserver,
  predicate: (status: ResearchStatus | undefined) => boolean,
  timeoutMs: number,
  description: string
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = observer.latestRun?.status;

    if (status === 'failed' || status === 'timed_out') {
      throw new Error(
        `Research entered terminal error state "${status}": ${getFailureReason(observer.latestRun)}`
      );
    }

    if (predicate(status)) {
      return;
    }

    if (await page.getByText('Research Failed').count()) {
      throw new Error(`UI entered failed state: ${getFailureReason(observer.latestRun)}`);
    }

    await page.waitForTimeout(1500);
  }

  throw new Error(
    `Timed out waiting for ${description}. Seen statuses: ${observer.seenStatuses.join(' -> ')}`
  );
}

async function progressResearchPipeline(page: Page, observer: RunObserver): Promise<void> {
  const deadline = Date.now() + config.researchTimeoutMs + 120000;

  while (Date.now() < deadline) {
    const status = observer.latestRun?.status;

    if (status === 'failed' || status === 'timed_out') {
      throw new Error(
        `Research entered terminal error state "${status}": ${getFailureReason(observer.latestRun)}`
      );
    }

    if (status === 'completed') {
      return;
    }

    if (await page.getByText('Research Failed').count()) {
      throw new Error(`UI entered failed state: ${getFailureReason(observer.latestRun)}`);
    }

    if (await page.getByRole('heading', { name: 'Review Discovered Sources' }).count()) {
      await resolveAllConfirmations(page);
      await page.waitForTimeout(1000);
      continue;
    }

    const continueToIngestion = page.getByRole('button', { name: 'Continue to Ingestion' });
    if (await continueToIngestion.isVisible().catch(() => false)) {
      await continueToIngestion.click();
      await page.waitForTimeout(1000);
      continue;
    }

    const generateBio = page.getByRole('button', { name: 'Generate Bio' });
    if (await generateBio.isVisible().catch(() => false)) {
      await generateBio.click();
      await page.waitForTimeout(1000);
      continue;
    }

    const finalize = page.getByRole('button', { name: 'Finalize' });
    if (await finalize.isVisible().catch(() => false)) {
      await finalize.click();
      await page.waitForTimeout(1000);
      continue;
    }

    await page.waitForTimeout(1500);
  }

  throw new Error(
    `Timed out waiting for research pipeline completion. Seen statuses: ${observer.seenStatuses.join(' -> ')}`
  );
}

async function resolveAllConfirmations(page: Page): Promise<void> {
  await expect(
    page.getByRole('heading', { name: 'Review Discovered Sources' })
  ).toBeVisible({ timeout: 60000 });

  for (let attempts = 0; attempts < 50; attempts++) {
    const confirmButton = page.getByRole('button', { name: 'This is Me' }).first();
    if ((await confirmButton.count()) === 0) {
      break;
    }

    await confirmButton.click();
    await page.waitForTimeout(1000);
  }

  const continueButtons = [
    page.getByRole('button', { name: /^Continue\b/i }),
    page.getByRole('button', { name: 'Continue to Ingestion' }),
  ];

  for (const button of continueButtons) {
    if (await button.isVisible().catch(() => false)) {
      await button.click();
      return;
    }
  }
}

async function handleClaimsReview(page: Page, observer: RunObserver): Promise<void> {
  const deadline = Date.now() + config.claimsTimeoutMs;

  while (Date.now() < deadline) {
    if (await page.getByText('Claims Extraction Failed').count()) {
      throw new Error(
        `Claims extraction failed: ${observer.latestClaimsStatus?.error_message || 'Unknown error'}`
      );
    }

    const reviewHeading = page.getByRole('heading', { name: 'Review Extracted Claims' });
    if (await reviewHeading.isVisible().catch(() => false)) {
      const skipButton = page.getByRole('button', { name: 'Skip Review' });
      await skipButton.click();
      return;
    }

    const continueButton = page.getByRole('button', { name: /^Continue\b/i });
    if (await continueButton.isVisible().catch(() => false)) {
      await continueButton.click();
      return;
    }

    await page.waitForTimeout(1500);
  }

  throw new Error(
    `Timed out waiting for claims review. Latest claims status: ${observer.latestClaimsStatus?.status || 'none'}`
  );
}

function getFailureReason(payload: ResearchRunPayload | null): string {
  if (!payload) {
    return 'No failure details were captured.';
  }

  const warnings = Array.isArray(payload.checkpoint_data?.warnings)
    ? payload.checkpoint_data?.warnings
    : [];
  const ingestionErrors = Array.isArray(payload.checkpoint_data?.ingestion?.errors)
    ? payload.checkpoint_data?.ingestion?.errors
    : [];

  return warnings[warnings.length - 1] || ingestionErrors[0] || 'Unknown failure reason.';
}
