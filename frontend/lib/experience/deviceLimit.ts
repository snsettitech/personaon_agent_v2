import { createHmac, timingSafeEqual } from 'crypto';

// Per-browser free-demo quota, carried in a signed HttpOnly cookie.
//
// Why a cookie and not the in-memory per-IP map in session.ts: PersonaOn runs on
// Cloud Run with horizontal scale-out, so an in-memory counter resets whenever a
// request lands on a fresh container (see the KNOWN LIMITATION note in
// session.ts). The count here travels *inside* the cookie, so it is stateless —
// it survives scale-out and cold starts with no shared store (Redis) needed.
//
// This is deliberately a SOFT gate. An unauthenticated visitor can always bypass
// it with a new browser, incognito, or by clearing cookies — that is the accepted
// ceiling for a no-signup demo. The goal is to nudge signup after a couple of
// tries, not to be unbypassable. The IP limiter in the analyze route stays on as
// a looser abuse ceiling for scripted reuse from one network.

export const DEMO_BUILD_LIMIT = 2;
const COOKIE_NAME = 'pon_demo';
const WINDOW_MS = 30 * 24 * 60 * 60 * 1000; // 30 days, measured from the first build

// A dedicated secret makes the count unforgeable from devtools. If it is not
// provisioned the cookie still functions (readable/writable) but is not
// cryptographically protected — combined with the IP backstop that is an
// acceptable degraded mode for local/dev. Set DEMO_LIMIT_SECRET in prod.
const SECRET = process.env.DEMO_LIMIT_SECRET || 'personaon-demo-dev-unsigned';
const IS_PROD = process.env.NODE_ENV === 'production';

export interface DemoQuota {
  count: number;
  firstAt: number;
}

function sign(payload: string): string {
  return createHmac('sha256', SECRET).update(payload).digest('base64url');
}

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

function fresh(): DemoQuota {
  return { count: 0, firstAt: Date.now() };
}

/** Read + verify the quota cookie. Tampering, corruption, or an elapsed window
 *  all fall back to a fresh (zero-use) quota. */
export function readQuota(req: Request): DemoQuota {
  const header = req.headers.get('cookie');
  if (!header) return fresh();
  const match = header.match(/(?:^|;\s*)pon_demo=([^;]+)/);
  if (!match) return fresh();
  const [payload, sig] = decodeURIComponent(match[1]).split('.');
  if (!payload || !sig || !safeEqual(sig, sign(payload))) return fresh();
  try {
    const parsed = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as Partial<DemoQuota>;
    const firstAt = Number(parsed.firstAt) || Date.now();
    if (Date.now() - firstAt > WINDOW_MS) return fresh(); // window elapsed → reset
    return { count: Math.max(0, Number(parsed.count) || 0), firstAt };
  } catch {
    return fresh();
  }
}

export function quotaExceeded(quota: DemoQuota): boolean {
  return quota.count >= DEMO_BUILD_LIMIT;
}

export function remainingBuilds(quota: DemoQuota): number {
  return Math.max(0, DEMO_BUILD_LIMIT - quota.count);
}

/** Serialize the NEXT quota (i.e. this build counted) into a Set-Cookie value.
 *  Call only after a build actually succeeds so failed builds don't burn a use. */
export function buildQuotaCookie(quota: DemoQuota): string {
  const next: DemoQuota = { count: quota.count + 1, firstAt: quota.firstAt || Date.now() };
  const payload = Buffer.from(JSON.stringify(next)).toString('base64url');
  const value = encodeURIComponent(`${payload}.${sign(payload)}`);
  const maxAgeSec = Math.floor(WINDOW_MS / 1000);
  // Secure is omitted in dev so the cookie works over http://localhost.
  return `${COOKIE_NAME}=${value}; Path=/; Max-Age=${maxAgeSec}; HttpOnly; SameSite=Lax${IS_PROD ? '; Secure' : ''}`;
}
