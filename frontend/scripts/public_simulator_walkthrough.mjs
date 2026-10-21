import fs from 'fs';
import path from 'path';
import { chromium } from '@playwright/test';

function loadEnv(envPath) {
  const out = {};
  if (!fs.existsSync(envPath)) return out;
  const data = fs.readFileSync(envPath, 'utf8');
  for (const raw of data.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf('=');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const val = line.slice(idx + 1).trim();
    out[key] = val.replace(/^"(.*)"$/, '$1');
  }
  return out;
}

function safeTokenPreview(value) {
  if (!value) return null;
  if (value.length <= 8) return value;
  return `${value.slice(0, 4)}...${value.slice(-4)}`;
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data, text };
}

function parseChatSSE(rawText) {
  const lines = String(rawText || '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const events = [];
  let content = '';
  let metadata = null;
  let clarify = null;
  for (const line of lines) {
    try {
      const evt = JSON.parse(line);
      events.push(evt);
      if (evt.type === 'metadata') metadata = evt;
      if (evt.type === 'content') content += evt.content || evt.token || '';
      if (evt.type === 'clarify') clarify = evt;
    } catch {
      // ignore non-json lines
    }
  }
  return { events, content: content.trim(), metadata, clarify };
}

async function signInSupabase({ supabaseUrl, anonKey, email, password }) {
  const url = `${supabaseUrl}/auth/v1/token?grant_type=password`;
  const res = await fetchJson(url, {
    method: 'POST',
    headers: {
      apikey: anonKey,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok || !res.data?.access_token) {
    throw new Error(`Supabase password sign-in failed (${res.status}): ${res.text}`);
  }
  return res.data;
}

async function ensureTwin(token, backendUrl) {
  const list = await fetchJson(`${backendUrl}/auth/my-twins`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (list.ok && Array.isArray(list.data) && list.data.length > 0) {
    return list.data[0];
  }

  const payload = {
    name: `Walkthrough Twin ${Date.now()}`,
    description: 'Auto-created for simulator walkthrough',
    specialization: 'digital-persona',
    settings: {
      system_prompt: 'You are a helpful assistant.',
      handle: `walkthrough-${Date.now()}`,
      tagline: 'Walkthrough twin',
      expertise: ['vc', 'founder-coaching'],
      personality: { tone: 'professional', responseLength: 'medium', firstPerson: true },
    },
  };
  const create = await fetchJson(`${backendUrl}/twins`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!create.ok || !create.data?.id) {
    throw new Error(`Failed to create twin (${create.status}): ${create.text}`);
  }
  return create.data;
}

async function ensureShare(token, backendUrl, twinId) {
  const headers = { Authorization: `Bearer ${token}` };
  let info = await fetchJson(`${backendUrl}/twins/${twinId}/share-link`, { headers });
  if (!info.ok) {
    throw new Error(`Failed to read share-link (${info.status})`);
  }

  if (!info.data?.public_share_enabled) {
    await fetchJson(`${backendUrl}/twins/${twinId}/sharing`, {
      method: 'PATCH',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_public: true }),
    });
  }

  if (!info.data?.share_token) {
    await fetchJson(`${backendUrl}/twins/${twinId}/share-link`, {
      method: 'POST',
      headers,
    });
  }

  info = await fetchJson(`${backendUrl}/twins/${twinId}/share-link`, { headers });
  if (!info.ok || !info.data?.share_token) {
    throw new Error(`Share token not available (${info.status})`);
  }
  return info.data;
}

async function runLegacyPrompt(token, backendUrl, twinId, prompt) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  let res;
  let raw = '';
  let timedOut = false;
  try {
    res = await fetch(`${backendUrl}/chat/${twinId}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: prompt,
        conversation_id: null,
        mode: 'public',
      }),
      signal: controller.signal,
    });
    raw = await res.text();
  } catch (err) {
    timedOut = err?.name === 'AbortError';
    if (!timedOut) throw err;
  } finally {
    clearTimeout(timeout);
  }

  const parsed = parseChatSSE(raw);
  return {
    prompt,
    endpoint: `/chat/${twinId}`,
    status: timedOut ? 408 : (res?.status ?? 499),
    assistant: parsed.content || parsed.clarify?.question || '',
    confidence_score: parsed.metadata?.confidence_score ?? null,
    citations_count: Array.isArray(parsed.metadata?.citations) ? parsed.metadata.citations.length : 0,
    clarify: parsed.clarify
      ? {
          clarification_id: parsed.clarify.clarification_id || null,
          question: parsed.clarify.question || null,
        }
      : null,
  };
}

async function runUiPrompt(page, twinId, prompt) {
  const reqPromise = page.waitForResponse(
    (res) => {
      if (res.request().method() !== 'POST') return false;
      const url = res.url();
      return url.includes(`/public/chat/${twinId}/`) || url.endsWith(`/chat/${twinId}`);
    },
    { timeout: 20000 }
  );

  await page.fill('textarea[aria-label="Chat message input"]', prompt);
  await page.press('textarea[aria-label="Chat message input"]', 'Enter');

  let res;
  try {
    res = await reqPromise;
  } catch {
    // Fallback click path if Enter key did not trigger submit.
    await page.click('button[aria-label="Send message"]');
    res = await page.waitForResponse(
      (r) => {
        if (r.request().method() !== 'POST') return false;
        const url = r.url();
        return url.includes(`/public/chat/${twinId}/`) || url.endsWith(`/chat/${twinId}`);
      },
      { timeout: 20000 }
    );
  }
  const url = res.url();
  const bodyText = await res.text();
  let payload = null;
  try {
    payload = bodyText ? JSON.parse(bodyText) : null;
  } catch {
    payload = null;
  }

  let assistant = '';
  if (payload?.status === 'answer') assistant = payload.response || '';
  else if (payload?.status === 'queued') assistant = payload.message || '';
  else assistant = payload?.response || '';

  return {
    prompt,
    endpoint: url,
    status: res.status(),
    endpoint_type: url.includes('/public/chat/') ? 'public_chat' : 'legacy_chat',
    assistant,
    confidence_score: payload?.confidence_score ?? null,
    citations_count: Array.isArray(payload?.citations) ? payload.citations.length : 0,
    queued: payload?.status === 'queued',
  };
}

async function main() {
  const repoRoot = path.resolve(process.cwd(), '..');
  const env = loadEnv(path.join(repoRoot, '.env'));
  const frontendUrl = 'http://127.0.0.1:3000';
  const backendUrl = 'http://127.0.0.1:8000';
  const email = env.TEST_ACCOUNT_EMAIL;
  const password = env.TEST_ACCOUNT_PASSWORD;
  const supabaseUrl = env.SUPABASE_URL;
  const anonKey = env.SUPABASE_KEY;

  if (!email || !password || !supabaseUrl || !anonKey) {
    throw new Error('Missing TEST_ACCOUNT_EMAIL/TEST_ACCOUNT_PASSWORD/SUPABASE_URL/SUPABASE_KEY in root .env');
  }

  const prompts = ['hi', 'who are you?', 'do you know antler'];

  console.log('[walkthrough] starting');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  try {
    console.log('[walkthrough] signing in');
    const session = await signInSupabase({
      supabaseUrl,
      anonKey,
      email,
      password,
    });
    const token = session.access_token;

    const projectRef = new URL(supabaseUrl).hostname.split('.')[0];
    const cookieName = `sb-${projectRef}-auth-token`;
    const cookieValue = `base64-${Buffer.from(JSON.stringify(session)).toString('base64')}`;
    await context.addCookies([
      {
        name: cookieName,
        value: cookieValue,
        url: frontendUrl,
        httpOnly: false,
        secure: false,
      },
    ]);

    await page.goto(frontendUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });

    console.log('[walkthrough] ensuring twin/share');
    const twin = await ensureTwin(token, backendUrl);
    const share = await ensureShare(token, backendUrl, twin.id);

    // Force simulator to use this twin when context is available.
    await page.evaluate((id) => localStorage.setItem('activeTwinId', id), twin.id);

    console.log('[walkthrough] collecting before traces');
    const before = [];
    for (const prompt of prompts) {
      before.push(await runLegacyPrompt(token, backendUrl, twin.id, prompt));
    }

    const simulatorUrl = `${frontendUrl}/dashboard/simulator/public?twin_id=${encodeURIComponent(
      twin.id
    )}&share_token=${encodeURIComponent(share.share_token)}`;
    console.log('[walkthrough] opening', simulatorUrl);
    await page.goto(simulatorUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForSelector('textarea[aria-label="Chat message input"]', { timeout: 60000 });

    console.log('[walkthrough] collecting after traces');
    const after = [];
    for (const prompt of prompts) {
      after.push(await runUiPrompt(page, twin.id, prompt));
      await page.waitForTimeout(800);
    }

    const output = {
      executed_at: new Date().toISOString(),
      frontend_url: frontendUrl,
      backend_url: backendUrl,
      twin_id: twin.id,
      share_token_preview: safeTokenPreview(share.share_token || ''),
      prompts,
      before_legacy_path: before,
      after_public_simulator_ui: after,
    };

    const outDir = path.join(repoRoot, 'tmp');
    fs.mkdirSync(outDir, { recursive: true });
    const jsonPath = path.join(outDir, 'public_simulator_walkthrough.json');
    const mdPath = path.join(outDir, 'public_simulator_walkthrough.md');
    fs.writeFileSync(jsonPath, JSON.stringify(output, null, 2), 'utf8');

    const md = [
      `# Public Simulator Walkthrough`,
      ``,
      `- Executed at: ${output.executed_at}`,
      `- Frontend: ${frontendUrl}`,
      `- Backend: ${backendUrl}`,
      `- Twin ID: ${twin.id}`,
      `- Share token: ${output.share_token_preview}`,
      ``,
      `## Before (Legacy /chat/{twin})`,
      ...before.map(
        (r) =>
          `- \`${r.prompt}\` -> status ${r.status}, confidence=${r.confidence_score}, citations=${r.citations_count}, endpoint=\`${r.endpoint}\`\n  - assistant: ${JSON.stringify(r.assistant)}`
      ),
      ``,
      `## After (UI on /dashboard/simulator/public)`,
      ...after.map(
        (r) =>
          `- \`${r.prompt}\` -> status ${r.status}, endpoint_type=${r.endpoint_type}, confidence=${r.confidence_score}, citations=${r.citations_count}, queued=${r.queued}\n  - endpoint: \`${r.endpoint}\`\n  - assistant: ${JSON.stringify(r.assistant)}`
      ),
      ``,
    ].join('\n');
    fs.writeFileSync(mdPath, md, 'utf8');

    console.log(`WALKTHROUGH_JSON=${jsonPath}`);
    console.log(`WALKTHROUGH_MD=${mdPath}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
