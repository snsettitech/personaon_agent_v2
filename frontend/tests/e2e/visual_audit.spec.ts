import { test } from '@playwright/test';

test.describe('visual audit', () => {
  test.setTimeout(120000);

  test('landing desktop full page', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: '/tmp/shot-landing-desktop.png', fullPage: true });
  });

  test('landing mobile full page', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: '/tmp/shot-landing-mobile.png', fullPage: true });
  });

  test('persona page hero desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/p/jane-smith');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: '/tmp/shot-persona-hero.png', fullPage: true });
  });

  test('persona chat with loop prompt mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.route('**/v2/chat/public/**/stream', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: message\ndata: {"text": "I am Jane Smith, a Product Leader at Acme. I have spent 15 years building products in tech."}\n\nevent: done\ndata: {}\n\n',
      })
    );
    await page.goto('/p/jane-smith');
    await page.waitForTimeout(2000);
    await page.getByText('What do you do?').first().click();
    await page.waitForTimeout(2500);
    await page.screenshot({ path: '/tmp/shot-persona-chat-mobile.png', fullPage: false });
  });
});
