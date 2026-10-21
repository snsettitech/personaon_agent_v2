/**
 * Deep-dive investigations on specific issues found in live_site_audit.spec.ts
 * Focus: waitlist form, chat response detection, persona page avatar, persona chat
 */

import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE_URL = 'https://personaon.com';
const SCREENSHOT_DIR = '/d/PersonaOn/frontend/playwright-test-results/deep-dive';

if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function shot(page: Page, name: string) {
    const fp = path.join(SCREENSHOT_DIR, `${name}.png`);
    await page.screenshot({ path: fp, fullPage: true });
    return fp;
}

// ─────────────────────────────────────────────────────────────────
// ISSUE 1: Waitlist form — "Join the Waitlist" button is distinct
// from the demo chat submit button. The form needs full name + email + role.
// ─────────────────────────────────────────────────────────────────

test.describe('Waitlist Form (Full)', () => {
    test('submit waitlist form with all fields', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Scroll to waitlist section
        await page.locator('#waitlist, [id="waitlist"]').first().scrollIntoViewIfNeeded().catch(() => {
            // Fallback: scroll to bottom
        });

        // Fill full name
        const nameInput = page.locator('input[placeholder*="name"], input[placeholder*="Name"], textbox[name*="name"]').first();
        const hasName = await nameInput.isVisible().catch(() => false);
        console.log('Name input visible:', hasName);

        // Use the identified refs from the snapshot:
        // textbox "Full name" [ref=e258]
        // textbox "Email address" [ref=e259]
        // textbox "Your role..." [ref=e260]
        // button "Join the Waitlist" [ref=e261]

        const fullNameInput = page.getByPlaceholder('Full name').or(page.locator('input[placeholder*="Full name"]')).first();
        const emailInput = page.getByPlaceholder('Email address').or(page.locator('input[type="email"]')).first();
        const roleInput = page.getByPlaceholder('Your role').or(page.locator('input[placeholder*="role"]')).first();
        const joinBtn = page.getByRole('button', { name: 'Join the Waitlist' }).first();

        const hasFullName = await fullNameInput.isVisible().catch(() => false);
        const hasEmail = await emailInput.isVisible().catch(() => false);
        const hasRole = await roleInput.isVisible().catch(() => false);
        const hasJoinBtn = await joinBtn.isVisible().catch(() => false);

        console.log('Full name visible:', hasFullName);
        console.log('Email visible:', hasEmail);
        console.log('Role visible:', hasRole);
        console.log('Join Waitlist button visible:', hasJoinBtn);

        if (!hasFullName) {
            // Scroll down to reach the waitlist section
            await page.evaluate(() => {
                const el = document.querySelector('[id*="waitlist"], section:last-of-type');
                if (el) el.scrollIntoView({ behavior: 'smooth' });
            });
            await page.waitForTimeout(1000);
            await shot(page, 'waitlist-scroll');
        }

        // Fill the form
        await fullNameInput.fill('E2E Test User').catch(() => console.log('Could not fill full name'));
        await emailInput.fill('e2e-test@test-domain-e2e.com').catch(() => console.log('Could not fill email'));
        await roleInput.fill('QA Engineer').catch(() => console.log('Could not fill role'));

        await shot(page, 'waitlist-filled-all-fields');

        // Click the actual "Join the Waitlist" button (not the chat send button)
        const joinWaitlistBtn = page.getByRole('button', { name: 'Join the Waitlist' }).first();
        const canClick = await joinWaitlistBtn.isEnabled().catch(() => false);
        console.log('Join Waitlist button enabled:', canClick);

        if (canClick) {
            // Track the API request
            const [response] = await Promise.all([
                page.waitForResponse(
                    (resp) => resp.url().includes('/waitlist') || resp.url().includes('api.personaon.com'),
                    { timeout: 10000 }
                ).catch(() => null),
                joinWaitlistBtn.click(),
            ]);

            await page.waitForTimeout(3000);
            await shot(page, 'waitlist-submitted');

            if (response) {
                console.log('Waitlist API response status:', response.status());
                const body = await response.json().catch(() => null);
                console.log('Waitlist API response body:', JSON.stringify(body));
            } else {
                console.log('No API response intercepted for waitlist submission');
            }

            // Check for success/thank you message
            const successIndicators = [
                page.locator('text=/thank/i').first(),
                page.locator('text=/success/i').first(),
                page.locator('text=/joined/i').first(),
                page.locator('text=/check your email/i').first(),
                page.locator('text=/waitlist/i').first(),
                page.locator('[class*="success"]').first(),
            ];

            let foundSuccess = false;
            for (const indicator of successIndicators) {
                const visible = await indicator.isVisible({ timeout: 2000 }).catch(() => false);
                if (visible) {
                    const text = await indicator.textContent();
                    console.log('SUCCESS indicator found:', text?.trim());
                    foundSuccess = true;
                    break;
                }
            }
            console.log('Waitlist submission success UI visible:', foundSuccess);
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 2: Landing page demo chat — verify actual response arrives
// ─────────────────────────────────────────────────────────────────

test.describe('Landing Page Demo Chat (Detailed)', () => {
    test('demo chat shows a response from Alex Rivera', async ({ page }) => {
        const consoleErrors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') consoleErrors.push(msg.text());
        });

        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, 'chat-before-message');

        // The chat is for "Alex Rivera" persona with placeholder "Ask Alex anything..."
        const chatInput = page.getByPlaceholder('Ask Alex anything...').or(
            page.locator('input[placeholder*="Ask"], textarea[placeholder*="Ask"]')
        ).first();

        const hasInput = await chatInput.isVisible().catch(() => false);
        console.log('Demo chat input visible:', hasInput);

        if (!hasInput) {
            console.log('FAIL: Demo chat input not found');
            expect(hasInput).toBe(true);
            return;
        }

        await chatInput.fill('What industries do you focus on?');

        // The send button — should become enabled after typing
        const sendBtn = page.locator('button[aria-label="Send message"]').first();
        await sendBtn.waitFor({ state: 'attached', timeout: 5000 }).catch(() => null);

        const isEnabled = await sendBtn.isEnabled().catch(() => false);
        console.log('Send button enabled after typing:', isEnabled);
        await shot(page, 'chat-typed-message');

        if (isEnabled) {
            await sendBtn.click();
        } else {
            // Try pressing Enter
            await chatInput.press('Enter');
        }

        // Wait for SSE/streaming response — up to 15 seconds
        await page.waitForTimeout(12000);
        await shot(page, 'chat-after-response');

        // Look for a response bubble that appeared
        const messages = await page.locator('[class*="message"], [class*="chat-bubble"], [class*="response"]').all();
        console.log('Message elements found after chat:', messages.length);

        for (const msg of messages) {
            const text = await msg.textContent().catch(() => '');
            if (text && text.length > 10) {
                console.log('Message content:', text.substring(0, 200));
            }
        }

        console.log('Console errors during chat:', consoleErrors);
    });

    test('demo chat starter suggestions are visible and clickable', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Look for conversation starters or suggestion chips
        const starters = page.locator('[class*="starter"], [class*="suggestion"], [class*="chip"], button:has-text("Ask")');
        const count = await starters.count();
        console.log('Conversation starters found:', count);

        if (count > 0) {
            const firstStarter = starters.first();
            const text = await firstStarter.textContent();
            console.log('First starter text:', text?.trim());
            await firstStarter.click();
            await page.waitForTimeout(2000);
            await shot(page, 'chat-starter-clicked');
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 3: Persona page /p/sainath-setti — missing avatar
// ─────────────────────────────────────────────────────────────────

test.describe('Persona Page — Avatar & Profile', () => {
    const PERSONA_URL = `${BASE_URL}/p/sainath-setti`;

    test('inspect all images on persona page', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, 'persona-full-page');

        // Get all img elements with their src and alt
        const images = await page.locator('img').evaluateAll((imgs) =>
            imgs.map((img) => ({
                src: (img as HTMLImageElement).src,
                alt: (img as HTMLImageElement).alt,
                width: (img as HTMLImageElement).naturalWidth,
                height: (img as HTMLImageElement).naturalHeight,
                complete: (img as HTMLImageElement).complete,
                visible: (img as HTMLImageElement).offsetParent !== null,
            }))
        );
        console.log('Images on persona page:');
        for (const img of images) {
            console.log(`  alt="${img.alt}" src=${img.src.substring(0, 80)} ${img.width}x${img.height} visible=${img.visible} complete=${img.complete}`);
        }
    });

    test('check if avatar shows initials fallback instead of image', async ({ page }) => {
        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Some avatar implementations show initials when no photo is set
        const avatarInitials = page.locator('[class*="avatar"] span, [class*="initials"], [aria-label*="avatar"]').first();
        const hasInitials = await avatarInitials.isVisible().catch(() => false);
        const initialsText = hasInitials ? await avatarInitials.textContent() : null;
        console.log('Avatar initials fallback:', hasInitials, initialsText?.trim());
    });

    test('persona page structure snapshot', async ({ page }) => {
        const errors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') errors.push(`[${msg.type()}] ${msg.text()}`);
        });
        page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`));

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // Get the page title
        const title = await page.title();
        console.log('Persona page title:', title);

        // Check for key persona page elements
        const h1Text = await page.locator('h1').first().textContent().catch(() => '');
        console.log('H1 text:', h1Text?.trim());

        const h2Texts = await page.locator('h2').evaluateAll((els) =>
            els.map((el) => el.textContent?.trim())
        );
        console.log('H2 texts:', h2Texts);

        // Check for bio or about section
        const bio = page.locator('[class*="bio"], [class*="about"], [data-testid*="bio"]').first();
        const hasBio = await bio.isVisible().catch(() => false);
        const bioText = hasBio ? (await bio.textContent())?.substring(0, 200) : null;
        console.log('Bio visible:', hasBio, bioText);

        console.log('Console errors on persona page:', errors);
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 4: Persona page chat — response detection
// ─────────────────────────────────────────────────────────────────

test.describe('Persona Page Chat (Detailed)', () => {
    const PERSONA_URL = `${BASE_URL}/p/sainath-setti`;

    test('chat sends and API call is made', async ({ page }) => {
        const apiCalls: { url: string; status: number }[] = [];
        page.on('response', (resp) => {
            if (resp.url().includes('api.personaon.com') || resp.url().includes('/chat')) {
                apiCalls.push({ url: resp.url(), status: resp.status() });
            }
        });

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, 'persona-chat-before');

        // Find the chat input
        const chatInput = page.locator('textarea, input[type="text"]').filter({
            hasNot: page.locator('input[type="hidden"]'),
        }).last();

        const allInputs = await page.locator('textarea, input[type="text"]').all();
        console.log('Text inputs found:', allInputs.length);
        for (const inp of allInputs) {
            const placeholder = await inp.getAttribute('placeholder').catch(() => '');
            const visible = await inp.isVisible().catch(() => false);
            console.log(`  input placeholder="${placeholder}" visible=${visible}`);
        }

        const lastInput = allInputs[allInputs.length - 1];
        if (!lastInput) { test.skip(); return; }

        const isVisible = await lastInput.isVisible().catch(() => false);
        if (!isVisible) { test.skip(); return; }

        await lastInput.fill('What is your background?');
        await page.waitForTimeout(500);
        await shot(page, 'persona-chat-typed');

        // Press Enter
        await lastInput.press('Enter');

        // Wait up to 15s for API calls to appear
        await page.waitForTimeout(15000);
        await shot(page, 'persona-chat-after-wait');

        console.log('API calls made during chat:', apiCalls);

        // Inspect the full page content to find the response
        const allText = await page.locator('body').innerText();
        const lines = allText.split('\n').filter((l) => l.trim().length > 20);
        console.log('Page text lines (first 30):');
        for (const line of lines.slice(0, 30)) {
            console.log(' ', line.trim().substring(0, 150));
        }
    });

    test('check SSE streaming endpoint is called', async ({ page }) => {
        const sseRequests: string[] = [];
        page.on('request', (req) => {
            if (req.url().includes('stream') || req.url().includes('chat') || req.url().includes('sse')) {
                sseRequests.push(`${req.method()} ${req.url()}`);
            }
        });

        await page.goto(PERSONA_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const chatInput = page.locator('textarea, input[placeholder*="ask"], input[placeholder*="Ask"]').first();
        const hasInput = await chatInput.isVisible().catch(() => false);
        if (!hasInput) { test.skip(); return; }

        await chatInput.fill('Quick question about your work');
        await chatInput.press('Enter');

        await page.waitForTimeout(10000);

        console.log('SSE/Chat/Stream requests:', sseRequests);
        expect(sseRequests.length).toBeGreaterThan(0);
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 5: Footer links — Documentation, Blog, Help Center, About, etc.
// are plain text (not links). Check for dead/unimplemented content.
// ─────────────────────────────────────────────────────────────────

test.describe('Footer & Navigation Completeness', () => {
    test('footer link audit', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        const footer = page.locator('footer');
        const hasFooter = await footer.isVisible().catch(() => false);
        if (!hasFooter) { console.log('No footer element found'); return; }

        const footerLinks = await footer.locator('a').evaluateAll((links) =>
            links.map((a) => ({
                text: (a as HTMLAnchorElement).textContent?.trim(),
                href: (a as HTMLAnchorElement).href,
            }))
        );

        const footerTextItems = await footer.locator('li').evaluateAll((items) =>
            items.map((li) => ({
                text: (li as HTMLElement).textContent?.trim(),
                hasLink: (li as HTMLElement).querySelector('a') !== null,
            }))
        );

        console.log('Footer links:');
        for (const link of footerLinks) {
            console.log(`  "${link.text}" → ${link.href}`);
        }

        console.log('\nFooter list items (including non-linked):');
        for (const item of footerTextItems) {
            const status = item.hasLink ? 'LINKED' : 'NOT LINKED (plain text)';
            console.log(`  [${status}] "${item.text}"`);
        }

        // Report footer items that are not linked
        const unlinkedItems = footerTextItems.filter((i) => !i.hasLink && i.text && i.text.length > 1);
        if (unlinkedItems.length > 0) {
            console.warn('\nWARN: Footer items missing links (dead content):');
            for (const item of unlinkedItems) {
                console.warn(`  - "${item.text}"`);
            }
        }
    });

    test('social links in footer go somewhere', async ({ page }) => {
        await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

        // From snapshot: X (Twitter) → "#", GitHub → "#"
        const socialLinks = await page.locator('footer a, [class*="social"] a').evaluateAll((links) =>
            links.map((a) => ({
                text: (a as HTMLAnchorElement).textContent?.trim(),
                href: (a as HTMLAnchorElement).href,
            }))
        );

        console.log('Social links:', socialLinks);

        const deadLinks = socialLinks.filter(
            (l) => l.href === '#' || l.href === `${BASE_URL}/#` || l.href.endsWith('#')
        );
        if (deadLinks.length > 0) {
            console.warn('WARN: Dead social links (href="#"):', deadLinks);
        }
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 6: Share page deep dive
// ─────────────────────────────────────────────────────────────────

test.describe('Share Page', () => {
    test('share page content and structure', async ({ page }) => {
        const response = await page.goto(`${BASE_URL}/share/sainath-setti`, {
            waitUntil: 'networkidle',
            timeout: 30000,
        });

        await shot(page, 'share-page-sainath');

        const statusCode = response?.status() ?? 0;
        console.log('Share page status:', statusCode);
        expect(statusCode).toBeLessThan(400);

        const title = await page.title();
        console.log('Share page title:', title);

        const h1 = await page.locator('h1').first().textContent().catch(() => '');
        console.log('Share page H1:', h1?.trim());

        // Check for QR code or share link display
        const qrCode = page.locator('[class*="qr"], canvas, img[alt*="qr"], img[alt*="QR"]').first();
        const hasQR = await qrCode.isVisible().catch(() => false);
        console.log('QR code visible:', hasQR);

        // Check for copyable link
        const copyBtn = page.locator('button:has-text("Copy"), button[aria-label*="copy"]').first();
        const hasCopy = await copyBtn.isVisible().catch(() => false);
        console.log('Copy button visible:', hasCopy);
    });
});

// ─────────────────────────────────────────────────────────────────
// ISSUE 7: Marketplace — inspect actual page structure
// ─────────────────────────────────────────────────────────────────

test.describe('Marketplace Deep Dive', () => {
    test('marketplace page full structure inspection', async ({ page }) => {
        const errors: string[] = [];
        page.on('console', (msg) => {
            if (msg.type() === 'error') errors.push(msg.text());
        });

        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });
        await shot(page, 'marketplace-full');

        const title = await page.title();
        console.log('Marketplace title:', title);

        // Count cards / personas listed
        const personaLinks = await page.locator('a[href*="/p/"]').all();
        console.log('Persona links (/p/...):', personaLinks.length);

        for (const link of personaLinks) {
            const href = await link.getAttribute('href');
            const text = await link.textContent();
            console.log(`  → ${href} "${text?.trim().substring(0, 50)}"`);
        }

        // Check filters
        const filterButtons = await page.locator('button, [role="tab"]').evaluateAll((btns) =>
            btns
                .filter((b) => (b as HTMLElement).offsetParent !== null)
                .map((b) => (b as HTMLElement).textContent?.trim())
                .filter(Boolean)
        );
        console.log('Visible buttons/tabs on marketplace:', filterButtons.slice(0, 20));

        // Check search input
        const searchInput = page.locator('input[type="search"], input[placeholder*="search"], input[placeholder*="Search"]').first();
        const hasSearch = await searchInput.isVisible().catch(() => false);
        console.log('Search input visible:', hasSearch);

        console.log('Console errors:', errors);
    });

    test('search functionality on marketplace', async ({ page }) => {
        await page.goto(`${BASE_URL}/marketplace`, { waitUntil: 'networkidle', timeout: 30000 });

        const searchInput = page.locator('input[type="search"], input[placeholder*="search"], input[placeholder*="Search"]').first();
        const hasSearch = await searchInput.isVisible().catch(() => false);

        if (!hasSearch) {
            console.log('No search input on marketplace — skipping');
            return;
        }

        await searchInput.fill('sainath');
        await page.waitForTimeout(2000);
        await shot(page, 'marketplace-search-sainath');

        const results = await page.locator('a[href*="/p/"]').count();
        console.log('Search results for "sainath":', results);
    });
});
