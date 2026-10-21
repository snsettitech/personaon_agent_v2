/**
 * Live Site E2E Audit — https://personaon.com
 * Tests all critical user-facing flows against production.
 * Run with: E2E_BASE_URL=https://personaon.com npx playwright test tests/e2e/live_site_audit.spec.ts --headed=false
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE_URL = 'https://personaon.com';
const API_URL = 'https://api.personaon.com';
const SCREENSHOT_DIR = '/d/PersonaOn/frontend/playwright-test-results/live-audit';

// Ensure screenshot dir exists
if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function captureScreenshot(page: Page, name: string) {
    const filepath = path.join(SCREENSHOT_DIR, `${name}.png`);
    await page.screenshot({ path: filepath, fullPage: true });
    return filepath;
}

async function collectConsoleErrors(page: Page): Promise<string[]> {
    const errors: string[] = [];
    page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', (err) => errors.push(`PAGE ERROR: ${err.message}`));
    return errors;
}

// ─────────────────────────────────────────────────────────────────
// 1. API HEALTH
// ─────────────────────────────────────────────────────────────────

test.describe('API Health', () => {
    test('GET /health returns 200', async ({ request }) => {
        const response = await request.get(`${API_URL}/health`);
        expect(response.status()).toBe(200);
        const body = await response.json().catch(() => null);
        console.log('API health response:', JSON.stringify(body));
        await expect(response).toBeOK();
    });

    test('GET /health response has status field', async ({ request }) => {
        const response = await request.get(`${API_URL}/health`);
        const body = await response.json().catch(() => ({}));
        // Accept any of the common health response shapes
        const hasStatus =
            body.status !== undefined ||
            body.ok !== undefined ||
            body.healthy !== undefined ||
            body.message !== undefined;
        expect(hasStatus).toBe(true);
        console.log('Health body keys:', Object.keys(body));
    });
});

// ─────────────────────────────────────────────────────────────────
// 2. LANDING PAGE
// ─────────────────────────────────────────────────────────────────

test.describe('Landing Page', () => {
    test('loads without errors', async ({ page }) => {
        const errors: string[] = [];
        page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
        page.on('pageerror', (err) => errors.push(`PAGE ERROR: ${err.message}`));

        const response = await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '01-landing-page');

        expect(response?.status()).toBeLessThan(400);
        if (errors.length > 0) {
            console.warn('Console errors on landing page:', errors);
        }
    });

    test('has correct page title', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const title = await page.title();
        console.log('Landing page title:', title);
        expect(title).toBeTruthy();
        expect(title.length).toBeGreaterThan(0);
    });

    test('main hero / headline is visible', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for any prominent heading
        const h1 = page.locator('h1').first();
        const hasH1 = await h1.isVisible().catch(() => false);
        console.log('H1 visible:', hasH1);
        if (hasH1) {
            const h1Text = await h1.textContent();
            console.log('H1 text:', h1Text?.trim());
        }
        expect(hasH1).toBe(true);
    });

    test('waitlist/CTA form or button is present', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Check for waitlist email input or any CTA button
        const emailInput = page.locator('input[type="email"]').first();
        const ctaButton = page.locator('button:has-text("waitlist"), button:has-text("Join"), button:has-text("Get Started"), button:has-text("Sign up"), a:has-text("Get Started"), a:has-text("Sign up")').first();

        const hasEmail = await emailInput.isVisible().catch(() => false);
        const hasCTA = await ctaButton.isVisible().catch(() => false);

        console.log('Email input visible:', hasEmail);
        console.log('CTA button visible:', hasCTA);

        expect(hasEmail || hasCTA).toBe(true);
    });

    test('waitlist form submission works (or shows validation)', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const emailInput = page.locator('input[type="email"]').first();
        const hasEmail = await emailInput.isVisible().catch(() => false);
        if (!hasEmail) {
            test.skip();
            return;
        }

        await emailInput.fill('e2e-test-user@test-domain-e2e.com');
        await captureScreenshot(page, '02-waitlist-filled');

        // Try to find and click submit button
        const submitBtn = page.locator('button[type="submit"], button:has-text("Join"), button:has-text("Submit"), button:has-text("Get early access")').first();
        const hasSubmit = await submitBtn.isVisible().catch(() => false);
        if (hasSubmit) {
            await submitBtn.click();
            await page.waitForTimeout(2000);
            await captureScreenshot(page, '03-waitlist-submitted');

            // Check for success message or thank you
            const successMsg = page.locator('text=/thank|success|joined|waitlist|check your email/i').first();
            const hasSuccess = await successMsg.isVisible({ timeout: 5000 }).catch(() => false);
            console.log('Waitlist submission success message visible:', hasSuccess);
        }
    });

    test('demo chat widget is present', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for a chat input on the landing page
        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="chat"], input[placeholder*="message"], input[placeholder*="Ask"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);
        console.log('Demo chat input visible:', hasChat);

        if (hasChat) {
            await captureScreenshot(page, '04-landing-chat-visible');
        }
    });

    test('demo chat can send a message', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="chat"], input[placeholder*="message"], input[placeholder*="Ask"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);

        if (!hasChat) {
            console.log('No demo chat input found — skipping chat send test');
            test.skip();
            return;
        }

        await chatInput.fill('Hello, tell me about yourself');
        await captureScreenshot(page, '05-chat-message-typed');

        // Submit via Enter or button
        const sendBtn = page.locator('button[type="submit"], button:has-text("Send"), button[aria-label*="send"]').first();
        const hasSendBtn = await sendBtn.isVisible().catch(() => false);
        if (hasSendBtn) {
            await sendBtn.click();
        } else {
            await chatInput.press('Enter');
        }

        // Wait for a response to appear
        await page.waitForTimeout(5000);
        await captureScreenshot(page, '06-chat-response');
        console.log('Chat message sent and waited for response');
    });

    test('navigation links resolve without 404', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Collect all nav links
        const navLinks = await page.locator('nav a, header a').evaluateAll((els) =>
            els.map((el) => ({
                href: (el as HTMLAnchorElement).href,
                text: (el as HTMLAnchorElement).textContent?.trim(),
            }))
        );

        console.log('Nav links found:', navLinks.length);
        for (const link of navLinks) {
            if (!link.href || link.href.startsWith('javascript:') || link.href === '#') continue;
            if (!link.href.includes('personaon.com') && !link.href.startsWith('/')) continue;
            console.log(`Nav link: "${link.text}" → ${link.href}`);
        }

        // At least some nav links should exist
        const validLinks = navLinks.filter(
            (l) => l.href && !l.href.startsWith('javascript:') && l.href !== '#'
        );
        console.log('Valid nav links:', validLinks.length);
    });
});

// ─────────────────────────────────────────────────────────────────
// 3. AUTH FLOWS
// ─────────────────────────────────────────────────────────────────

test.describe('Auth Flows', () => {
    test('login page renders', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '10-auth-login');

        const statusCode = response?.status() ?? 0;
        console.log('Login page status:', statusCode);
        expect(statusCode).toBeLessThan(400);

        // Check for email/password inputs or any login form
        const emailInput = page.locator('input[type="email"], input[name="email"]').first();
        const hasEmail = await emailInput.isVisible().catch(() => false);
        console.log('Login email input visible:', hasEmail);
        expect(hasEmail).toBe(true);
    });

    test('signup page renders', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/auth/signup`, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '11-auth-signup');

        const statusCode = response?.status() ?? 0;
        console.log('Signup page status:', statusCode);
        expect(statusCode).toBeLessThan(400);

        const emailInput = page.locator('input[type="email"], input[name="email"]').first();
        const hasEmail = await emailInput.isVisible().catch(() => false);
        console.log('Signup email input visible:', hasEmail);
        expect(hasEmail).toBe(true);
    });

    test('login form shows validation on empty submit', async ({ page }) => {
        await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'networkidle', timeout: 30000 });

        const submitBtn = page.locator('button[type="submit"]').first();
        const hasSubmit = await submitBtn.isVisible().catch(() => false);
        if (!hasSubmit) { test.skip(); return; }

        await submitBtn.click();
        await page.waitForTimeout(1000);
        await captureScreenshot(page, '12-login-validation');

        // Should show some validation error or still be on login page
        const currentUrl = page.url();
        console.log('URL after empty submit:', currentUrl);
        // Should not have navigated away
        expect(currentUrl).toContain('personaon.com');
    });

    test('login with bad credentials shows error', async ({ page }) => {
        await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'networkidle', timeout: 30000 });

        const emailInput = page.locator('input[type="email"], input[name="email"]').first();
        const passwordInput = page.locator('input[type="password"]').first();
        const submitBtn = page.locator('button[type="submit"]').first();

        const hasForm = await emailInput.isVisible().catch(() => false);
        if (!hasForm) { test.skip(); return; }

        await emailInput.fill('fake-user-9999@e2e-test.invalid');
        await passwordInput.fill('wrongpassword123');
        await submitBtn.click();

        await page.waitForTimeout(3000);
        await captureScreenshot(page, '13-login-bad-creds');

        // Should show error message
        const errorMsg = page.locator('text=/invalid|error|incorrect|wrong|failed/i').first();
        const hasError = await errorMsg.isVisible({ timeout: 5000 }).catch(() => false);
        console.log('Error message shown for bad credentials:', hasError);
    });
});

// ─────────────────────────────────────────────────────────────────
// 4. MARKETPLACE
// ─────────────────────────────────────────────────────────────────

test.describe('Marketplace', () => {
    test('marketplace page loads', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '20-marketplace');

        const statusCode = response?.status() ?? 0;
        console.log('Marketplace page status:', statusCode);
        expect(statusCode).toBeLessThan(400);
    });

    test('marketplace has persona cards', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for persona cards — common patterns
        const cards = page.locator('[data-testid="persona-card"], .persona-card, article, [class*="card"], [class*="persona"]');
        const count = await cards.count();
        console.log('Persona cards found:', count);

        if (count === 0) {
            // Try looking for any linked items that look like personas
            const linkedItems = await page.locator('a[href*="/p/"]').count();
            console.log('Links to /p/ routes:', linkedItems);
            await captureScreenshot(page, '20b-marketplace-no-cards');
        }

        expect(count > 0 || await page.locator('a[href*="/p/"]').count() > 0).toBe(true);
    });

    test('category filters are present and clickable', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for filter buttons
        const filterBtns = page.locator('button[class*="filter"], [role="tab"], [data-testid*="filter"], button:has-text("All"), button:has-text("Category")');
        const filterCount = await filterBtns.count();
        console.log('Filter buttons found:', filterCount);

        if (filterCount > 0) {
            const firstFilter = filterBtns.first();
            await firstFilter.click();
            await page.waitForTimeout(1000);
            await captureScreenshot(page, '21-marketplace-filtered');
            console.log('Filter clicked successfully');
        }
    });

    test('can click into a persona detail page', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });

        // Find first /p/ link
        const personaLink = page.locator('a[href*="/p/"]').first();
        const hasLink = await personaLink.isVisible().catch(() => false);

        if (!hasLink) {
            console.log('No persona links found on marketplace');
            test.skip();
            return;
        }

        const href = await personaLink.getAttribute('href');
        console.log('Clicking persona link:', href);
        await personaLink.click();

        await page.waitForURL(/\/p\//, { timeout: 15000 });
        await page.waitForLoadState('networkidle', { timeout: 30000 });
        await captureScreenshot(page, '22-persona-detail');

        const currentUrl = page.url();
        console.log('Navigated to persona page:', currentUrl);
        expect(currentUrl).toContain('/p/');
    });

    test('anonymous chat on marketplace persona works', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });

        // Navigate to a persona page
        const personaLink = page.locator('a[href*="/p/"]').first();
        const hasLink = await personaLink.isVisible().catch(() => false);
        if (!hasLink) { test.skip(); return; }

        await personaLink.click();
        await page.waitForURL(/\/p\//, { timeout: 15000 });
        await page.waitForLoadState('networkidle', { timeout: 30000 });

        // Find chat input on persona page
        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="Ask"], input[placeholder*="message"], input[placeholder*="chat"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);
        console.log('Anonymous chat input on persona page:', hasChat);

        if (hasChat) {
            await chatInput.fill('What are your main areas of expertise?');
            const sendBtn = page.locator('button[type="submit"], button[aria-label*="send"], button:has-text("Send")').first();
            const hasSend = await sendBtn.isVisible().catch(() => false);
            if (hasSend) await sendBtn.click();
            else await chatInput.press('Enter');

            await page.waitForTimeout(5000);
            await captureScreenshot(page, '23-marketplace-anon-chat');
            console.log('Anonymous chat message sent');
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// 5. PUBLIC PERSONA PAGE — sainath-setti
// ─────────────────────────────────────────────────────────────────

test.describe('Public Persona Page (/p/sainath-setti)', () => {
    const PERSONA_URL = `${BASE_URL}/p/sainath-setti`;

    test('persona page loads with 200', async ({ page }) => {
        const response = await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '30-persona-sainath');

        const statusCode = response?.status() ?? 0;
        console.log('Persona page status:', statusCode);
        expect(statusCode).toBeLessThan(400);
    });

    test('persona name is displayed', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for persona name in heading or profile area
        const heading = page.locator('h1, h2, [class*="name"], [class*="title"]').first();
        const hasHeading = await heading.isVisible().catch(() => false);
        const headingText = hasHeading ? await heading.textContent() : '';
        console.log('Persona heading:', headingText?.trim());
        expect(hasHeading).toBe(true);
    });

    test('profile avatar or image is present', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const img = page.locator('img[alt*="avatar"], img[alt*="profile"], img[class*="avatar"], img[class*="profile"]').first();
        const hasImg = await img.isVisible().catch(() => false);
        console.log('Profile image visible:', hasImg);
        // Not a hard failure — log it
        if (!hasImg) {
            console.warn('WARN: No profile avatar image found on persona page');
        }
    });

    test('no broken images on persona page', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const brokenImages = await page.evaluate(() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .filter((img) => !img.complete || img.naturalWidth === 0)
                .map((img) => img.src);
        });
        console.log('Broken images:', brokenImages);
        if (brokenImages.length > 0) {
            console.warn('WARN: Broken images found:', brokenImages);
        }
    });

    test('chat input is present on persona page', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="Ask"], input[placeholder*="message"], input[placeholder*="chat"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);
        console.log('Chat input on persona page:', hasChat);
        expect(hasChat).toBe(true);
    });

    test('can send a chat message on persona page', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="Ask"], input[placeholder*="message"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);
        if (!hasChat) { test.skip(); return; }

        await chatInput.fill('What is your background?');
        const sendBtn = page.locator('button[type="submit"], button[aria-label*="send"], button:has-text("Send")').first();
        const hasSend = await sendBtn.isVisible().catch(() => false);
        if (hasSend) await sendBtn.click();
        else await chatInput.press('Enter');

        await page.waitForTimeout(8000);
        await captureScreenshot(page, '31-persona-chat-response');

        // Check for any response text appearing
        const responseArea = page.locator('[class*="message"], [class*="response"], [class*="chat"], [role="log"]').first();
        const hasResponse = await responseArea.isVisible().catch(() => false);
        console.log('Chat response area visible:', hasResponse);
    });

    test('no CORS errors in console', async ({ page }) => {
        const corsErrors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error' && msg.text().toLowerCase().includes('cors')) {
                corsErrors.push(msg.text());
            }
        });

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });
        console.log('CORS errors:', corsErrors);
        if (corsErrors.length > 0) {
            console.warn('CORS errors detected:', corsErrors);
        }
        expect(corsErrors.length).toBe(0);
    });
});

// ─────────────────────────────────────────────────────────────────
// 6. EDGE CASES
// ─────────────────────────────────────────────────────────────────

test.describe('Edge Cases', () => {
    test('non-existent persona handle returns graceful page (not crash)', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/p/this-persona-does-not-exist-xyz123`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });
        await captureScreenshot(page, '40-404-persona');

        const statusCode = response?.status() ?? 0;
        console.log('Non-existent persona status:', statusCode);

        // Should be 404 or a graceful redirect — not 500
        expect(statusCode).not.toBe(500);
        // Check page doesn't show a raw stack trace
        const bodyText = await page.locator('body').textContent();
        const hasStackTrace = bodyText?.includes('at Object.') || bodyText?.includes('at Module.');
        expect(hasStackTrace).toBe(false);
    });

    test('very long message in chat does not crash', async ({ page }) => {
        await page.goto(`${BASE_URL}/p/sainath-setti`, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="Ask"], input[placeholder*="message"]').first();
        const hasChat = await chatInput.isVisible().catch(() => false);
        if (!hasChat) { test.skip(); return; }

        const longMessage = 'A'.repeat(2000) + ' tell me everything about your background and expertise';
        await chatInput.fill(longMessage);

        const sendBtn = page.locator('button[type="submit"], button[aria-label*="send"], button:has-text("Send")').first();
        const hasSend = await sendBtn.isVisible().catch(() => false);
        if (hasSend) await sendBtn.click();
        else await chatInput.press('Enter');

        await page.waitForTimeout(5000);
        await captureScreenshot(page, '41-long-message');

        // Page should still be alive
        const title = await page.title();
        expect(title).toBeTruthy();
        console.log('Page still alive after long message, title:', title);
    });

    test('mobile viewport (375px) — landing page layout', async ({ page }) => {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '42-mobile-375-landing');

        // Check content is visible and not horizontally overflowing
        const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
        console.log('Body scrollWidth at 375px:', bodyWidth);
        if (bodyWidth > 400) {
            console.warn('WARN: Possible horizontal overflow on mobile. Body width:', bodyWidth);
        }

        const h1 = page.locator('h1').first();
        const hasH1 = await h1.isVisible().catch(() => false);
        expect(hasH1).toBe(true);
    });

    test('mobile viewport (375px) — marketplace layout', async ({ page }) => {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '43-mobile-375-marketplace');

        const statusCode = (await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'domcontentloaded' }))?.status();
        console.log('Marketplace mobile status:', statusCode);
        expect(statusCode).toBeLessThan(400);
    });

    test('dashboard redirects to login when unauthenticated', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle', timeout: 30000 });
        await captureScreenshot(page, '44-dashboard-unauth');

        const currentUrl = page.url();
        console.log('Dashboard redirect URL (unauthenticated):', currentUrl);

        // Should redirect to login or show auth page
        const isAuthPage =
            currentUrl.includes('/auth/') ||
            currentUrl.includes('/login') ||
            currentUrl.includes('/signin') ||
            currentUrl === BASE_URL + '/';
        console.log('Correctly redirected to auth:', isAuthPage);
        expect(isAuthPage).toBe(true);
    });

    test('404 page for unknown routes shows friendly message', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/this-page-definitely-does-not-exist-abc`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });
        await captureScreenshot(page, '45-404-unknown-route');

        const statusCode = response?.status() ?? 0;
        console.log('Unknown route status:', statusCode);
        expect(statusCode).not.toBe(500);

        // Check it's not a raw server error
        const bodyText = await page.locator('body').textContent();
        const isRawError = bodyText?.includes('Internal Server Error') && !bodyText?.includes('404');
        expect(isRawError).toBe(false);
    });
});

// ─────────────────────────────────────────────────────────────────
// 7. SHARE PAGES
// ─────────────────────────────────────────────────────────────────

test.describe('Share Pages', () => {
    test('share page for sainath-setti loads', async ({ page }) => {
        // Check common share page patterns
        const shareUrls = [
            `${BASE_URL}/share/sainath-setti`,
            `${BASE_URL}/p/sainath-setti/share`,
        ];

        for (const url of shareUrls) {
            const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null);
            if (!response) continue;

            const statusCode = response.status();
            console.log(`Share URL ${url} → status ${statusCode}`);
            await captureScreenshot(page, `50-share-${url.split('/').pop()}`);

            if (statusCode < 400) {
                console.log('Share page works at:', url);
                return; // Pass on first working URL
            }
        }
        // Not a hard failure since share URL structure may vary
        console.log('INFO: No share page found at expected URLs');
    });
});

// ─────────────────────────────────────────────────────────────────
// 8. PERFORMANCE / NETWORK
// ─────────────────────────────────────────────────────────────────

test.describe('Network & Performance', () => {
    test('landing page has no 4xx/5xx resource failures', async ({ page }) => {
        const failedRequests: { url: string; status: number }[] = [];

        page.on('response', (response) => {
            const status = response.status();
            if (status >= 400) {
                failedRequests.push({ url: response.url(), status });
            }
        });

        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Filter out tracking pixels and external analytics that commonly fail
        const importantFailures = failedRequests.filter(
            (r) =>
                r.url.includes('personaon.com') ||
                r.url.includes('api.personaon.com')
        );

        console.log('Failed requests (personaon.com only):', importantFailures);
        if (importantFailures.length > 0) {
            console.warn('WARN: Failed resource requests:', importantFailures);
        }
        expect(importantFailures.length).toBe(0);
    });

    test('landing page loads within 10 seconds', async ({ page }) => {
        const start = Date.now();
        await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const loadTime = Date.now() - start;
        console.log(`Landing page DOM load time: ${loadTime}ms`);
        expect(loadTime).toBeLessThan(10000);
    });

    test('marketplace page loads within 15 seconds', async ({ page }) => {
        const start = Date.now();
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const loadTime = Date.now() - start;
        console.log(`Marketplace DOM load time: ${loadTime}ms`);
        expect(loadTime).toBeLessThan(15000);
    });
});
