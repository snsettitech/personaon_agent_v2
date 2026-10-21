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
const BACKEND_URL = env.DEPLOYED_BACKEND_URL;
const EMAIL = env.TEST_ACCOUNT_EMAIL;
const PASSWORD = env.TEST_ACCOUNT_PASSWORD;

if (!FRONTEND_URL || !EMAIL || !PASSWORD || !BACKEND_URL) {
  console.error('Missing required env vars in .env');
  process.exit(1);
}

const OUTPUT_ROOT = path.resolve('..', 'artifacts', 'simulator');
fs.mkdirSync(OUTPUT_ROOT, { recursive: true });

async function getAuthToken(page) {
  return await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('sb-') && key.endsWith('-auth-token')) {
        const raw = localStorage.getItem(key);
        if (!raw) continue;
        try {
          const parsed = JSON.parse(raw);
          return parsed?.access_token || null;
        } catch {}
      }
    }
    return null;
  });
}

async function waitForAuthToken(page, timeoutMs = 15000) {
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

async function ensureTwinExists(page, scenarioDir) {
  let token = await waitForAuthToken(page, 20000);
  if (!token) {
    token = await getAuthTokenFromCookies(page.context());
  }
  if (!token) {
    fs.writeFileSync(path.join(scenarioDir, 'auth_token_missing.txt'), 'No auth token found in localStorage or cookies');
    // Fallback: attempt UI-based twin creation even without token access
    const createButton = page.getByRole('button', { name: /create your first twin/i });
    if (await createButton.count()) {
      await createButton.first().click();
      await page.waitForTimeout(5000);
    }
    return;
  }

  let twins = [];
  try {
    const twinsRes = await fetch(`${BACKEND_URL}/auth/my-twins`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (twinsRes.ok) {
      const data = await twinsRes.json();
      twins = Array.isArray(data) ? data : (data.twins || []);
    } else {
      const errText = await twinsRes.text();
      fs.writeFileSync(path.join(scenarioDir, 'twins_fetch_error.txt'), errText);
    }
  } catch (err) {
    fs.writeFileSync(path.join(scenarioDir, 'twins_fetch_error.txt'), String(err));
  }

  let activeTwinId = twins[0]?.id || null;

  if (!activeTwinId) {
    const payload = {
      name: 'Simulator E2E Twin',
      description: 'Auto-created for simulator repro',
      specialization: 'digital-persona',
      settings: {
        system_prompt: 'You are a helpful assistant.',
        handle: 'sim-e2e',
        tagline: 'Simulator repro',
        expertise: ['general'],
        personality: { tone: 'neutral', responseLength: 'medium', firstPerson: true }
      }
    };

    try {
      const createRes = await fetch(`${BACKEND_URL}/twins`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (createRes.ok) {
        const created = await createRes.json();
        activeTwinId = created.id;
        fs.writeFileSync(path.join(scenarioDir, 'created_twin.json'), JSON.stringify(created, null, 2));
      } else {
        const errText = await createRes.text();
        fs.writeFileSync(path.join(scenarioDir, 'create_twin_error.txt'), errText);
      }
    } catch (err) {
      fs.writeFileSync(path.join(scenarioDir, 'create_twin_error.txt'), String(err));
    }
  }

  if (activeTwinId) {
    await page.evaluate((twinId) => {
      localStorage.setItem('activeTwinId', twinId);
    }, activeTwinId);
    return;
  }

  // Fallback: attempt UI-based twin creation if still none
  const createButton = page.getByRole('button', { name: /create your first twin/i });
  if (await createButton.count()) {
    await createButton.first().click();
    await page.waitForTimeout(3000);
  }
}

async function loginIfNeeded(page, scenarioDir) {
  await page.waitForLoadState('domcontentloaded');

  const emailInput = page.locator('input[type="email"]');
  if (await emailInput.count()) {
    await emailInput.first().fill(EMAIL);
    const passwordInput = page.locator('input[type="password"]');
    await passwordInput.first().fill(PASSWORD);
    const signInButton = page.getByRole('button', { name: /sign in/i });
    await signInButton.click();
    await page.waitForLoadState('networkidle');
    return;
  }

  if (page.url().includes('/auth/login')) {
    try {
      await page.waitForSelector('input[type="email"]', { timeout: 10000 });
      await emailInput.first().fill(EMAIL);
      const passwordInput = page.locator('input[type="password"]');
      await passwordInput.first().fill(PASSWORD);
      await page.getByRole('button', { name: /sign in/i }).click();
      await page.waitForLoadState('networkidle');
      return;
    } catch (e) {
      const html = await page.content();
      fs.writeFileSync(path.join(scenarioDir, 'login_page.html'), html);
      await page.screenshot({ path: path.join(scenarioDir, 'login_page.png'), fullPage: true });
      throw e;
    }
  }
}

async function getMessageTexts(page) {
  const locator = page.locator('p.whitespace-pre-wrap');
  const count = await locator.count();
  const texts = [];
  for (let i = 0; i < count; i++) {
    const txt = (await locator.nth(i).innerText())?.trim();
    if (txt) texts.push(txt);
  }
  return texts;
}

async function sendMessage(page, text, logs, scenarioDir) {
  try {
    await page.waitForSelector('input[placeholder="Ask anything about your knowledge base..."]', { timeout: 30000 });
  } catch (e) {
    const html = await page.content();
    fs.writeFileSync(path.join(scenarioDir, 'simulator_page.html'), html);
    await page.screenshot({ path: path.join(scenarioDir, 'simulator_page.png'), fullPage: true });
    throw new Error('Chat input not found');
  }
  const input = page.getByPlaceholder('Ask anything about your knowledge base...');
  await input.fill(text);
  await input.press('Enter');
  logs.uiEvents.push({ type: 'send', text, at: new Date().toISOString() });
}

async function waitForResponse(page, logs, timeoutMs = 60000) {
  const start = Date.now();
  const spinnerTexts = ['Searching knowledge base...', 'Generating response...'];
  let spinnerVisible = true;
  let timedOut = false;
  while (Date.now() - start < timeoutMs) {
    spinnerVisible = false;
    for (const t of spinnerTexts) {
      const count = await page.locator(`text=${t}`).count();
      if (count > 0) {
        spinnerVisible = true;
        break;
      }
    }
    if (!spinnerVisible) break;
    await page.waitForTimeout(1000);
  }
  if (spinnerVisible) {
    timedOut = true;
  }
  logs.uiEvents.push({ type: 'wait_response', spinnerVisible, timedOut, at: new Date().toISOString() });
  return { spinnerVisible, timedOut };
}

async function getErrorBannerText(page) {
  const retryButton = page.getByRole('button', { name: /retry/i });
  if (await retryButton.count()) {
    const container = retryButton.first().locator('..');
    const text = (await container.innerText()).trim();
    return text || 'Retry banner visible';
  }
  const banner = page.locator('text=Connection stalled. Please retry.').first();
  if (await banner.count()) {
    return (await banner.innerText()).trim();
  }
  const altBanner = page.locator('div').filter({ hasText: "Sorry, I'm having trouble connecting to my brain right now." }).first();
  if (await altBanner.count()) {
    return (await altBanner.innerText()).trim();
  }
  return null;
}

async function getStorageSnapshot(page) {
  return await page.evaluate(() => ({
    localStorage: Object.fromEntries(Object.entries(localStorage)),
    sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
    url: location.href
  }));
}

async function runScenario(name, scenarioFn) {
  const scenarioDir = path.join(OUTPUT_ROOT, name);
  fs.mkdirSync(scenarioDir, { recursive: true });
  const harPath = path.join(scenarioDir, `${name}.har`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    recordHar: { path: harPath, content: 'embed' },
    viewport: { width: 1400, height: 900 }
  });
  const page = await context.newPage();

  const logs = {
    scenario: name,
    startTime: new Date().toISOString(),
    console: [],
    network: [],
    uiEvents: [],
    messagesBefore: [],
    messagesAfter: []
  };

  page.on('console', (msg) => {
    logs.console.push({
      type: msg.type(),
      text: msg.text(),
      location: msg.location(),
      at: new Date().toISOString()
    });
  });

  page.on('request', (req) => {
    const url = req.url();
    if (url.includes('/chat/')) {
      const entry = {
        type: 'request',
        url,
        method: req.method(),
        postData: req.postData(),
        headers: { 'content-type': req.headers()['content-type'] },
        at: new Date().toISOString()
      };
      logs.network.push(entry);
    }
  });

  page.on('response', async (res) => {
    const req = res.request();
    if (req.url().includes('/chat/')) {
      const entry = {
        type: 'response',
        url: res.url(),
        status: res.status(),
        statusText: res.statusText(),
        headers: res.headers(),
        at: new Date().toISOString()
      };
      logs.network.push(entry);
      try {
        await res.finished();
        const body = await res.text();
        entry.bodySnippet = body.slice(0, 1000);
        const lines = body.split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            if (data.type === 'metadata') {
              entry.conversation_id = data.conversation_id;
              entry.citations = data.citations;
              entry.confidence_score = data.confidence_score;
            }
          } catch {}
        }
      } catch (e) {
        entry.parseError = String(e);
      }
    }
  });

  page.on('requestfailed', (req) => {
    if (req.url().includes('/chat/')) {
      logs.network.push({
        type: 'requestfailed',
        url: req.url(),
        method: req.method(),
        failure: req.failure(),
        at: new Date().toISOString()
      });
    }
  });

  await page.goto(FRONTEND_URL, { waitUntil: 'domcontentloaded' });
  await loginIfNeeded(page, scenarioDir);
  try {
    const cookies = await context.cookies();
    fs.writeFileSync(path.join(scenarioDir, 'cookies.json'), JSON.stringify(cookies, null, 2));
    const storage = await getStorageSnapshot(page);
    fs.writeFileSync(path.join(scenarioDir, 'storage.json'), JSON.stringify(storage, null, 2));
  } catch (e) {
    fs.writeFileSync(path.join(scenarioDir, 'storage_error.txt'), String(e));
  }
  await ensureTwinExists(page, scenarioDir);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  await scenarioFn(page, logs, scenarioDir);

  logs.endTime = new Date().toISOString();
  logs.messagesAfter = await getMessageTexts(page);
  logs.errorBanner = await getErrorBannerText(page);
  try {
    const storageEnd = await getStorageSnapshot(page);
    fs.writeFileSync(path.join(scenarioDir, 'storage_end.json'), JSON.stringify(storageEnd, null, 2));
  } catch (e) {
    fs.writeFileSync(path.join(scenarioDir, 'storage_end_error.txt'), String(e));
  }

  fs.writeFileSync(path.join(scenarioDir, 'logs.json'), JSON.stringify(logs, null, 2));

  await context.close();
  await browser.close();

  return logs;
}

