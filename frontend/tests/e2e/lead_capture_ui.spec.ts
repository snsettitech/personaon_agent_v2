/**
 * Lead Capture UI -- E2E Tests
 *
 * Covers:
 *   LC-01  /dashboard/widget/leads shows empty state when no leads
 *   LC-02  Widget settings renders ToggleSwitch with role=switch
 *   LC-03  Enabling toggle reveals value_frame + booking_url fields
 *   LC-04  Save settings sends PATCH with correct widget_ui payload
 *   LC-05  Leads page shows all rows when API returns 3 leads
 *   LC-06  Clicking a row opens the slide-over detail panel
 *   LC-07  Mark contacted button sends PATCH /widget/leads/:id
 *   LC-08  Two-tap delete removes the lead row from the table
 *   LC-09  Search filter narrows visible rows to matching name
 *   LC-10  AssistantHome nudge appears when lead_capture_enabled is false
 *   LC-11  Dismiss button hides nudge and persists to localStorage
 *   LC-12  Typing bounce dots visible while stream is pending
 *   LC-13  Offer state strip appears when stream returns offer_state=offered
 *   LC-14  Booking URL in response renders as a rounded-full pill button
 *
 * All API calls are mocked -- no real backend required.
 * Auth is bypassed via NEXT_PUBLIC_E2E_BYPASS_AUTH=1 (playwright.config.ts).
 *
 * Run:
 *   npx playwright test tests/e2e/lead_capture_ui.spec.ts --project=chromium
 */

import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// Constants -- the E2E bypass twin is hardcoded in TwinContext
// ---------------------------------------------------------------------------

const E2E_TWIN_ID = 'e2e-twin';
const MOCK_HANDLE = 'jane-smith';
const MOCK_TWIN_ID = 'test-twin-id-persona';
const MOCK_SHARE_TOKEN = 'test-share-token';

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const MOCK_LEADS = [
  {
    id: 'lead-1',
    visitor_name: 'Alice Johnson',
    visitor_email: 'alice@example.com',
    source_domain: 'example.com',
    created_at: new Date('2025-01-15T10:00:00Z').toISOString(),
    turn_count: 5,
    conversation_id: 'conv-1',
    offer_state: 'offered',
    inferred_intent: 'Explore product offerings',
    inferred_visitor_type: 'Prospect',
    contacted_at: null,
  },
  {
    id: 'lead-2',
    visitor_name: 'Bob Williams',
    visitor_email: 'bob@acme.com',
    source_domain: 'acme.com',
    created_at: new Date('2025-01-16T11:00:00Z').toISOString(),
    turn_count: 3,
    conversation_id: 'conv-2',
    offer_state: 'accepted',
    inferred_intent: 'Partnership discussion',
    inferred_visitor_type: 'Partner',
    contacted_at: null,
  },
  {
    id: 'lead-3',
    visitor_name: 'Carol Davis',
    visitor_email: 'carol@startup.io',
    source_domain: 'startup.io',
    created_at: new Date('2025-01-17T09:00:00Z').toISOString(),
    turn_count: 2,
    conversation_id: 'conv-3',
    offer_state: null,
    inferred_intent: null,
    inferred_visitor_type: null,
    contacted_at: null,
  },
];

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
    ],
  },
  settings: { subscription_tier: 'free' },
};

// ---------------------------------------------------------------------------
// Route mock helpers
// ---------------------------------------------------------------------------

async function mockLeadsList(
  page: import('@playwright/test').Page,
  leads: typeof MOCK_LEADS
): Promise<void> {
  await page.route('**/widget/leads/list/' + E2E_TWIN_ID + '**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(leads),
    })
  );
}

async function mockLeadActions(
  page: import('@playwright/test').Page,
  leadId: string
): Promise<void> {
  await page.route('**/widget/leads/' + leadId, (route) => {
    if (route.request().method() === 'PATCH')
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    if (route.request().method() === 'DELETE')
      return route.fulfill({ status: 204, body: '' });
    return route.fallback();
  });
}

