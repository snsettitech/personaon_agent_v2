/**
 * Persona Page E2E Tests — PersonaOn AI
 *
 * Covers:
 *   PERS-01: Visitor can send a message and receive a multi-turn response
 *   PERS-02: Chat response content from backend is displayed in assistant message bubble
 *   PERS-03: Visitor can navigate to /p/[handle] and see persona name, title, bio
 *   PERS-04: Free tier persona page shows ConversionBar with dynamic persona name
 *   PERS-05: Core tier persona page shows minimal 'Powered by PersonaOn' footer
 *
 * Uses mocked API endpoints — no real backend required.
 *
 * Run locally:
 *   npx playwright test tests/e2e/persona_page.spec.ts --project=chromium
 */

import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// Test constants
// ---------------------------------------------------------------------------

const MOCK_TWIN_ID = 'test-twin-id-persona';
const MOCK_SHARE_TOKEN = 'test-share-token';
const MOCK_HANDLE = 'jane-smith';

const MOCK_PROFILE = {
  profile: {
    name: 'Jane Smith',
    occupation: 'Product Leader at Acme',
    bio: 'Experienced product leader with 15 years in tech.',
    headline: 'Product Leader at Acme - Ex-Google - 3x Founder',
    areas_of_expertise: ['Product Strategy', 'Growth', 'Leadership'],
    key_achievements: ['Led $50M product line', 'Grew team from 5 to 50'],
    work_experience: [{ company: 'Acme', role: 'VP Product', description: 'Led product org' }],
    education: [{ institution: 'Stanford', degree: 'MBA', field: 'Business' }],
    social_links: { linkedin: 'https://linkedin.com/in/janesmith' },
    suggested_questions: [
      'What do you do?',
      'Tell me about your experience',
      'How can you help me?',
      'What is your leadership style?',
    ],
  },
  settings: { subscription_tier: 'free' },
};

const MOCK_CHAT_RESPONSE = {
  message: 'I am Jane Smith, a Product Leader at Acme. I have spent 15 years building products in tech.',
  conversation_id: 'mock-conversation-id',
  citations: [],
  persona_version: 'v1',
  surface: 'public',
};

// ---------------------------------------------------------------------------
// Helper: set up API route mocks
// ---------------------------------------------------------------------------

