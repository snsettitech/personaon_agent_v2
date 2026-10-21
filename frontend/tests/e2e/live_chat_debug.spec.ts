/**
 * Debug landing page demo chat 404 error and share page issue
 */

import { test, expect, Page } from '@playwright/test';

const BASE_URL = 'https://personaon.com';

test('landing demo chat — capture all network activity', async ({ page }) => {
    const allRequests: { method: string; url: string }[] = [];
    const allResponses: { url: string; status: number }[] = [];
    const consoleAll: string[] = [];

    page.on('request', (req) => allRequests.push({ method: req.method(), url: req.url() }));
    page.on('response', (resp) => allResponses.push({ url: resp.url(), status: resp.status() }));
    page.on('console', (msg) => consoleAll.push(`[${msg.type()}] ${msg.text()}`));
    page.on('pageerror', (err) => consoleAll.push(`[pageerror] ${err.message}`));

    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });

    // Fill and send the demo chat
    const chatInput = page.getByPlaceholder('Ask Alex anything...');
    await chatInput.waitFor({ state: 'visible', timeout: 10000 });
    await chatInput.fill('What industries do you focus on?');

    const sendBtn = page.locator('button[aria-label="Send message"]');
    await sendBtn.click();

    // Wait for streaming response
    await page.waitForTimeout(15000);

    // Find ALL 404s
    const failures = allResponses.filter((r) => r.status >= 400);
    console.log('\n=== FAILED REQUESTS ===');
    for (const f of failures) {
        console.log(`  ${f.status} ${f.url}`);
    }

    // Find chat-related requests
    const chatRequests = allRequests.filter(
        (r) =>
            r.url.includes('chat') ||
            r.url.includes('stream') ||
            r.url.includes('api.personaon') ||
            r.url.includes('message')
    );
    console.log('\n=== CHAT-RELATED REQUESTS ===');
    for (const r of chatRequests) {
        console.log(`  ${r.method} ${r.url}`);
    }

    const chatResponses = allResponses.filter(
        (r) =>
            r.url.includes('chat') ||
            r.url.includes('stream') ||
            r.url.includes('api.personaon') ||
            r.url.includes('message')
    );
    console.log('\n=== CHAT-RELATED RESPONSES ===');
    for (const r of chatResponses) {
        console.log(`  ${r.status} ${r.url}`);
    }

    console.log('\n=== CONSOLE MESSAGES ===');
    for (const msg of consoleAll) {
        console.log(' ', msg);
    }

    // Dump the page HTML structure related to the chat
    const chatContainerHTML = await page.evaluate(() => {
        const chatArea = document.querySelector('[class*="chat"], [class*="message"], [class*="widget"]');
        return chatArea ? chatArea.outerHTML.substring(0, 3000) : 'NO CHAT CONTAINER FOUND';
    });
    console.log('\n=== CHAT CONTAINER HTML (first 3000 chars) ===');
    console.log(chatContainerHTML);
});

test('share page /share/sainath-setti — full debug', async ({ page }) => {
    const consoleAll: string[] = [];
    const allResponses: { url: string; status: number }[] = [];

    page.on('response', (resp) => allResponses.push({ url: resp.url(), status: resp.status() }));
    page.on('console', (msg) => consoleAll.push(`[${msg.type()}] ${msg.text()}`));

    await page.goto(`${BASE_URL}/share/sainath-setti`, { waitUntil: 'networkidle', timeout: 30000 });

    console.log('Page title:', await page.title());
    console.log('Page URL:', page.url());

    const bodyText = await page.locator('body').innerText();
    console.log('Page body text (first 1000 chars):');
    console.log(bodyText.substring(0, 1000));

    const failures = allResponses.filter((r) => r.status >= 400);
    console.log('\nFailed requests on share page:');
    for (const f of failures) {
        console.log(`  ${f.status} ${f.url}`);
    }

    const apiRequests = allResponses.filter((r) => r.url.includes('api.personaon'));
    console.log('\nAPI requests on share page:');
    for (const r of apiRequests) {
        console.log(`  ${r.status} ${r.url}`);
    }

    console.log('\nConsole messages:');
    for (const msg of consoleAll.filter((m) => !m.includes('[log]'))) {
        console.log(' ', msg);
    }
});
