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

const BACKEND_URL =
  frontendEnv.NEXT_PUBLIC_BACKEND_URL ||
  frontendEnv.NEXT_PUBLIC_API_URL ||
  env.DEPLOYED_BACKEND_URL ||
  'http://localhost:8000';

const EMAIL = env.TEST_ACCOUNT_EMAIL;
const PASSWORD = env.TEST_ACCOUNT_PASSWORD;

if (!EMAIL || !PASSWORD) {
  console.error('Missing TEST_ACCOUNT_EMAIL or TEST_ACCOUNT_PASSWORD in .env');
  process.exit(1);
}

const PROOF_DIR = path.join(repoRoot, 'proof');
fs.mkdirSync(PROOF_DIR, { recursive: true });

const screenshotPath = (name) => path.join(PROOF_DIR, name);

function sanitizeHeaders(headers) {
  const sanitized = {};
  for (const [key, value] of Object.entries(headers || {})) {
    if (!value) continue;
    const lower = key.toLowerCase();
    if (lower === 'authorization' || lower === 'cookie' || lower === 'set-cookie') {
      sanitized[key] = '[redacted]';
    } else {
      sanitized[key] = value;
    }
  }
  return sanitized;
}

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

async function waitForAuthToken(page, timeoutMs = 20000) {
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

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) return { ok: false, status: res.status, data: null, text: await res.text() };
  const data = await res.json();
  return { ok: true, status: res.status, data };
}

async function ensureTwin(token) {
  const twinsRes = await fetchJson(`${BACKEND_URL}/auth/my-twins`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const twins = twinsRes.ok && Array.isArray(twinsRes.data) ? twinsRes.data : [];

  for (const twin of twins) {
    const memRes = await fetchJson(`${BACKEND_URL}/twins/${twin.id}/owner-memory?status=active`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (memRes.ok && Array.isArray(memRes.data) && memRes.data.length === 0) {
      return twin;
    }
  }

  const payload = {
    name: `UI Proof Twin ${Date.now()}`,
    description: 'Auto-created for UI proof run',
    specialization: 'digital-persona',
    settings: {
      system_prompt: 'You are a helpful assistant.',
      handle: `ui-proof-${Date.now()}`,
      tagline: 'UI proof run',
      expertise: ['general'],
      personality: { tone: 'neutral', responseLength: 'medium', firstPerson: true }
    }
  };

  const createRes = await fetchJson(`${BACKEND_URL}/twins`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!createRes.ok) {
    throw new Error(`Failed to create twin: ${createRes.status}`);
  }
  return createRes.data;
}

async function ensureShareToken(token, twinId) {
  const headers = { Authorization: `Bearer ${token}` };
  const getInfo = async () => fetchJson(`${BACKEND_URL}/twins/${twinId}/share-link`, { headers });

  let infoRes = await getInfo();
  if (!infoRes.ok) {
    throw new Error(`Failed to fetch share link info (${infoRes.status})`);
  }

  const info = infoRes.data || {};
  if (!info.public_share_enabled) {
    await fetchJson(`${BACKEND_URL}/twins/${twinId}/sharing`, {
      method: 'PATCH',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_public: true })
    });
  }

  if (!info.share_token) {
    await fetchJson(`${BACKEND_URL}/twins/${twinId}/share-link`, {
      method: 'POST',
      headers
    });
  }

  infoRes = await getInfo();
  if (!infoRes.ok || !infoRes.data?.share_token) {
    throw new Error('Share token missing after generation');
  }
  return infoRes.data.share_token;
}

async function captureHarAndSnippet(response, requestBody, outputHarPath, outputSnippetPath) {
  const resBody = await response.text();
  const lines = resBody.split('\n').filter(Boolean);
  const snippetLines = lines.slice(0, 6);
  fs.writeFileSync(outputSnippetPath, snippetLines.join('\n'));

  const har = {
    log: {
      version: '1.2',
      creator: { name: 'ui-proof-script', version: '1.0' },
      entries: [
        {
          startedDateTime: new Date().toISOString(),
          time: 0,
          request: {
            method: response.request().method(),
            url: response.request().url(),
            headers: sanitizeHeaders(response.request().headers()),
            postData: requestBody ? { mimeType: 'application/json', text: requestBody } : undefined
          },
          response: {
            status: response.status(),
            statusText: response.statusText(),
            headers: sanitizeHeaders(response.headers()),
            content: { mimeType: response.headers()['content-type'] || 'application/json', text: snippetLines.join('\n') }
          }
        }
      ]
    }
  };

  fs.writeFileSync(outputHarPath, JSON.stringify(har, null, 2));
}

