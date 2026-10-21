import fs from 'fs';
import path from 'path';
import { chromium } from '@playwright/test';

function loadEnv(envPath) {
  const data = fs.readFileSync(envPath, 'utf8');
  const env = {};
  for (const line of data.split(/\r?\n/)) {
    if (!line || line.trim().startsWith('#')) continue;
    const idx = line.indexOf('=');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const val = line.slice(idx + 1).trim();
    env[key] = val;
  }
  return env;
}

const env = loadEnv(path.resolve('..', '.env'));
const FRONTEND_URL = env.DEPLOYED_FRONTEND_URL;
const EMAIL = env.TEST_ACCOUNT_EMAIL;
const PASSWORD = env.TEST_ACCOUNT_PASSWORD;

const OUTPUT_DIR = path.resolve('..', 'artifacts', 'simulator', 'login_check');
fs.mkdirSync(OUTPUT_DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  page.on('console', (msg) => {
    fs.appendFileSync(path.join(OUTPUT_DIR, 'console.txt'), `[${msg.type()}] ${msg.text()}\n`);
  });

  await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  const emailInput = page.locator('input[type="email"]');
  if (await emailInput.count()) {
    await emailInput.first().fill(EMAIL);
    const passwordInput = page.locator('input[type="password"]');
    await passwordInput.first().fill(PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForTimeout(5000);
  }

  await page.screenshot({ path: path.join(OUTPUT_DIR, 'after_login.png'), fullPage: true });
  fs.writeFileSync(path.join(OUTPUT_DIR, 'after_login.html'), await page.content());
  fs.writeFileSync(path.join(OUTPUT_DIR, 'url.txt'), page.url());

  await context.close();
  await browser.close();
})();
