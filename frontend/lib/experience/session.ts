import { randomUUID } from 'crypto';

import type { DemoProfile } from './types';

export const CHAT_MESSAGE_LIMIT = 4; // free demo turns before the wall
const TTL_MS = 45 * 60 * 1000; // 45 min — resumes are PII; hold briefly then drop

export interface ChatTurn {
  role: 'user' | 'model';
  text: string;
}

interface DemoSession {
  profile: DemoProfile;
  createdAt: number;
  ip: string;
  msgCount: number;
  history: ChatTurn[];
}

interface RateEntry {
  count: number;
  resetAt: number;
}

// Survive Next dev HMR by stashing on globalThis. Demo-grade only — single
// instance. KNOWN LIMITATION IN PRODUCTION: personaon-web/personaon-web-v2 run
// on Cloud Run with concurrency=80 and no max-instances cap, so under any load
// that triggers horizontal scale-out (or after a scale-to-zero cold start) a
// request can land on a fresh container with an empty store — sessions vanish
// mid-flow and the per-IP rate limit resets to zero. Acceptable for initial
// low-traffic launch; needs to move to Redis/Upstash before this surface sees
// real traffic volume.
interface DemoStore {
  sessions: Map<string, DemoSession>;
  rate: Map<string, RateEntry>;
}
const g = globalThis as unknown as { __personaonDemoStore?: DemoStore };
const store: DemoStore = (g.__personaonDemoStore ??= { sessions: new Map(), rate: new Map() });

// Independent of the (spoofable) per-IP rate limit — a hard ceiling on total
// concurrent demo sessions so a single process's memory can't be driven
// unbounded even if the per-IP limiter is bypassed.
const MAX_LIVE_SESSIONS = 2000;

function sweep(): void {
  const now = Date.now();
  for (const [token, session] of store.sessions) {
    if (now - session.createdAt > TTL_MS) store.sessions.delete(token);
  }
  for (const [id, entry] of store.rate) {
    if (now > entry.resetAt) store.rate.delete(id);
  }
}

export function createSession(profile: DemoProfile, ip: string): string | null {
  sweep();
  if (store.sessions.size >= MAX_LIVE_SESSIONS) return null;
  const token = randomUUID();
  store.sessions.set(token, { profile, createdAt: Date.now(), ip, msgCount: 0, history: [] });
  return token;
}

export function getSession(token: string): DemoSession | null {
  sweep();
  return store.sessions.get(token) ?? null;
}

/** Fixed-window per-IP limiter. Returns true if allowed. */
export function rateLimit(ip: string, bucket: string, max: number, windowMs: number): boolean {
  const id = `${bucket}:${ip}`;
  const now = Date.now();
  const cur = store.rate.get(id);
  if (!cur || now > cur.resetAt) {
    store.rate.set(id, { count: 1, resetAt: now + windowMs });
    return true;
  }
  if (cur.count >= max) return false;
  cur.count += 1;
  return true;
}
