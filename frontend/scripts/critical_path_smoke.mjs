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

const repoRoot = path.resolve(process.cwd(), '..');
const envPath = path.join(repoRoot, '.env');
const env = loadEnv(envPath);

const frontendEnvPath = path.join(process.cwd(), '.env.local');
const frontendEnv = fs.existsSync(frontendEnvPath) ? loadEnv(frontendEnvPath) : {};

const frontendCandidate =
  frontendEnv.NEXT_PUBLIC_FRONTEND_URL ||
  env.DEPLOYED_FRONTEND_URL ||
  'http://localhost:3000';
const FRONTEND_URL = (() => {
  try {
    return new URL(frontendCandidate).origin;
  } catch {
    return frontendCandidate;
  }
})();

const EMAIL = env.TEST_ACCOUNT_EMAIL;
const PASSWORD = env.TEST_ACCOUNT_PASSWORD;

if (!EMAIL || !PASSWORD) {
  console.error('Missing TEST_ACCOUNT_EMAIL or TEST_ACCOUNT_PASSWORD in .env');
  process.exit(1);
}

const PROOF_DIR = path.join(repoRoot, 'proof');
fs.mkdirSync(PROOF_DIR, { recursive: true });

const screenshotPath = (name) => path.join(PROOF_DIR, name);

const proofDataPath = path.join(PROOF_DIR, 'api_proof.json');
if (!fs.existsSync(proofDataPath)) {
  console.error('Missing proof/api_proof.json - run scripts/run_api_proof.py first.');
  process.exit(1);
}

const proofData = JSON.parse(fs.readFileSync(proofDataPath, 'utf8'));
const twinId = proofData.twin_id;
function normalizeShareUrl(rawShareUrl) {
  if (!rawShareUrl) return rawShareUrl;
  try {
    const parsed = new URL(rawShareUrl);
    if (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1') {
      const base = new URL(FRONTEND_URL);
      return `${base.origin}${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
    return rawShareUrl;
  } catch {
    if (rawShareUrl.startsWith('/')) {
      return `${FRONTEND_URL}${rawShareUrl}`;
    }
    return rawShareUrl;
  }
}

const shareUrl = normalizeShareUrl(proofData.share_url);
const uniquePhrase = proofData.unique_phrase;

async function loginIfNeeded(page) {
  await page.waitForLoadState('domcontentloaded');

  if (page.url().includes('/auth/login')) {
    await page.waitForSelector('input[type="email"]', { timeout: 20000 });
  }

  const emailInput = page.locator('input[type="email"]');
  if (await emailInput.count()) {
    await emailInput.first().fill(EMAIL);
    const passwordInput = page.locator('input[type="password"]');
    await passwordInput.first().fill(PASSWORD);
    const signInButton = page.getByRole('button', { name: /sign in/i });
    await signInButton.click();
    await page.waitForLoadState('domcontentloaded');
  }
}

async function getAuthToken(page) {
  return await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('sb-') && key.endsWith('-auth-token')) {
        const raw = localStorage.getItem(key);
        if (!raw) continue;
        try {
          const parsed = JSON.parse(raw);
          return parsed?.access_token || null;
        } catch {
          return null;
        }
      }
    }
    return null;
  });
}

async function waitForAuthToken(page, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const token = await getAuthToken(page);
    if (token) return token;
    await page.waitForTimeout(500);
  }
  return null;
}

async function getAuthTokenFromCookies(context) {
  const cookies = await context.cookies();
  for (const cookie of cookies) {
    if (!cookie.name.endsWith('auth-token')) continue;
    const value = cookie.value || '';
    const prefix = 'base64-';
    if (!value.startsWith(prefix)) continue;
    try {
      const raw = Buffer.from(value.slice(prefix.length), 'base64').toString('utf8');
      const parsed = JSON.parse(raw);
      if (parsed?.access_token) {
        return parsed.access_token;
      }
    } catch {}
  }
  return null;
}

async function resolveAuthToken(page) {
  let token = await waitForAuthToken(page, 25000);
  if (!token) {
    token = await getAuthTokenFromCookies(page.context());
  }
  return token;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const consoleLogPath = screenshotPath('ui_console.log');
  fs.writeFileSync(consoleLogPath, '');
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      fs.appendFileSync(consoleLogPath, `[console.${msg.type()}] ${msg.text()}\n`);
    }
  });
  page.on('pageerror', (err) => {
    fs.appendFileSync(consoleLogPath, `[pageerror] ${err.message}\n`);
  });

  await page.goto(`${FRONTEND_URL}/auth/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await loginIfNeeded(page);
  const token = await resolveAuthToken(page);
  if (!token) {
    const html = await page.content();
    fs.writeFileSync(screenshotPath('ui_login_debug.html'), html);
    throw new Error('Unable to resolve auth token after login');
  }

  // Knowledge tab: verify ingested sources visible
  const knowledgeUrl = `${FRONTEND_URL}/dashboard/twins/${twinId}?tab=knowledge`;
  await page.goto(knowledgeUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  let expectedLabel = null;
  try {
    const sourcesResponse = await page.waitForResponse((res) => {
      return res.url().includes(`/sources/${twinId}`) && res.status() === 200;
    }, { timeout: 60000 });
    const data = await sourcesResponse.json();
    fs.writeFileSync(screenshotPath('ui_sources_response.json'), JSON.stringify(data, null, 2));
    const sources = Array.isArray(data) ? data : [];
    if (sources.length > 0) {
      const source = sources[0];
      expectedLabel =
        source?.filename ||
        source?.file_url ||
        source?.name ||
        source?.title ||
        source?.id;
      if (expectedLabel) {
        await page.waitForSelector(`text=${expectedLabel}`, { timeout: 20000 });
      }
    }
  } catch (err) {
    fs.appendFileSync(consoleLogPath, `[sources] ${err?.message || err}\n`);
  }
  await page.waitForTimeout(2000);
  const html = await page.content();
  fs.writeFileSync(screenshotPath('ui_knowledge_debug.html'), html);
  const hasSource = expectedLabel ? html.includes(expectedLabel) : false;
  await page.screenshot({ path: screenshotPath('ui_knowledge_sources.png'), fullPage: true });
  fs.writeFileSync(screenshotPath('ui_knowledge_has_source.txt'), hasSource ? 'true' : 'false');

  // Public share chat: verify retrieval
  await page.goto(shareUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('input[placeholder="Type your message..."]', { timeout: 60000 });
  const publicInput = page.getByPlaceholder('Type your message...');
  const question = 'What is the unique phrase in the critical path proof file?';
  await publicInput.fill(question);
  await publicInput.press('Enter');
  await page.waitForSelector(`text=${uniquePhrase}`, { timeout: 60000 });
  await page.screenshot({ path: screenshotPath('ui_public_chat_answer.png'), fullPage: true });

  await context.close();
  await browser.close();

  console.log('Critical path UI proof artifacts saved to proof/');
})();
