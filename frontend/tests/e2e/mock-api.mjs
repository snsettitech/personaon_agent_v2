// Minimal mock backend for Playwright e2e runs.
//
// The /p/[handle] page fetches the profile pack SERVER-SIDE (Next.js SSR),
// which Playwright's page.route() cannot intercept — so mocked specs need a
// real HTTP endpoint. playwright.config.ts starts this alongside `next dev`
// and points NEXT_PUBLIC_API_URL / NEXT_PUBLIC_BACKEND_URL at it.
//
// Tier is encoded in the handle: any handle ending in `-core` returns a paid
// ("core") profile pack; everything else is free tier.

import { createServer } from 'node:http';

const PORT = Number(process.env.MOCK_API_PORT || 8000);

const MOCK_TWIN_ID = 'test-twin-id-persona';
const MOCK_SHARE_TOKEN = 'test-share-token';

const PROFILE_FIELDS = {
  name: 'Jane Smith',
  occupation: 'Product Leader at Acme',
  bio: 'Experienced product leader with 15 years in tech.',
  headline: 'Product Leader at Acme - Ex-Google - 3x Founder',
  areas_of_expertise: ['Product Strategy', 'Growth', 'Leadership'],
  key_achievements: ['Led $50M product line', 'Grew team from 5 to 50'],
  work_experience: [
    { company: 'Acme', role: 'VP Product', description: 'Led product org' },
  ],
  education: [{ institution: 'Stanford', degree: 'MBA', field: 'Business' }],
  social_links: { linkedin: 'https://linkedin.com/in/janesmith' },
  suggested_questions: [
    'What do you do?',
    'Tell me about your experience',
    'How can you help me?',
    'What is your leadership style?',
  ],
};

// Hostile-content fixture: everything a malicious or messy real-world resume
// could throw at the page. The page must render it inert and unbroken.
const HOSTILE_FIELDS = {
  name: 'ال🎯 Ünïcôdé <script>alert(1)</script>',
  occupation: 'CEO of <img src=x onerror=alert(2)> & "Quotes" Pty',
  bio: `[click me](javascript:alert(3)) <iframe src="https://evil.example"></iframe> ${'overflowingunbrokentoken'.repeat(16)}`,
  areas_of_expertise: ['<b>bold?</b>', '🧨', 'נדל"ן ויזמות', `${'x'.repeat(220)}`],
  key_achievements: Array.from({ length: 8 }, (_, i) => `Achievement ${i} <svg onload=alert(4)>`),
  work_experience: Array.from({ length: 12 }, (_, i) => ({
    company: i === 0 ? 'Evil<script>alert(5)</script> Corp' : `Company ${i}`,
    role: i === 0 ? `${'longrole'.repeat(30)}` : `Role ${i}`,
    description: 'Did things & "stuff" — twice.',
    start_year: 2010 + i,
    end_year: 2011 + i,
  })),
  education: [{ institution: 'École 🏫', degree: '<u>PhD</u>', field: 'Tëst' }],
  social_links: { website: 'javascript:alert(6)', linkedin: 'https://linkedin.com/in/x' },
  suggested_questions: ['What do you do?'],
};

// Thin fixture: a brand-new user with almost nothing — the page must not
// look broken or print undefined/null.
const EMPTY_FIELDS = { name: 'Min Imal' };

function profilePack(handle) {
  const tier = handle.endsWith('-core') ? 'core' : 'free';
  const fields = handle.startsWith('edge-hostile')
    ? HOSTILE_FIELDS
    : handle.startsWith('edge-empty')
      ? EMPTY_FIELDS
      : PROFILE_FIELDS;
  return {
    twin_id: MOCK_TWIN_ID,
    handle,
    share_token: MOCK_SHARE_TOKEN,
    is_indexable: false,
    last_modified: new Date().toISOString(),
    profile: {
      profile: fields,
      settings: { subscription_tier: tier },
    },
  };
}

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

const server = createServer((req, res) => {
  const url = new URL(req.url || '/', `http://localhost:${PORT}`);
  const path = url.pathname;

  // GET /handles/resolve?handle=X — client-side fallback resolution.
  // Handles starting with "nonexistent" 404 so specs can exercise the
  // not-found path end-to-end.
  if (path === '/handles/resolve') {
    const handle = url.searchParams.get('handle') || '';
    if (handle.startsWith('nonexistent')) {
      return json(res, 404, { detail: 'Handle not found' });
    }
    return json(res, 200, { twin_id: MOCK_TWIN_ID, share_token: MOCK_SHARE_TOKEN });
  }

  // GET /handles/:handle/profile — SSR profile pack
  const handleProfile = path.match(/^\/handles\/([^/]+)\/profile$/);
  if (handleProfile) {
    const handle = decodeURIComponent(handleProfile[1]);
    if (handle.startsWith('nonexistent')) {
      return json(res, 404, { detail: 'Handle not found' });
    }
    return json(res, 200, profilePack(handle));
  }

  // GET /share/:twinId/:token/profile — client-side share-page profile
  const shareProfile = path.match(/^\/share\/([^/]+)\/([^/]+)\/profile$/);
  if (shareProfile) {
    return json(res, 200, {
      profile: PROFILE_FIELDS,
      settings: { subscription_tier: 'free' },
    });
  }

  // POST /v2/chat/public/... — non-streaming chat fallback (most chat specs
  // intercept client-side with page.route; this is a safety net).
  if (path.startsWith('/v2/chat/')) {
    return json(res, 200, {
      message: 'Mock response from the persona.',
      conversation_id: 'mock-conversation-id',
      citations: [],
    });
  }

  // GET /health — webServer readiness probe
  if (path === '/health') {
    return json(res, 200, { status: 'ok' });
  }

  return json(res, 404, { detail: `mock-api: no route for ${path}` });
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console -- test infra startup log, not app code
  console.log(`[mock-api] listening on http://localhost:${PORT}`);
});
