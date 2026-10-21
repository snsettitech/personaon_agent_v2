// Browser walk of public staging routes after a deploy (pilot step C3).
//
// For each route at widths 390, 768 and 1440: the document returns HTTP 200,
// the page logs no console errors or uncaught exceptions, a key element is
// visible, and a full-page screenshot is saved for the job summary.
// Console errors whose source is another origin (analytics, fonts, CDNs) are
// ignored: they say nothing about our deploy.
// Public routes only: no logins.
//
// Env:
//   STAGING_WALK_BASE_URL        staging frontend origin (required, see config)
//   STAGING_WALK_PERSONA_HANDLE  handle for /p/<handle>; the route is skipped when unset
//                                or when the handle renders "not found"
//   STAGING_WALK_SCREENSHOT_DIR  where screenshots go (default ./screenshots)
//   STAGING_WALK_IGNORE_CONSOLE  extra regex of console errors to ignore
import * as path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';

interface WalkRoute {
    name: string;
    path: string;
    keyElement: (page: Page) => Locator;
    // A soft-404 still returns 200. A matching title skips the route: the
    // test fixture is missing, which is not a deploy failure.
    skipTitle?: RegExp;
}

const WIDTHS = [390, 768, 1440] as const;
const HEIGHT_BY_WIDTH: Record<(typeof WIDTHS)[number], number> = { 390: 844, 768: 1024, 1440: 900 };
const SETTLE_MS = 1_500; // let hydration errors and late console errors surface

const handle = process.env.STAGING_WALK_PERSONA_HANDLE?.trim() ?? '';
const screenshotDir = path.resolve(process.env.STAGING_WALK_SCREENSHOT_DIR || 'screenshots');

// Extra noise to ignore. Keep this short: every entry is a class of error
// the walk can no longer catch.
const IGNORED_CONSOLE: RegExp[] = [
    /posthog/i,
    ...(process.env.STAGING_WALK_IGNORE_CONSOLE ? [new RegExp(process.env.STAGING_WALK_IGNORE_CONSOLE)] : []),
];

const firstH1 = (page: Page): Locator => page.locator('h1').first();

const ROUTES: WalkRoute[] = [
    { name: 'landing', path: '/', keyElement: firstH1 },
    { name: 'pricing', path: '/pricing', keyElement: firstH1 },
    {
        name: 'persona',
        path: handle ? `/p/${encodeURIComponent(handle)}` : '',
        keyElement: firstH1,
        skipTitle: /not found/i,
    },
];

function isIgnored(text: string): boolean {
    return IGNORED_CONSOLE.some((re) => re.test(text));
}

// True when the message came from a script or resource on another origin.
function isThirdParty(sourceUrl: string, appOrigin: string): boolean {
    if (!sourceUrl) return false;
    try {
        return new URL(sourceUrl).origin !== appOrigin;
    } catch {
        return false; // not a URL (e.g. "debugger eval"): treat as ours
    }
}

for (const route of ROUTES) {
    for (const width of WIDTHS) {
        test(`${route.name} @ ${width}px`, async ({ page, baseURL }) => {
            test.skip(!route.path, 'STAGING_WALK_PERSONA_HANDLE not set');

            const errors: string[] = [];
            const appOrigin = new URL(baseURL ?? '').origin;
            page.on('console', (msg) => {
                if (msg.type() !== 'error' || isThirdParty(msg.location().url, appOrigin)) return;
                if (!isIgnored(msg.text())) {
                    errors.push(`console.error: ${msg.text()}`);
                }
            });
            page.on('pageerror', (err) => {
                if (!isIgnored(err.message)) errors.push(`pageerror: ${err.message}`);
            });

            await page.setViewportSize({ width, height: HEIGHT_BY_WIDTH[width] });
            const response = await page.goto(route.path, { waitUntil: 'load' });
            expect(response, `no response for ${route.path}`).not.toBeNull();
            expect(response?.status(), `HTTP status of ${route.path}`).toBe(200);

            if (route.skipTitle && route.skipTitle.test(await page.title())) {
                test.skip(true, `${route.path} renders "not found": set STAGING_WALK_PERSONA_HANDLE to a live handle`);
            }
            await expect(route.keyElement(page)).toBeVisible();
            await page.waitForTimeout(SETTLE_MS);

            // Screenshot before the console assertion, so a red run still has it.
            await page.screenshot({
                path: path.join(screenshotDir, `${route.name}-${width}.png`),
                fullPage: true,
            });

            expect(errors, `console errors on ${route.path}`).toEqual([]);
        });
    }
}