async function scenarioA(page, logs, scenarioDir) {
  await sendMessage(page, 'Scenario A: initial message', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  const page2 = await page.context().newPage();
  await page2.goto('about:blank');
  await page2.bringToFront();
  await page.waitForTimeout(65000);
  await page.bringToFront();

  await sendMessage(page, 'Scenario A: second message after switch', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
}

async function scenarioB(page, logs, scenarioDir) {
  await sendMessage(page, 'Scenario B: initial message', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  await sendMessage(page, 'Scenario B: message after refresh', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
}

async function scenarioC(page, logs, scenarioDir) {
  await sendMessage(page, 'Scenario C: initial message', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  await page.waitForTimeout(180000);

  await sendMessage(page, 'Scenario C: message after idle', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
}

async function scenarioD(page, logs, scenarioDir) {
  await sendMessage(page, 'Scenario D: initial message', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await loginIfNeeded(page, scenarioDir);

  await sendMessage(page, 'Scenario D: message after re-login', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
}

async function scenarioE(page, logs, scenarioDir) {
  await sendMessage(page, 'Scenario E: message before clear', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  page.once('dialog', async (dialog) => {
    await dialog.accept();
  });
  const clearButton = page.getByRole('button', { name: /clear history/i });
  await clearButton.click();
  await page.waitForTimeout(1000);

  logs.uiEvents.push({ type: 'clear_history', at: new Date().toISOString() });

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
}

async function scenarioF(page, logs, scenarioDir) {
  let token = await waitForAuthToken(page, 20000);
  if (!token) {
    token = await getAuthTokenFromCookies(page.context());
  }
  if (!token) {
    fs.writeFileSync(path.join(scenarioDir, 'auth_token_missing.txt'), 'No auth token for twin switch test');
    return;
  }

  const newTwinPayload = {
    name: 'Simulator E2E Twin B',
    description: 'Second twin for switch test',
    specialization: 'digital-persona',
    settings: {
      system_prompt: 'You are a helpful assistant.',
      handle: `sim-e2e-${Date.now()}`,
      tagline: 'Simulator repro',
      expertise: ['general'],
      personality: { tone: 'neutral', responseLength: 'medium', firstPerson: true }
    }
  };

  let twinB = null;
  try {
    const createRes = await fetch(`${BACKEND_URL}/twins`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(newTwinPayload)
    });
    if (createRes.ok) {
      twinB = await createRes.json();
      fs.writeFileSync(path.join(scenarioDir, 'created_twin.json'), JSON.stringify(twinB, null, 2));
    } else {
      fs.writeFileSync(path.join(scenarioDir, 'create_twin_error.txt'), await createRes.text());
      return;
    }
  } catch (e) {
    fs.writeFileSync(path.join(scenarioDir, 'create_twin_error.txt'), String(e));
    return;
  }

  await sendMessage(page, 'Scenario F: message on twin A', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
  logs.messagesBefore = await getMessageTexts(page);

  await page.evaluate((id) => {
    localStorage.setItem('activeTwinId', id);
  }, twinB.id);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);

  await sendMessage(page, 'Scenario F: message on twin B', logs, scenarioDir);
  await waitForResponse(page, logs, 60000);
}

async function scenarioG(page, logs, scenarioDir) {
  let abortNext = true;
  await page.route('**/chat/**', async (route) => {
    if (abortNext) {
      abortNext = false;
      await route.abort();
      return;
    }
    await route.continue();
  });

  await sendMessage(page, 'Scenario G: force failure', logs, scenarioDir);
  await waitForResponse(page, logs, 30000);
  logs.errorBanner = await getErrorBannerText(page);

  const retryButton = page.getByRole('button', { name: /retry/i });
  if (await retryButton.count()) {
    await retryButton.first().click();
    logs.uiEvents.push({ type: 'retry_click', at: new Date().toISOString() });
    await waitForResponse(page, logs, 60000);
  }
}

(async () => {
  const scenarios = [
    ['A', scenarioA],
    ['B', scenarioB],
    ['C', scenarioC],
    ['D', scenarioD],
    ['E', scenarioE],
    ['F', scenarioF],
    ['G', scenarioG]
  ];

  const allowed = (process.env.SIM_SCENARIOS || '').split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
  const activeScenarios = allowed.length ? scenarios.filter(([name]) => allowed.includes(name)) : scenarios;

  for (const [name, fn] of activeScenarios) {
    console.log(`Running scenario ${name}...`);
    await runScenario(`scenario_${name}`, fn);
  }

  console.log('Done. Logs saved to artifacts/simulator/*');
})();