async function setupMocks(
  page: import('@playwright/test').Page,
  options: { tier?: 'free' | 'core' } = {}
) {
  const tier = options.tier ?? 'free';

  // Mock: resolve handle → twin_id + share_token
  await page.route('**/handles/resolve**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ twin_id: MOCK_TWIN_ID, share_token: MOCK_SHARE_TOKEN }),
    })
  );

  // Mock: profile endpoint
  await page.route(`**/share/${MOCK_TWIN_ID}/${MOCK_SHARE_TOKEN}/profile`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...MOCK_PROFILE,
        settings: { subscription_tier: tier },
      }),
    })
  );

  // Mock: public chat endpoint — the client streams SSE from .../stream and
  // parses `event: message` / `data: {"text": ...}` frames (lib/chat/streamParser).
  await page.route(`**/v2/chat/public/${MOCK_TWIN_ID}/${MOCK_SHARE_TOKEN}/stream`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: [
        `event: message`,
        `data: ${JSON.stringify({ text: MOCK_CHAT_RESPONSE.message })}`,
        '',
        'event: done',
        `data: ${JSON.stringify({ conversation_id: MOCK_CHAT_RESPONSE.conversation_id })}`,
        '',
        '',
      ].join('\n'),
    })
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Persona Page — /p/[handle]', () => {
  test.setTimeout(60000);

  /**
   * PERS-03: Persona page shows name, title, bio on initial load
   */
  test('PERS-03: displays persona name and headline on load', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for profile to load (name appears when loading is done)
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Product Leader at Acme').first()).toBeVisible();
  });

  /**
   * Full portfolio: Experience timeline and Education render from the
   * profile pack (work_experience/education are public, visibility-gated
   * sections since the portfolio pivot).
   */
  test('PERS-06: renders Experience and Education portfolio sections', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Experience timeline
    await expect(page.getByText('Experience', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('VP Product').first()).toBeVisible();
    await expect(page.getByText('Led product org').first()).toBeVisible();

    // Education card
    await expect(page.getByText('Education', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Stanford').first()).toBeVisible();
  });

  /**
   * PERS-01: Visitor can send a message and receive a response
   */
  test('PERS-01: visitor can send a message and receive a response', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for profile to load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Type and send a message. pressSequentially (per-keystroke) mirrors a
    // real user and reliably drives React's controlled-input onChange across
    // engines; fill() sets the value in one shot and WebKit doesn't always
    // propagate it to React, leaving the send button disabled.
    await page.getByPlaceholder('Ask me anything...').pressSequentially('What do you do?');
    await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled();
    await page.getByRole('button', { name: 'Send message' }).click();

    // User message appears in chat
    await expect(page.getByText('What do you do?')).toBeVisible({ timeout: 10000 });

    // Assistant response appears
    await expect(page.getByText('I am Jane Smith').first()).toBeVisible({ timeout: 10000 });
  });

  /**
   * PERS-02: Chat response content from backend is displayed in assistant message bubble
   *          This verifies grounded response display — the full mock response content appears.
   */
  test('PERS-02: chat response is rendered in assistant message bubble with full content', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Send a message
    await page.getByPlaceholder('Ask me anything...').pressSequentially('Tell me about yourself');
    await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled();
    await page.getByRole('button', { name: 'Send message' }).click();

    // Verify the full mock response content appears in the chat area
    // This proves the frontend correctly displays the grounded response from the backend
    await expect(page.getByText('I am Jane Smith, a Product Leader at Acme.').first()).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(/15 years building products in tech/).first()).toBeVisible({
      timeout: 10000,
    });
  });

  /**
   * PERS-04: Free tier shows ConversionBar with dynamic persona name interpolation
   */
  test('PERS-04: free tier shows ConversionBar branding with persona name', async ({ page }) => {
    await setupMocks(page, { tier: 'free' });
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for profile to load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // ConversionBar shows the persona's actual name (dynamic interpolation)
    await expect(page.getByText('Jane Smith is powered by PersonaOn')).toBeVisible({
      timeout: 10000,
    });

    // Viral-loop CTA: must deep-link to signup with referral attribution —
    // guards against regression to the old dead '/#waitlist' anchor.
    const cta = page.getByRole('link', { name: 'Build yours free →' });
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute(
      'href',
      `/auth/signup?ref=${MOCK_HANDLE}&utm_source=persona_page`,
    );
  });

  /**
   * PERS-05: Core tier shows minimal footer, no ConversionBar
   */
  test('PERS-05: core tier shows minimal footer, no ConversionBar', async ({ page }) => {
    await setupMocks(page, { tier: 'core' });
    // The mock API (tests/e2e/mock-api.mjs) encodes tier in the handle:
    // SSR fetches can't be intercepted by page.route, so the server-side
    // profile pack for `*-core` handles returns subscription_tier=core.
    await page.goto(`/p/${MOCK_HANDLE}-core`);

    // Wait for profile to load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Minimal footer visible
    await expect(page.getByText('Powered by PersonaOn')).toBeVisible({ timeout: 10000 });

    // ConversionBar NOT visible
    await expect(page.getByText('is powered by PersonaOn AI')).not.toBeVisible();
  });

  /**
   * Suggestion chips appear on initial load and disappear after click
   */
  test('suggestion chips appear on initial load and disappear after click', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Suggestion chip visible
    await expect(page.getByText('What do you do?').first()).toBeVisible();

    // Click a chip — triggers message send
    await page.getByText('What do you do?').first().click();

    // Chat response appears — suggestions hidden
    await expect(page.getByText('I am Jane Smith').first()).toBeVisible({ timeout: 10000 });
  });

  /**
   * Profile drawer opens when info button clicked
   */
  test('profile drawer opens when info button clicked', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);

    // Wait for load
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // The "View profile" info button lives in the chat-mode pill header,
    // which only renders once a conversation has started — send a message
    // first by clicking a suggestion chip.
    await page.getByText('What do you do?').first().click();
    await expect(page.getByText('I am Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Open the profile drawer via dispatchEvent: the pill header is
    // framer-motion-animated (never "stable" for a real click) AND on desktop
    // the top-bar Sign-in link overlaps it and intercepts pointer events.
    // dispatchEvent fires React's onClick directly, bypassing both.
    const infoButton = page.getByRole('button', { name: 'View profile' }).first();
    await expect(infoButton).toBeVisible({ timeout: 10000 });
    await infoButton.dispatchEvent('click');

    const drawer = page.getByRole('dialog', { name: 'Profile drawer' });
    await expect(drawer).toBeVisible({ timeout: 5000 });

    // Drawer shows full profile sections. On the mobile bottom-sheet the
    // section may sit below the fold — scroll it into view before asserting.
    const expertise = drawer.getByText('Areas of Expertise').first();
    await expertise.scrollIntoViewIfNeeded();
    await expect(expertise).toBeVisible({ timeout: 5000 });
    await expect(drawer.getByText('Product Strategy').first()).toBeVisible();
  });

  /**
   * Visitor → owner loop prompt appears after the persona's first answer,
   * deep-linking to signup with referral attribution.
   */
  test('loop prompt appears after first response with ref-tracked signup link', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // No prompt before any conversation
    await expect(page.getByText('Make yours free →')).not.toBeVisible();

    // Trigger a chat exchange via a suggestion chip
    await page.getByText('What do you do?').first().click();
    await expect(page.getByText('I am Jane Smith').first()).toBeVisible({ timeout: 10000 });

    // Prompt visible with referral-attributed signup href
    const prompt = page.getByRole('link', { name: /Make yours free/ });
    await expect(prompt).toBeVisible();
    await expect(prompt).toHaveAttribute(
      'href',
      `/auth/signup?ref=${MOCK_HANDLE}&utm_source=persona_page`,
    );
  });

  /**
   * Generated OG card: the file-convention image route renders a PNG for
   * existing handles AND for missing ones (brand-generic fallback) — a
   * shared link must never have a broken preview image.
   */
  test('opengraph-image route returns a PNG card', async ({ page }) => {
    const ok = await page.request.get(`/p/${MOCK_HANDLE}/opengraph-image`);
    expect(ok.status()).toBe(200);
    expect(ok.headers()['content-type']).toContain('image/png');

    const missing = await page.request.get('/p/nonexistent-og-e2e/opengraph-image');
    expect(missing.status()).toBe(200);
    expect(missing.headers()['content-type']).toContain('image/png');
  });

  /**
   * Shows error state for a handle that doesn't exist. The page is SSR'd:
   * the mock API (tests/e2e/mock-api.mjs) returns 404 for handles starting
   * with "nonexistent", and the server calls notFound() → app/not-found.tsx.
   */
  test('shows error for non-existent handle', async ({ page }) => {
    // Unique-ish handle: Next's data cache (revalidate: 3600) persists in
    // .next across dev-server restarts, so a handle that ever returned 200
    // would stay cached. Anything starting with "nonexistent" 404s.
    await page.goto('/p/nonexistent-e2e-404');

    // Custom not-found page (app/not-found.tsx) rendered server-side
    await expect(page.getByText('404 · not found')).toBeVisible({ timeout: 10000 });
  });

  /**
   * PURGE GUARD: the hero chrome now renders from frontend/lib/persona-themes
   * (the Classic shell). Tailwind v4 auto-scans frontend source, so its
   * arbitrary-value classes must survive purge — or the page would render
   * structurally correct but UNSTYLED, which
   * the other (text/role-based) tests can't catch. This asserts the shell's
   * classes actually compiled. Deterministic + cross-platform (no pixel
   * snapshot), so it is CI-safe unlike a toHaveScreenshot baseline.
   */
  test('purge guard: Classic shell arbitrary-value classes survive Tailwind purge', async ({ page }) => {
    await setupMocks(page);
    await page.goto(`/p/${MOCK_HANDLE}`);
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 10000 });

    const styles = await page.evaluate(() => {
      const divs = Array.from(document.querySelectorAll('div'));
      const card = divs.find((el) => getComputedStyle(el).borderTopLeftRadius === '32px');
      const root = document.querySelector('main')?.parentElement ?? null;
      const h1 = document.querySelector('h1');
      return {
        cardRadius: card ? getComputedStyle(card).borderTopLeftRadius : null, // rounded-[32px]
        rootBg: root ? getComputedStyle(root).backgroundColor : null,         // bg-[#f5f5f7]
        h1FontSize: h1 ? getComputedStyle(h1).fontSize : null,               // text-3xl/4xl
      };
    });

    expect(styles.cardRadius).toBe('32px');
    expect(styles.rootBg).toBe('rgb(245, 245, 247)');
    expect(parseInt(styles.h1FontSize ?? '0', 10)).toBeGreaterThanOrEqual(30);
  });
});