async function findAccessibleTwin(page, candidateIds, baseUrl) {
  for (const id of candidateIds) {
    if (!id) continue;
    const url = `${baseUrl}/dashboard/twins/${id}?tab=training`;
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const result = await Promise.race([
      page.waitForSelector('text=Pending Clarifications', { timeout: 20000 }).then(() => 'ok').catch(() => null),
      page.waitForSelector('text=Twin not found', { timeout: 20000 }).then(() => 'notfound').catch(() => null)
    ]);
    if (result === 'ok') {
      return id;
    }
  }
  return null;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto(`${FRONTEND_URL}/auth/login`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await loginIfNeeded(page);

  const token = await resolveAuthToken(page);
  if (!token) {
    throw new Error('Unable to resolve auth token after login');
  }

  const twin = await ensureTwin(token);
  const twinId = twin.id;

  const shareToken = await ensureShareToken(token, twinId);

  const trainingUrl = `${FRONTEND_URL}/dashboard/twins/${twinId}?tab=training`;
  await page.goto(trainingUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  try {
    await page.waitForSelector('text=Pending Clarifications', { timeout: 60000 });
  } catch (err) {
    await page.screenshot({ path: screenshotPath('debug_training_page.png'), fullPage: true });
    const html = await page.content();
    fs.writeFileSync(path.join(PROOF_DIR, 'debug_training_page.html'), html);
    throw err;
  }

  await page.screenshot({ path: screenshotPath('ui_env_indicator.png'), fullPage: true });
  await page.screenshot({ path: screenshotPath('ui_tabs_visible.png'), fullPage: true });

  const topicTag = `Zephyr-Prism-${Date.now()}`;
  const stanceQuestion = `What is your stance on the ${topicTag} hiring framework for 2026?`;
  const stanceAnswer = `I strongly support the ${topicTag} hiring framework for 2026.`;

  const input = page.getByPlaceholder('Ask anything about your knowledge base...');
  await input.fill(stanceQuestion);

  const responsePromise = page.waitForResponse((res) => {
    return res.request().method() === 'POST' && res.url().includes(`/chat/${twinId}`);
  }, { timeout: 60000 });

  await input.press('Enter');

  const response = await responsePromise;
  await captureHarAndSnippet(
    response,
    JSON.stringify({ query: stanceQuestion, conversation_id: null, mode: 'owner' }),
    screenshotPath('network_owner_stance_request.har'),
    screenshotPath('network_response_snippet.txt')
  );

  await page.waitForSelector('text=Clarification Needed', { timeout: 60000 });
  await page.locator('text=Clarification Needed').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshotPath('ui_owner_step1_clarify.png'), fullPage: true });

  const clarifyInput = page.getByRole('textbox', { name: 'Answer in one sentence...' }).first();
  await clarifyInput.fill(stanceAnswer);
  await page.getByRole('button', { name: /save memory/i }).first().click();

  await page.waitForSelector('text=Saved. Ask again and I will answer using your memory.', { timeout: 60000 });
  await page.getByRole('button', { name: /refresh/i }).first().click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: screenshotPath('ui_owner_step2_saved.png'), fullPage: true });

  await input.fill(stanceQuestion);
  await input.press('Enter');
  await page.waitForSelector('text=Used Owner Memory', { timeout: 60000 });
  await page.locator('text=Used Owner Memory').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshotPath('ui_owner_step3_used_memory.png'), fullPage: true });

  const debugToggle = page.getByRole('button', { name: /show/i }).first();
  await debugToggle.click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: screenshotPath('ui_debug_panel.png'), fullPage: true });

  const shareUrl = `${FRONTEND_URL}/share/${twinId}/${shareToken}`;
  await page.goto(shareUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('text=Start a Conversation', { timeout: 60000 });

  const publicInput = page.getByPlaceholder('Type your message...');
  await publicInput.fill(stanceQuestion);
  await publicInput.press('Enter');
  await page.waitForSelector('text=Used Owner Memory', { timeout: 60000 });
  await page.locator('text=Used Owner Memory').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshotPath('ui_public_step4_used_memory.png'), fullPage: true });

  const topicTag2 = `Orion-Policy-${Date.now()}`;
  const stanceQuestion2 = `What is your stance on the ${topicTag2} escalation policy for incidents?`;
  await publicInput.fill(stanceQuestion2);
  await publicInput.press('Enter');
  await page.waitForSelector('text=Queued for owner confirmation', { timeout: 60000 });
  await page.screenshot({ path: screenshotPath('ui_public_step5_queued.png'), fullPage: true });

  await page.goto(trainingUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('text=Pending Clarifications', { timeout: 60000 });
  await page.getByRole('button', { name: /refresh/i }).first().click();
  await page.waitForTimeout(1500);

  const pendingCard = page.locator('div', { hasText: topicTag2 }).first();
  await pendingCard.locator('input[placeholder="Answer in one sentence..."]').fill(`Use ${topicTag2} only for critical emergencies.`);
  await pendingCard.getByRole('button', { name: /save memory/i }).click();
  await page.waitForTimeout(1500);

  await page.goto(shareUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await publicInput.fill(stanceQuestion2);
  await publicInput.press('Enter');
  await page.waitForSelector('text=Used Owner Memory', { timeout: 60000 });
  await page.locator('text=Used Owner Memory').first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: screenshotPath('ui_public_step7_after_resolve.png'), fullPage: true });

  const reportHtml = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>UI Proof Report</title>
  <style>body{font-family:Arial, sans-serif;padding:20px;background:#f7f7fb;color:#111}h1{font-size:20px}img{max-width:100%;border:1px solid #ddd;border-radius:8px;margin:8px 0}</style>
</head>
<body>
  <h1>UI Proof Report</h1>
  <p>Frontend: ${FRONTEND_URL}</p>
  <p>Backend: ${BACKEND_URL}</p>
  <h2>Owner Flow</h2>
  <img src="ui_env_indicator.png" alt="env" />
  <img src="ui_tabs_visible.png" alt="tabs" />
  <img src="ui_owner_step1_clarify.png" alt="clarify" />
  <img src="ui_owner_step2_saved.png" alt="saved" />
  <img src="ui_owner_step3_used_memory.png" alt="used memory" />
  <img src="ui_debug_panel.png" alt="debug" />
  <h2>Public Flow</h2>
  <img src="ui_public_step4_used_memory.png" alt="public used memory" />
  <img src="ui_public_step5_queued.png" alt="public queued" />
  <img src="ui_public_step7_after_resolve.png" alt="public after resolve" />
</body>
</html>`;

  fs.writeFileSync(path.join(PROOF_DIR, 'playwright_report.html'), reportHtml);

  await context.close();
  await browser.close();

  console.log('UI proof artifacts saved to proof/');
})();
