import { NextResponse } from 'next/server';

import { chatReply } from '@/lib/experience/gemini';
import { clientIp } from '@/lib/experience/http';
import { CHAT_MESSAGE_LIMIT, getSession, rateLimit } from '@/lib/experience/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const ip = clientIp(req);
  if (!rateLimit(ip, 'chat', 40, 60 * 60 * 1000)) {
    return NextResponse.json({ error: 'Slow down a moment and try again.' }, { status: 429 });
  }

  let body: { token?: string; message?: string };
  try {
    body = (await req.json()) as { token?: string; message?: string };
  } catch {
    return NextResponse.json({ error: 'Invalid request.' }, { status: 400 });
  }

  const token = String(body.token ?? '');
  const message = String(body.message ?? '').trim().slice(0, 1000);
  if (!token || !message) {
    return NextResponse.json({ error: 'Missing token or message.' }, { status: 400 });
  }

  const session = getSession(token);
  if (!session) {
    return NextResponse.json({ error: 'Your demo session expired — start again.' }, { status: 404 });
  }
  if (session.msgCount >= CHAT_MESSAGE_LIMIT) {
    return NextResponse.json({ locked: true, chatLimit: CHAT_MESSAGE_LIMIT }, { status: 403 });
  }
  // Reserve the turn synchronously, before the Gemini await, so two concurrent
  // requests for the same token can't both read msgCount below the limit and
  // both slip through — the increment below has no await between it and the
  // check above, so it's atomic with respect to other request handlers.
  session.msgCount += 1;

  try {
    const reply = await chatReply(session.profile, session.history, message);
    session.history.push({ role: 'user', text: message }, { role: 'model', text: reply });
    const remaining = Math.max(0, CHAT_MESSAGE_LIMIT - session.msgCount);
    return NextResponse.json({ reply, remaining, locked: remaining === 0 });
  } catch (err) {
    session.msgCount -= 1; // the turn never happened — release the reservation
    console.error('[experience/chat] failed:', err);
    return NextResponse.json({ error: 'The persona had trouble replying. Try again.' }, { status: 500 });
  }
}