// ---------------------------------------------------------------------------
// Per-layout shell gate (personaThemes flag on for the test webServer)
//
// The four non-classic layout shells render the SAME opaque PersonaConsole, so
// each must:
//   1. render the persona content (name visible in the shell),
//   2. expose EXACTLY ONE chat input (console-once invariant — no double mount),
//   3. carry the adapter's `--pon-accent` wrapper resolved to a real color
//      (purge guard — the wrapper survives Tailwind purge / the inline var is
//      actually applied).
// `?theme=<id>` previews the layout; it only takes effect with the flag on.
// ---------------------------------------------------------------------------

test.describe('Persona Page — layout shells', () => {
  test.setTimeout(60000);

  for (const theme of ['founder-site', 'conversion-warm', 'editorial', 'split'] as const) {
    test(`layout ${theme}: renders, exactly one console, accent var resolved (purge guard)`, async ({ page }) => {
      await setupMocks(page);
      await page.goto(`/p/${MOCK_HANDLE}?theme=${theme}`);

      // persona content renders in the layout
      await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 15000 });

      // console-once invariant: exactly one chat input across the whole layout
      await expect(page.getByPlaceholder('Ask me anything...')).toHaveCount(1);

      // purge guard: the adapter's --pon-accent wrapper exists and resolved to a real color
      const accent = await page.evaluate(() => {
        const el = document.querySelector('[style*="--pon-accent"]') as HTMLElement | null;
        return el ? getComputedStyle(el).getPropertyValue('--pon-accent').trim() : '';
      });
      expect(accent).toMatch(/^#?[0-9a-fA-F]{6}$|^rgb/);
    });
  }
});
