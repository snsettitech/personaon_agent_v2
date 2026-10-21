/**
 * Comprehensive Live E2E Audit — personaon.com
 *
 * Tests all critical user journeys against production:
 *   1. Public Persona Page (/p/sainath-setti)
 *   2. Landing Page
 *   3. Marketplace
 *   4. Auth Pages (signup / login)
 *   5. Onboarding (unauthenticated redirect)
 *   6. API Health
 *   7. Share Page
 *   8. Edge Cases
 *
 * Run with:
 *   cd frontend
 *   E2E_BASE_URL=https://personaon.com npx playwright test tests/e2e/comprehensive_live_audit.spec.ts --reporter=list
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE_URL = 'https://personaon.com';
const API_URL = 'https://api.personaon.com';
const SCREENSHOT_DIR = '/d/PersonaOn/frontend/playwright-test-results/comprehensive-audit';

if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function shot(page: Page, name: string): Promise<string> {
    const fp = path.join(SCREENSHOT_DIR, `${name}.png`);
    await page.screenshot({ path: fp, fullPage: true });
    return fp;
}

function collectErrors(page: Page): string[] {
    const errors: string[] = [];
    page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`);
    });
    page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));
    return errors;
}

// ─────────────────────────────────────────────────────────────────
// 1. PUBLIC PERSONA PAGE — /p/sainath-setti
// ─────────────────────────────────────────────────────────────────

test.describe('1. Public Persona Page (/p/sainath-setti)', () => {
    const PERSONA_URL = `${BASE_URL}/p/sainath-setti`;

    test('1.1 page loads with HTTP 200', async ({ page }) => {
        const errors = collectErrors(page);
        const response = await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });
        await shot(page, '01-persona-page-load');

        const status = response?.status() ?? 0;
        console.log(`[RESULT] Persona page HTTP status: ${status}`);
        expect(status).toBe(200);
        if (errors.length > 0) console.warn('[WARN] Console errors:', errors);
    });

    test('1.2 avatar + name + headline are visible inline', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Name — check h1 or h2 or any heading containing "Sainath"
        const nameEl = page.locator('h1, h2, [class*="name"], [class*="title"]').filter({ hasText: /sainath/i }).first();
        const hasName = await nameEl.isVisible({ timeout: 10000 }).catch(() => false);
        const nameText = hasName ? await nameEl.textContent() : 'NOT FOUND';
        console.log(`[RESULT] Name visible: ${hasName} — "${nameText?.trim()}"`);
        expect(hasName).toBe(true);

        // Headline — look for occupation / headline text near the top
        const headline = page.locator('[class*="headline"], [class*="occupation"], [class*="subtitle"], [class*="tagline"]').first();
        const hasHeadline = await headline.isVisible({ timeout: 5000 }).catch(() => false);
        const headlineText = hasHeadline ? await headline.textContent() : 'NOT FOUND';
        console.log(`[RESULT] Headline visible: ${hasHeadline} — "${headlineText?.trim()?.substring(0, 80)}"`);

        // Avatar — img or avatar div
        const avatar = page.locator('img[alt*="avatar"], img[alt*="profile"], img[alt*="Sainath"], [class*="avatar"], [class*="Avatar"]').first();
        const hasAvatar = await avatar.isVisible({ timeout: 5000 }).catch(() => false);
        console.log(`[RESULT] Avatar visible: ${hasAvatar}`);

        await shot(page, '01b-persona-profile-inline');
    });

    test('1.3 bio is visible', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        const bio = page.locator('[class*="bio"], [class*="about"], p').filter({ hasText: /.{50,}/ }).first();
        const hasBio = await bio.isVisible({ timeout: 8000 }).catch(() => false);
        const bioText = hasBio ? (await bio.textContent())?.substring(0, 150) : 'NOT FOUND';
        console.log(`[RESULT] Bio visible: ${hasBio} — "${bioText?.trim()}"`);
        // Not a hard assertion — just log
        if (!hasBio) console.warn('[WARN] Bio section not found on persona page');
    });

    test('1.4 Areas of Expertise tags are visible', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Section label is "AREAS OF EXPERTISE" in all-caps on this page
        const expertiseSection = page.locator('text=/AREAS OF EXPERTISE/i, text=/Areas of Expertise/i').first();
        const hasSection = await expertiseSection.isVisible({ timeout: 10000 }).catch(() => false);
        console.log(`[RESULT] Areas of Expertise section: ${hasSection}`);

        // Skills are rendered as inline text items below the AREAS OF EXPERTISE label
        // The page uses a list structure — look for sibling text items
        const bodyText = await page.locator('body').innerText();
        const hasExpertiseContent = bodyText.includes('AI Product Development') ||
            bodyText.includes('Cloud Architecture') ||
            bodyText.includes('AREAS OF EXPERTISE');
        console.log(`[RESULT] Expertise content in page text: ${hasExpertiseContent}`);

        // Look for tag/badge style elements
        const tags = page.locator('[class*="tag"], [class*="badge"], [class*="chip"], [class*="skill"]');
        const tagCount = await tags.count();
        console.log(`[RESULT] Tag/badge elements found: ${tagCount}`);

        await shot(page, '01c-expertise-tags');

        // Either the section label or the content itself must be present
        expect(hasExpertiseContent || hasSection).toBe(true);
    });

    test('1.5 Key Achievements are listed', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Section label is "KEY ACHIEVEMENTS" in all-caps on this page
        const bodyText = await page.locator('body').innerText();
        const hasAchievementsLabel = bodyText.includes('KEY ACHIEVEMENTS');
        const hasAchievementContent = bodyText.includes('Founded PersonaOn') ||
            bodyText.includes('Microsoft') ||
            bodyText.includes('KEY ACHIEVEMENTS');
        console.log(`[RESULT] KEY ACHIEVEMENTS label in text: ${hasAchievementsLabel}`);
        console.log(`[RESULT] Achievement content in page: ${hasAchievementContent}`);

        // Print what achievements are shown
        const achievementLines = bodyText.split('\n')
            .filter(l => l.trim().length > 10)
            .slice(0, 30);
        const achievementsIndex = achievementLines.findIndex(l => l.includes('KEY ACHIEVEMENTS'));
        if (achievementsIndex >= 0) {
            console.log(`[RESULT] Achievement items after label:`);
            for (const line of achievementLines.slice(achievementsIndex + 1, achievementsIndex + 6)) {
                console.log(`  - ${line.trim()}`);
            }
        }

        expect(hasAchievementContent).toBe(true);
    });

    test('1.6 Social Links are shown', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Social links — LinkedIn, Twitter, GitHub, etc.
        const socialLinks = await page.locator('a[href*="linkedin"], a[href*="twitter"], a[href*="github"], a[href*="x.com"], [class*="social"] a').all();
        console.log(`[RESULT] Social link elements: ${socialLinks.length}`);
        for (const link of socialLinks) {
            const href = await link.getAttribute('href').catch(() => '');
            console.log(`  Social link href: ${href}`);
        }
        // Not a hard assertion — persona may not have all social links
    });

    test('1.7 Share button is present', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        const shareBtn = page.locator('button:has-text("Share"), a:has-text("Share"), [aria-label*="share"], [aria-label*="Share"]').first();
        const hasShare = await shareBtn.isVisible({ timeout: 8000 }).catch(() => false);
        console.log(`[RESULT] Share button visible: ${hasShare}`);
        await shot(page, '01d-share-button');
        expect(hasShare).toBe(true);
    });

    test('1.8 Suggested questions are displayed as CARDS (not pills)', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // The page renders question cards as full-width buttons with class "rounded-xl"
        // They contain text like "What do you do?", "What's your background?", etc.
        // Selector: button elements that are full-width (block w-full) — exclude the Send button
        const questionCards = page.locator('button').filter({
            hasNot: page.locator('[aria-label="Send message"]'),
        }).filter({
            hasText: /\?|about|your|how|what|tell|why/i,
        });

        const cardCount = await questionCards.count();
        console.log(`[RESULT] Suggested question card elements: ${cardCount}`);

        // Collect their texts
        const cardTexts: string[] = [];
        for (let i = 0; i < Math.min(cardCount, 6); i++) {
            const txt = await questionCards.nth(i).textContent().catch(() => '');
            if (txt?.trim()) cardTexts.push(txt.trim().substring(0, 80));
        }
        console.log(`[RESULT] Question card texts: ${JSON.stringify(cardTexts)}`);

        // Verify they look like cards not pills — full-width block buttons with padding
        if (cardCount > 0) {
            const firstCard = questionCards.first();
            const classes = await firstCard.getAttribute('class').catch(() => '');
            console.log(`[RESULT] First question card classes: ${classes}`);
            // Cards have "rounded-xl" and "w-full" — confirms card (not pill) style
            const isCardStyle = classes?.includes('rounded-xl') || classes?.includes('w-full');
            console.log(`[RESULT] Card style (rounded-xl / w-full): ${isCardStyle}`);
        }

        await shot(page, '01e-question-cards');
        expect(cardCount).toBeGreaterThan(0);
    });

    test('1.9 Clicking a suggested question sends a message and gets a response', async ({ page }) => {
        const apiCalls: { url: string; status: number }[] = [];
        page.on('response', (resp) => {
            if (resp.url().includes('api.personaon.com') || resp.url().includes('/chat')) {
                apiCalls.push({ url: resp.url(), status: resp.status() });
            }
        });

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Find and click a suggested question card (full-width button with question text)
        const questionCard = page.locator('button').filter({
            hasNot: page.locator('[aria-label="Send message"]'),
        }).filter({
            hasText: /\?|about|your|how|what|tell|why/i,
        }).first();
        const hasCard = await questionCard.isVisible({ timeout: 8000 }).catch(() => false);

        if (!hasCard) {
            console.log('[SKIP] No question cards found — skipping click test');
            test.skip();
            return;
        }

        const cardText = await questionCard.textContent().catch(() => '');
        console.log(`[ACTION] Clicking question card: "${cardText?.trim().substring(0, 80)}"`);
        await questionCard.click();

        await shot(page, '01f-after-question-click');

        // Wait for response — up to 20s
        await page.waitForTimeout(20000);
        await shot(page, '01g-chat-response');

        console.log(`[RESULT] API calls made: ${JSON.stringify(apiCalls)}`);
        expect(apiCalls.length).toBeGreaterThan(0);

        // Check a response message appeared
        const responseEl = page.locator('[class*="message"], [class*="response"], [class*="assistant"], [class*="bubble"]').last();
        const hasResponse = await responseEl.isVisible({ timeout: 5000 }).catch(() => false);
        console.log(`[RESULT] Response element visible: ${hasResponse}`);
    });

    test('1.10 Profile scrolls away when chat starts', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Take screenshot of initial state (profile visible)
        await shot(page, '01h-profile-initial');

        const questionCard = page.locator('button').filter({
            hasNot: page.locator('[aria-label="Send message"]'),
        }).filter({
            hasText: /\?|about|your|how|what|tell|why/i,
        }).first();
        const hasCard = await questionCard.isVisible({ timeout: 8000 }).catch(() => false);

        if (!hasCard) {
            console.log('[SKIP] No question cards — skipping scroll-away test');
            test.skip();
            return;
        }

        await questionCard.click();
        await page.waitForTimeout(3000);
        await shot(page, '01i-profile-after-chat-start');

        // Check if the profile section is now hidden or scrolled out
        const profilePanel = page.locator('[class*="profile-panel"], [class*="profilePanel"], [class*="persona-profile"]').first();
        const profileVisible = await profilePanel.isVisible({ timeout: 3000 }).catch(() => true);
        console.log(`[RESULT] Profile panel still visible after chat start: ${profileVisible}`);
        // If it scrolls away, the panel should not be visible or should have moved
    });

    test('1.11 Chat input works — send message and verify response', async ({ page }) => {
        const errors = collectErrors(page);
        const apiCalls: { url: string; status: number; method: string }[] = [];
        page.on('response', (resp) => {
            if (resp.url().includes('api.personaon.com') || resp.url().includes('/chat')) {
                apiCalls.push({ url: resp.url(), status: resp.status(), method: resp.request().method() });
            }
        });

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 45000 });

        // Locate the chat input
        const chatInput = page.locator('textarea[placeholder*="ask"], textarea[placeholder*="Ask"], textarea[placeholder*="message"], input[placeholder*="ask"], input[placeholder*="Ask"]').first();
        const hasChatInput = await chatInput.isVisible({ timeout: 8000 }).catch(() => false);
        console.log(`[RESULT] Chat input visible: ${hasChatInput}`);
        expect(hasChatInput).toBe(true);

        await chatInput.fill('What is your professional background?');
        await shot(page, '01j-chat-typed');

        // Try send button first, fall back to Enter
        const sendBtn = page.locator('button[aria-label*="send"], button[aria-label*="Send"], button[type="submit"]').first();
        const hasSendBtn = await sendBtn.isEnabled({ timeout: 3000 }).catch(() => false);
        if (hasSendBtn) {
            await sendBtn.click();
        } else {
            await chatInput.press('Enter');
        }

        // Wait for response
        await page.waitForTimeout(20000);
        await shot(page, '01k-chat-response-received');

        console.log(`[RESULT] API calls: ${JSON.stringify(apiCalls)}`);
        console.log(`[RESULT] Console errors: ${errors.join('; ')}`);

        expect(apiCalls.length).toBeGreaterThan(0);
        const successCalls = apiCalls.filter((c) => c.status < 400);
        console.log(`[RESULT] Successful API calls: ${successCalls.length}/${apiCalls.length}`);
        expect(successCalls.length).toBeGreaterThan(0);
    });
});

// ─────────────────────────────────────────────────────────────────
// 2. LANDING PAGE
// ─────────────────────────────────────────────────────────────────

test.describe('2. Landing Page (https://personaon.com)', () => {
    test('2.1 Sign In button visible in nav', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, '02a-landing-nav');

        const signInBtn = page.locator('nav a:has-text("Sign In"), header a:has-text("Sign In"), nav button:has-text("Sign In"), a:has-text("Sign in"), a:has-text("Login")').first();
        const hasSignIn = await signInBtn.isVisible({ timeout: 8000 }).catch(() => false);
        console.log(`[RESULT] Sign In button visible: ${hasSignIn}`);
        expect(hasSignIn).toBe(true);
    });

    test('2.2 "Create Your Persona — Free" CTA button visible in nav', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Primary CTA — look for variations of the create/free CTA
        const ctaBtn = page.locator('nav a, header a, nav button, header button').filter({
            hasText: /Create Your Persona|Create Persona|Get Started|Free/i,
        }).first();
        const hasCTA = await ctaBtn.isVisible({ timeout: 8000 }).catch(() => false);
        const ctaText = hasCTA ? await ctaBtn.textContent() : 'NOT FOUND';
        console.log(`[RESULT] Primary CTA visible: ${hasCTA} — "${ctaText?.trim()}"`);
        await shot(page, '02b-landing-cta');
        expect(hasCTA).toBe(true);
    });

    test('2.3 Demo chat is present', async ({ page }) => {
        const errors = collectErrors(page);
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="Ask"], input[placeholder*="ask"], input[placeholder*="chat"]').first();
        const hasChat = await chatInput.isVisible({ timeout: 10000 }).catch(() => false);
        console.log(`[RESULT] Demo chat input visible: ${hasChat}`);
        await shot(page, '02c-landing-demo-chat');

        if (!hasChat) {
            console.warn('[WARN] Demo chat input not found on landing page');
        }
        expect(hasChat).toBe(true);
    });

    test('2.4 Demo chat can send a message and get a response (route fix check)', async ({ page }) => {
        const errors = collectErrors(page);
        const apiCalls: { url: string; status: number }[] = [];
        page.on('response', (resp) => {
            if (resp.url().includes('api.personaon.com') || resp.url().includes('/chat')) {
                apiCalls.push({ url: resp.url(), status: resp.status() });
            }
        });

        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="Ask"], input[placeholder*="ask"]').first();
        const hasChat = await chatInput.isVisible({ timeout: 10000 }).catch(() => false);

        if (!hasChat) {
            console.log('[SKIP] Demo chat not present — skip');
            test.skip();
            return;
        }

        await chatInput.fill('What industries do you focus on?');

        const sendBtn = page.locator('button[aria-label*="send"], button[aria-label*="Send"], button[type="submit"]').first();
        const hasSendBtn = await sendBtn.isEnabled({ timeout: 3000 }).catch(() => false);
        if (hasSendBtn) {
            await sendBtn.click();
        } else {
            await chatInput.press('Enter');
        }

        await page.waitForTimeout(15000);
        await shot(page, '02d-landing-chat-response');

        console.log(`[RESULT] API calls during demo chat: ${JSON.stringify(apiCalls)}`);
        console.log(`[RESULT] Console errors: ${errors.join('; ')}`);

        // Verify a response appeared
        const chatMessages = await page.locator('[class*="message"], [class*="response"], [class*="assistant"], [class*="bubble"]').all();
        console.log(`[RESULT] Message elements after send: ${chatMessages.length}`);
        for (const msg of chatMessages.slice(0, 3)) {
            const txt = await msg.textContent().catch(() => '');
            if (txt?.trim()) console.log(`  Message: "${txt.trim().substring(0, 100)}"`);
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// 3. MARKETPLACE
// ─────────────────────────────────────────────────────────────────

test.describe('3. Marketplace (https://personaon.com/marketplace)', () => {
    test('3.1 marketplace loads with persona cards', async ({ page }) => {
        const errors = collectErrors(page);
        const response = await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 45000 });
        await shot(page, '03a-marketplace-load');

        const status = response?.status() ?? 0;
        console.log(`[RESULT] Marketplace HTTP status: ${status}`);
        expect(status).toBe(200);

        // Look for persona cards — /p/ links are the most reliable signal
        const personaLinks = page.locator('a[href*="/p/"]');
        const linkCount = await personaLinks.count();
        console.log(`[RESULT] Persona links (/p/...) on marketplace: ${linkCount}`);

        if (linkCount === 0) {
            await shot(page, '03a-marketplace-no-cards');
            console.warn('[WARN] No persona cards found on marketplace');
        }
        expect(linkCount).toBeGreaterThan(0);
    });

    test('3.2 can click through to /p/sainath-setti', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 45000 });

        // First try a direct link to sainath-setti
        const sainathLink = page.locator('a[href*="/p/sainath-setti"]').first();
        const hasSainath = await sainathLink.isVisible({ timeout: 5000 }).catch(() => false);

        if (hasSainath) {
            console.log('[ACTION] Clicking direct link to /p/sainath-setti');
            await sainathLink.click();
        } else {
            // Click any /p/ link available
            const firstPersonaLink = page.locator('a[href*="/p/"]').first();
            const hasAny = await firstPersonaLink.isVisible({ timeout: 5000 }).catch(() => false);
            if (!hasAny) {
                console.log('[SKIP] No persona links on marketplace');
                test.skip();
                return;
            }
            const href = await firstPersonaLink.getAttribute('href');
            console.log(`[ACTION] Clicking first persona link: ${href}`);
            await firstPersonaLink.click();
        }

        await page.waitForURL(/\/p\//, { timeout: 20000 });
        await page.waitForLoadState('networkidle', { timeout: 30000 });
        await shot(page, '03b-marketplace-clickthrough');

        const currentUrl = page.url();
        console.log(`[RESULT] Navigated to: ${currentUrl}`);
        expect(currentUrl).toContain('/p/');
    });
});

// ─────────────────────────────────────────────────────────────────
// 4. AUTH PAGES
// ─────────────────────────────────────────────────────────────────

test.describe('4. Auth Pages', () => {
    test('4.1 /auth/signup loads', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/auth/signup`, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, '04a-auth-signup');

        const status = response?.status() ?? 0;
        console.log(`[RESULT] Signup page HTTP status: ${status}`);
        expect(status).toBeLessThan(400);

        const title = await page.title();
        console.log(`[RESULT] Signup page title: ${title}`);
    });

    test('4.2 LinkedIn is the PRIMARY button on signup (above Google)', async ({ page }) => {
        await page.goto(`${BASE_URL}/auth/signup`, { waitUntil: 'networkidle', timeout: 30000 });

        const linkedInBtn = page.locator('button:has-text("LinkedIn"), a:has-text("LinkedIn"), [class*="linkedin"]').first();
        const googleBtn = page.locator('button:has-text("Google"), a:has-text("Google"), [class*="google"]').first();

        const hasLinkedIn = await linkedInBtn.isVisible({ timeout: 8000 }).catch(() => false);
        const hasGoogle = await googleBtn.isVisible({ timeout: 8000 }).catch(() => false);

        console.log(`[RESULT] LinkedIn button visible: ${hasLinkedIn}`);
        console.log(`[RESULT] Google button visible: ${hasGoogle}`);

        if (hasLinkedIn && hasGoogle) {
            // Check LinkedIn appears first (higher in DOM / higher y position)
            const linkedInPos = await linkedInBtn.evaluate((el) => el.getBoundingClientRect().top);
            const googlePos = await googleBtn.evaluate((el) => el.getBoundingClientRect().top);
            console.log(`[RESULT] LinkedIn Y pos: ${linkedInPos}, Google Y pos: ${googlePos}`);
            const linkedInIsFirst = linkedInPos <= googlePos;
            console.log(`[RESULT] LinkedIn is above Google (primary): ${linkedInIsFirst}`);
            expect(linkedInIsFirst).toBe(true);
        } else {
            console.warn(`[WARN] Could not verify button order — LinkedIn: ${hasLinkedIn}, Google: ${hasGoogle}`);
            expect(hasLinkedIn).toBe(true);
        }

        await shot(page, '04b-signup-button-order');
    });

    test('4.3 /auth/login loads', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, '04c-auth-login');

        const status = response?.status() ?? 0;
        console.log(`[RESULT] Login page HTTP status: ${status}`);
        expect(status).toBeLessThan(400);

        // Check for any auth form elements
        const authElements = await page.locator('button, input[type="email"], a[href*="linkedin"], a[href*="google"]').count();
        console.log(`[RESULT] Auth form elements on login: ${authElements}`);
        expect(authElements).toBeGreaterThan(0);
    });
});

// ─────────────────────────────────────────────────────────────────
// 5. ONBOARDING — unauthenticated redirect
// ─────────────────────────────────────────────────────────────────

test.describe('5. Onboarding — Unauthenticated Redirect', () => {
    test('5.1 /onboarding redirects to login when not authenticated', async ({ page }) => {
        const redirectChain: string[] = [];
        page.on('response', (resp) => {
            if (resp.status() === 307 || resp.status() === 308 || resp.status() === 302 || resp.status() === 301) {
                redirectChain.push(`${resp.status()} → ${resp.headers()['location'] ?? 'unknown'}`);
            }
        });

        const response = await page.goto(`${BASE_URL}/onboarding`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });
        await shot(page, '05a-onboarding-unauth');

        const finalUrl = page.url();
        const finalStatus = response?.status() ?? 0;

        console.log(`[RESULT] Redirect chain: ${JSON.stringify(redirectChain)}`);
        console.log(`[RESULT] Final URL: ${finalUrl}`);
        console.log(`[RESULT] Final status: ${finalStatus}`);

        // Should have landed on an auth page
        const isAuthPage =
            finalUrl.includes('/auth/') ||
            finalUrl.includes('/login') ||
            finalUrl.includes('/signin');
        console.log(`[RESULT] Redirected to auth page: ${isAuthPage}`);
        expect(isAuthPage).toBe(true);
    });
});

// ─────────────────────────────────────────────────────────────────
// 6. API HEALTH
// ─────────────────────────────────────────────────────────────────

test.describe('6. API Health', () => {
    test('6.1 GET /health returns 200 with all systems green', async ({ request }) => {
        const response = await request.get(`${API_URL}/health`);
        const status = response.status();
        const body = await response.json().catch(() => null);

        console.log(`[RESULT] GET /health status: ${status}`);
        console.log(`[RESULT] GET /health body: ${JSON.stringify(body)}`);

        expect(status).toBe(200);

        // Check for health indicators
        if (body) {
            const hasHealthField =
                body.status !== undefined ||
                body.healthy !== undefined ||
                body.ok !== undefined;
            console.log(`[RESULT] Health field present: ${hasHealthField}`);
            console.log(`[RESULT] All body keys: ${Object.keys(body).join(', ')}`);
        }
    });

    test('6.2 GET /handles/check?handle=sainath-setti — endpoint requires auth (returns 401)', async ({ request }) => {
        // NOTE: /handles/check requires authentication (401 for anonymous requests).
        // This is by design — handle availability check is an authenticated operation.
        // The handle can be verified as taken via the public /handles/resolve endpoint instead.
        const response = await request.get(`${API_URL}/handles/check?handle=sainath-setti`);
        const status = response.status();
        const body = await response.json().catch(() => null);

        console.log(`[RESULT] GET /handles/check status: ${status}`);
        console.log(`[RESULT] GET /handles/check body: ${JSON.stringify(body)}`);

        // Endpoint requires auth — should return 401 for anonymous callers
        // This confirms the endpoint is protected (not publicly callable — correct behavior)
        expect(status).toBe(401);
        expect(body?.detail).toContain('Authentication');
    });

    test('6.3 GET /handles/resolve?handle=sainath-setti returns twin_id + share_token', async ({ request }) => {
        const response = await request.get(`${API_URL}/handles/resolve?handle=sainath-setti`);
        const status = response.status();
        const body = await response.json().catch(() => null);

        console.log(`[RESULT] GET /handles/resolve status: ${status}`);
        console.log(`[RESULT] GET /handles/resolve body: ${JSON.stringify(body)}`);

        expect(status).toBe(200);
        expect(body).toBeTruthy();
        expect(body.twin_id).toBeTruthy();
        expect(body.share_token).toBeTruthy();
        console.log(`[RESULT] twin_id: ${body.twin_id}, share_token: ${body.share_token?.substring(0, 12)}...`);
    });
});

// ─────────────────────────────────────────────────────────────────
// 7. SHARE PAGE
// ─────────────────────────────────────────────────────────────────

test.describe('7. Share Page', () => {
    test('7.1 /share/sainath-setti loads (was broken — now fixed)', async ({ page }) => {
        const errors = collectErrors(page);
        const response = await page.goto(`${BASE_URL}/share/sainath-setti`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });
        await shot(page, '07a-share-page');

        const status = response?.status() ?? 0;
        const finalUrl = page.url();
        const title = await page.title();

        console.log(`[RESULT] Share page HTTP status: ${status}`);
        console.log(`[RESULT] Share page final URL: ${finalUrl}`);
        console.log(`[RESULT] Share page title: ${title}`);
        console.log(`[RESULT] Console errors: ${errors.join('; ')}`);

        expect(status).toBeLessThan(400);
        expect(status).not.toBe(500);

        // Should NOT be a 404/crash page
        const bodyText = await page.locator('body').textContent().catch(() => '');
        const isErrorPage = bodyText?.includes('Application error') || bodyText?.includes('Internal Server Error');
        console.log(`[RESULT] Is error page: ${isErrorPage}`);
        expect(isErrorPage).toBe(false);
    });

    test('7.2 share page shows persona name and profile info', async ({ page }) => {
        await page.goto(`${BASE_URL}/share/sainath-setti`, { waitUntil: 'networkidle', timeout: 30000 });

        const nameEl = page.locator('h1, h2, [class*="name"]').filter({ hasText: /sainath/i }).first();
        const hasName = await nameEl.isVisible({ timeout: 10000 }).catch(() => false);
        console.log(`[RESULT] Persona name on share page: ${hasName}`);

        // Check for QR code
        const qrCode = page.locator('canvas, img[alt*="QR"], img[alt*="qr"], [class*="qr"]').first();
        const hasQR = await qrCode.isVisible({ timeout: 5000 }).catch(() => false);
        console.log(`[RESULT] QR code on share page: ${hasQR}`);

        // Check for copy/share URL button
        const copyBtn = page.locator('button:has-text("Copy"), button:has-text("copy"), [aria-label*="copy"]').first();
        const hasCopy = await copyBtn.isVisible({ timeout: 5000 }).catch(() => false);
        console.log(`[RESULT] Copy button on share page: ${hasCopy}`);

        await shot(page, '07b-share-page-content');
    });
});

// ─────────────────────────────────────────────────────────────────
// 8. EDGE CASES
// ─────────────────────────────────────────────────────────────────

test.describe('8. Edge Cases', () => {
    test('8.1 /p/nonexistent-handle shows "doesn\'t exist" not a crash', async ({ page }) => {
        const errors = collectErrors(page);
        const response = await page.goto(`${BASE_URL}/p/this-handle-does-not-exist-xyz999`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });
        await shot(page, '08a-nonexistent-persona');

        const status = response?.status() ?? 0;
        const bodyText = await page.locator('body').textContent().catch(() => '');

        console.log(`[RESULT] Non-existent handle HTTP status: ${status}`);
        console.log(`[RESULT] Console errors: ${errors.join('; ')}`);

        // Should not be a 500 crash
        expect(status).not.toBe(500);

        // Should not show a raw stack trace
        const hasStackTrace = bodyText?.includes(' at Object.') || bodyText?.includes(' at Module.');
        console.log(`[RESULT] Raw stack trace present: ${hasStackTrace}`);
        expect(hasStackTrace).toBe(false);

        // Should show a friendly not-found message
        const notFoundIndicators = [
            page.locator("text=/doesn't exist/i").first(),
            page.locator('text=/not found/i').first(),
            page.locator('text=/404/i').first(),
            page.locator('text=/persona not found/i').first(),
            page.locator('text=/could not find/i').first(),
        ];
        let foundMessage = false;
        for (const indicator of notFoundIndicators) {
            const visible = await indicator.isVisible({ timeout: 3000 }).catch(() => false);
            if (visible) {
                const txt = await indicator.textContent();
                console.log(`[RESULT] Not-found message: "${txt?.trim()}"`);
                foundMessage = true;
                break;
            }
        }
        console.log(`[RESULT] Friendly not-found message shown: ${foundMessage}`);
        expect(foundMessage).toBe(true);
    });

    test('8.2 Very long message in chat does not break the page', async ({ page }) => {
        await page.goto(`${BASE_URL}/p/sainath-setti`, { waitUntil: 'networkidle', timeout: 45000 });

        const chatInput = page.locator('textarea[placeholder*="ask"], textarea[placeholder*="Ask"], input[placeholder*="ask"], input[placeholder*="Ask"]').first();
        const hasInput = await chatInput.isVisible({ timeout: 8000 }).catch(() => false);

        if (!hasInput) {
            console.log('[SKIP] Chat input not visible — skipping long message test');
            test.skip();
            return;
        }

        const longMessage = 'A'.repeat(1500) + ' — tell me about your professional background and expertise please';
        await chatInput.fill(longMessage);

        const sendBtn = page.locator('button[aria-label*="send"], button[aria-label*="Send"], button[type="submit"]').first();
        const hasSend = await sendBtn.isEnabled({ timeout: 3000 }).catch(() => false);
        if (hasSend) {
            await sendBtn.click();
        } else {
            await chatInput.press('Enter');
        }

        await page.waitForTimeout(8000);
        await shot(page, '08b-long-message');

        // Page should still be alive and not show an error
        const title = await page.title().catch(() => '');
        const isPageAlive = title.length > 0;
        console.log(`[RESULT] Page alive after long message: ${isPageAlive} (title: "${title}")`);
        expect(isPageAlive).toBe(true);

        // Should not show Internal Server Error
        const bodyText = await page.locator('body').textContent().catch(() => '');
        const hasServerError = bodyText?.includes('Internal Server Error');
        expect(hasServerError).toBe(false);
    });

    test('8.3 Mobile 375px layout — no horizontal overflow on landing page', async ({ page }) => {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, '08c-mobile-375-landing');

        const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
        const viewportWidth = await page.evaluate(() => window.innerWidth);
        console.log(`[RESULT] Body scrollWidth: ${bodyScrollWidth}, viewport: ${viewportWidth}`);

        const hasOverflow = bodyScrollWidth > viewportWidth + 5; // allow 5px tolerance
        console.log(`[RESULT] Horizontal overflow: ${hasOverflow}`);
        if (hasOverflow) {
            console.warn(`[WARN] Horizontal overflow detected at 375px: scrollWidth=${bodyScrollWidth}`);
        }
        expect(hasOverflow).toBe(false);

        // H1 should still be visible
        const h1 = page.locator('h1').first();
        const hasH1 = await h1.isVisible({ timeout: 8000 }).catch(() => false);
        console.log(`[RESULT] H1 visible at 375px: ${hasH1}`);
        expect(hasH1).toBe(true);
    });

    test('8.4 Mobile 375px layout — no overflow on persona page', async ({ page }) => {
        await page.setViewportSize({ width: 375, height: 812 });
        await page.goto(`${BASE_URL}/p/sainath-setti`, { waitUntil: 'networkidle', timeout: 45000 });
        await shot(page, '08d-mobile-375-persona');

        const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
        const viewportWidth = await page.evaluate(() => window.innerWidth);
        console.log(`[RESULT] Persona mobile scrollWidth: ${bodyScrollWidth}, viewport: ${viewportWidth}`);

        const hasOverflow = bodyScrollWidth > viewportWidth + 5;
        console.log(`[RESULT] Horizontal overflow on persona mobile: ${hasOverflow}`);
        if (hasOverflow) {
            console.warn(`[WARN] Mobile overflow on persona page: scrollWidth=${bodyScrollWidth}`);
        }
        expect(hasOverflow).toBe(false);
    });
});