async function mockTwinPatch(
  page: import('@playwright/test').Page
): Promise<void> {
  await page.route('**/twins/' + E2E_TWIN_ID, (route) => {
    if (route.request().method() === 'PATCH')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: E2E_TWIN_ID, settings: {} }),
      });
    return route.fallback();
  });
}

async function mockPublicPersonaStream(
  page: import('@playwright/test').Page,
  ndjsonLines: string[]
): Promise<void> {
  await page.route('**/handles/resolve**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ twin_id: MOCK_TWIN_ID, share_token: MOCK_SHARE_TOKEN }),
    })
  );
  await page.route(
    '**/share/' + MOCK_TWIN_ID + '/' + MOCK_SHARE_TOKEN + '/profile',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_PROFILE),
      })
  );
  await page.route(
    '**/v2/chat/public/' + MOCK_TWIN_ID + '/' + MOCK_SHARE_TOKEN + '/stream',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/x-ndjson',
        body: ndjsonLines.join('\n') + '\n',
      })
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Lead Capture UI', () => {
  test.setTimeout(30000);

  // LC-01 -------------------------------------------------------------------

  test('LC-01: /dashboard/widget/leads renders empty state when no leads', async ({ page }) => {
    await mockLeadsList(page, []);
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Your leads').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('No leads yet').first()).toBeVisible({ timeout: 8000 });
  });

  // LC-02 -------------------------------------------------------------------

  test('LC-02: widget settings renders ToggleSwitch with role="switch"', async ({ page }) => {
    await page.goto('/dashboard/widget/settings');
    await expect(page.getByText('Widget Settings').first()).toBeVisible({ timeout: 10000 });

    const toggle = page.getByRole('switch');
    await expect(toggle).toBeVisible({ timeout: 5000 });
    // E2E bypass twin has no widget_ui -- lead_capture_enabled defaults false
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  // LC-03 -------------------------------------------------------------------

  test('LC-03: enabling toggle reveals value_frame select and booking_url input', async ({ page }) => {
    await page.goto('/dashboard/widget/settings');
    await expect(page.getByText('Widget Settings').first()).toBeVisible({ timeout: 10000 });

    const toggle = page.getByRole('switch');
    await expect(toggle).toBeVisible();

    // Extra fields absent before enabling
    await expect(page.getByText('Frame these visitors as').first()).not.toBeVisible();
    await expect(page.getByPlaceholder('https://cal.com/yourname')).not.toBeVisible();

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');

    // Extra fields appear after enabling
    await expect(page.getByText('Frame these visitors as').first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByPlaceholder('https://cal.com/yourname')).toBeVisible();
  });

  // LC-04 -------------------------------------------------------------------

  test('LC-04: save settings sends PATCH with widget_ui fields', async ({ page }) => {
    await mockTwinPatch(page);
    await page.goto('/dashboard/widget/settings');
    await expect(page.getByText('Widget Settings').first()).toBeVisible({ timeout: 10000 });

    const toggle = page.getByRole('switch');
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');

    const bookingInput = page.getByPlaceholder('https://cal.com/yourname');
    await expect(bookingInput).toBeVisible();
    await bookingInput.fill('https://cal.com/janesmith');

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes('/twins/' + E2E_TWIN_ID) && req.method() === 'PATCH'
    );
    await page.getByRole('button', { name: 'Save settings' }).click();

    const patchRequest = await patchPromise;
    const body = JSON.parse(patchRequest.postData() ?? '{}') as {
      settings?: { widget_ui?: Record<string, unknown> };
    };
    expect(body?.settings?.widget_ui?.lead_capture_enabled).toBe(true);
    expect(body?.settings?.widget_ui?.booking_url).toBe('https://cal.com/janesmith');
  });

  // LC-05 -------------------------------------------------------------------

  test('LC-05: leads page shows table rows for all returned leads', async ({ page }) => {
    await mockLeadsList(page, MOCK_LEADS);
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Alice Johnson').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Bob Williams').first()).toBeVisible();
    await expect(page.getByText('Carol Davis').first()).toBeVisible();
    // OfferBadge renders inside a <span> with rounded-full -- avoid matching
    // the hidden <option value="offered"> inside the filter <select>
    await expect(page.locator('span', { hasText: 'Offered' }).first()).toBeVisible();
    await expect(page.locator('span', { hasText: 'Accepted' }).first()).toBeVisible();
  });

  // LC-06 -------------------------------------------------------------------

  test('LC-06: clicking a lead row opens the detail slide-over panel', async ({ page }) => {
    await mockLeadsList(page, MOCK_LEADS);
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Alice Johnson').first()).toBeVisible({ timeout: 10000 });
    await page.getByText('Alice Johnson').first().click();
    await expect(page.getByText('Lead detail').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('alice@example.com').first()).toBeVisible();
  });

  // LC-07 -------------------------------------------------------------------

  test('LC-07: Mark contacted button sends PATCH /widget/leads/:id', async ({ page }) => {
    await mockLeadsList(page, MOCK_LEADS);
    await mockLeadActions(page, 'lead-1');
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Alice Johnson').first()).toBeVisible({ timeout: 10000 });
    await page.getByText('Alice Johnson').first().click();
    await expect(page.getByText('Lead detail').first()).toBeVisible({ timeout: 5000 });

    const patchPromise = page.waitForRequest(
      (req) => req.url().includes('/widget/leads/lead-1') && req.method() === 'PATCH'
    );
    await page.getByRole('button', { name: 'Mark as contacted' }).first().click();
    const patchReq = await patchPromise;
    expect(patchReq.url()).toContain('/widget/leads/lead-1');

    // Button label changes after successful mark
    await expect(
      page.getByText('✓ Marked as contacted').first()
    ).toBeVisible({ timeout: 5000 });
  });

  // LC-08 -------------------------------------------------------------------

  test('LC-08: two-tap delete removes the lead row from the table', async ({ page }) => {
    await mockLeadsList(page, MOCK_LEADS);
    await mockLeadActions(page, 'lead-2');
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Bob Williams').first()).toBeVisible({ timeout: 10000 });
    await page.getByText('Bob Williams').first().click();
    await expect(page.getByText('Lead detail').first()).toBeVisible({ timeout: 5000 });

    // First click: enter confirmation state
    const deleteBtn = page.getByRole('button', { name: 'Delete lead' }).first();
    await deleteBtn.click();

    const confirmBtn = page.getByRole('button', { name: 'Confirm delete' }).first();
    await expect(confirmBtn).toBeVisible({ timeout: 3000 });

    const deletePromise = page.waitForRequest(
      (req) => req.url().includes('/widget/leads/lead-2') && req.method() === 'DELETE'
    );
    // Second click: execute delete
    await confirmBtn.click();
    await deletePromise;

    // Panel closed; row removed from table
    await expect(page.getByText('Lead detail')).not.toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Bob Williams')).not.toBeVisible({ timeout: 5000 });
  });

  // LC-09 -------------------------------------------------------------------

  test('LC-09: search filter shows only matching lead name', async ({ page }) => {
    await mockLeadsList(page, MOCK_LEADS);
    await page.goto('/dashboard/widget/leads');
    await expect(page.getByText('Alice Johnson').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Bob Williams').first()).toBeVisible();
    await expect(page.getByText('Carol Davis').first()).toBeVisible();

    // Placeholder uses Unicode ellipsis U+2026
    const searchInput = page.getByPlaceholder('Search name, email, domain…');
    await searchInput.pressSequentially('Alice');

    await expect(page.getByText('Alice Johnson').first()).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Bob Williams')).not.toBeVisible();
    await expect(page.getByText('Carol Davis')).not.toBeVisible();
  });

  // LC-10 -------------------------------------------------------------------

  test('LC-10: nudge appears on /dashboard when lead_capture_enabled is false', async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem('nudge_capture_dismissed_e2e-twin'); } catch { /* ignore */ }
    });

    // AssistantHome calls useHomeStatus which hits these three tenant endpoints.
    // Returning empty/null keeps the status cards hidden and lets AssistantHome render.
    await page.route('**/v2/twins/e2e-twin/readiness**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ score: 0, max: 10, label: 'Low' }) })
    );
    await page.route('**/v2/dashboard/pending**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { to_review: 0, follow_ups: 0, visitor_questions: 0 } }) })
    );
    await page.route('**/v2/chat/conversations**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ conversations: [] }) })
    );
    // AssistantChat needs a chat endpoint to exist (won't be called unless user sends a message)
    await page.route('**/v2/chat/assistant/**', (route) => route.fulfill({ status: 200, body: '' }));

    await page.goto('/dashboard');

    // AssistantHome.tsx: "You're missing every lead that visits you"
    // The apostrophe is a JSX &apos; which renders as a Unicode right-single-quote U+2019
    await expect(
      page.getByText(/missing every lead that visits you/).first()
    ).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('link', { name: 'Enable capture' })).toBeVisible();
  });

  // LC-11 -------------------------------------------------------------------

  test('LC-11: dismiss button hides nudge and stores dismissal in localStorage', async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem('nudge_capture_dismissed_e2e-twin'); } catch { /* ignore */ }
    });

    await page.route('**/v2/twins/e2e-twin/readiness**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ score: 0, max: 10, label: 'Low' }) })
    );
    await page.route('**/v2/dashboard/pending**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: { to_review: 0, follow_ups: 0, visitor_questions: 0 } }) })
    );
    await page.route('**/v2/chat/conversations**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ conversations: [] }) })
    );
    await page.route('**/v2/chat/assistant/**', (route) => route.fulfill({ status: 200, body: '' }));

    await page.goto('/dashboard');

    const nudgeText = page.getByText(/missing every lead that visits you/).first();
    await expect(nudgeText).toBeVisible({ timeout: 15000 });

    const dismissBtn = page.getByRole('button', { name: 'Dismiss' });
    await expect(dismissBtn).toBeVisible();
    await dismissBtn.click();

    // Nudge disappears immediately
    await expect(nudgeText).not.toBeVisible({ timeout: 5000 });

    // localStorage entry set
    const stored = await page.evaluate(() => {
      try {
        return localStorage.getItem('nudge_capture_dismissed_e2e-twin');
      } catch {
        return null;
      }
    });
    expect(stored).toBe('1');

    // Persistence is verified by the localStorage assertion above.
    // A page.reload() check is not reliable here: the init script at line 386
    // re-runs on every navigation (including reload) and removes the key before
    // the page renders, making the assertion pass for the wrong reason.
  });

  // LC-12 -------------------------------------------------------------------

  test('LC-12: typing bounce indicator visible while stream is pending', async ({ page }) => {
    // The typing indicator (isSending && !streamStarted && empty last message) requires:
    // 1. fetch() to resolve with response headers (so code reaches setMessages(add empty))
    // 2. No content bytes yet (so streamStarted stays false)
    //
    // page.route() fulfill holds the ENTIRE response including headers -- so fetch() never
    // resolves until we call fulfill. Instead we use addInitScript to monkey-patch fetch()
    // in the page context, returning a Response with a ReadableStream body that we control
    // from the test via a window flag. This lets fetch() resolve immediately (headers 200)
    // but delays the body bytes.
    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      // @ts-expect-error -- test-only global, not on Window
      window.__streamControllers = {};
      // `as typeof fetch`: the lib type for `typeof fetch` now declares an experimental
      // `preconnect` static method (Node/undici) that a plain mock function can never
      // implement. This assertion only satisfies that type shape for tsc - nothing in
      // this test calls or depends on `fetch.preconnect`.
      window.fetch = (async (...args: Parameters<typeof fetch>) => {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url;
        if (url.includes('/v2/chat/public/') && url.includes('/stream')) {
          const stream = new ReadableStream({
            start(controller) {
              // @ts-expect-error -- test-only global, not on Window
              window.__streamControllers['chat'] = controller;
            },
          });
          return new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'application/x-ndjson' },
          });
        }
        return originalFetch(...args);
      }) as typeof fetch;
    });

    await page.route('**/handles/resolve**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ twin_id: MOCK_TWIN_ID, share_token: MOCK_SHARE_TOKEN }),
      })
    );
    await page.route(
      '**/share/' + MOCK_TWIN_ID + '/' + MOCK_SHARE_TOKEN + '/profile',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_PROFILE),
        })
    );

    await page.goto('/p/' + MOCK_HANDLE);
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 15000 });

    await page.getByPlaceholder('Ask me anything...').pressSequentially('What do you do?');
    await page.getByRole('button', { name: 'Send message' }).click();

    // Wait for the user message to confirm React processed the send
    await expect(page.getByText('What do you do?').first()).toBeVisible({ timeout: 5000 });

    // The typing indicator renders while isSending=true, streamStarted=false:
    // <span class="inline-flex gap-1.5"> containing 3 dot spans inside the bubble.
    const typingBubble = page.locator('span.inline-flex.gap-1\\.5');
    await expect(typingBubble).toBeVisible({ timeout: 8000 });

    // Release the stream: write NDJSON content then close
    await page.evaluate(() => {
      const encoder = new TextEncoder();
      // @ts-expect-error -- test-only global, not on Window
      const ctrl = window.__streamControllers['chat'];
      if (ctrl) {
        ctrl.enqueue(encoder.encode(JSON.stringify({ type: 'answer_token', content: 'I am Jane Smith.' }) + '\n'));
        ctrl.enqueue(encoder.encode(JSON.stringify({ type: 'done' }) + '\n'));
        ctrl.close();
      }
    });

    await expect(page.getByText('I am Jane Smith.').first()).toBeVisible({ timeout: 10000 });
    await expect(typingBubble).not.toBeVisible({ timeout: 5000 });
  });

  // LC-13 -------------------------------------------------------------------

  test('LC-13: offer state strip appears when stream returns offer_state=offered', async ({ page }) => {
    const ndjsonLines = [
      JSON.stringify({ type: 'answer_metadata', conversation_id: 'mock-conv', offer_state: 'offered' }),
      JSON.stringify({ type: 'answer_token', content: 'Great to connect with you!' }),
      JSON.stringify({ type: 'done' }),
    ];
    await mockPublicPersonaStream(page, ndjsonLines);

    await page.goto('/p/' + MOCK_HANDLE);
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 15000 });

    await page.getByPlaceholder('Ask me anything...').pressSequentially('Tell me about yourself');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Great to connect with you!').first()).toBeVisible({ timeout: 10000 });

    // Green offer strip rendered when offerState === 'offered'
    await expect(
      page.getByText('A meeting offer has been shared').first()
    ).toBeVisible({ timeout: 5000 });
  });

  // LC-14 -------------------------------------------------------------------

  test('LC-14: booking URL in chat response renders as pill button not a plain link', async ({ page }) => {
    const calUrl = 'https://cal.com/janesmith/30min';
    const ndjsonLines = [
      JSON.stringify({ type: 'answer_metadata', conversation_id: 'mock-conv' }),
      JSON.stringify({ type: 'answer_token', content: 'Book a time here: [Schedule](' + calUrl + ')' }),
      JSON.stringify({ type: 'done' }),
    ];
    await mockPublicPersonaStream(page, ndjsonLines);

    await page.goto('/p/' + MOCK_HANDLE);
    await expect(page.getByText('Jane Smith').first()).toBeVisible({ timeout: 15000 });

    await page.getByPlaceholder('Ask me anything...').pressSequentially('How do I book you?');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Book a time here').first()).toBeVisible({ timeout: 10000 });

    // PersonaConsole custom markdown: URLs matching /\/(book|cal|calendly|meetings|schedule)/i
    // render as rounded-full pill anchors, not plain underlined prose links
    const bookingPill = page.locator('a[href="' + calUrl + '"]');
    await expect(bookingPill).toBeVisible({ timeout: 5000 });
    const cls = await bookingPill.getAttribute('class');
    expect(cls).toContain('rounded-full');
  });

});
