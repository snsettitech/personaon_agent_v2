import { NextResponse } from 'next/server';

import { DEMO_BUILD_LIMIT, buildQuotaCookie, quotaExceeded, readQuota } from '@/lib/experience/deviceLimit';
import { buildPreview, extractPersona } from '@/lib/experience/gemini';
import { clientIp } from '@/lib/experience/http';
import { extractResumeText, validateResume } from '@/lib/experience/resume';
import { createSession, rateLimit } from '@/lib/experience/session';

// pdf-parse / mammoth need the Node runtime; never run this on the edge.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface AnswerInput {
  prompt?: string;
  answer?: string;
}

export async function POST(req: Request) {
  const ip = clientIp(req);

  // Primary gate: per-browser build quota carried in a signed cookie. It is
  // stateless (the count lives in the cookie) so it survives Cloud Run scale-out,
  // unlike the in-memory per-IP limiter below.
  const quota = readQuota(req);
  if (quotaExceeded(quota)) {
    return NextResponse.json(
      {
        error: `You've used all ${DEMO_BUILD_LIMIT} free previews on this device. Sign up to keep building your persona.`,
        limit: true,
      },
      { status: 429 },
    );
  }

  // Secondary backstop: a looser per-IP ceiling to blunt scripted reuse from a
  // single network (cost control on an unauthenticated, Gemini-calling endpoint).
  // Not the user-facing limit — that's the quota above.
  if (!rateLimit(ip, 'analyze', 15, 60 * 60 * 1000)) {
    return NextResponse.json({ error: 'Too many demo builds from your network. Try again later.' }, { status: 429 });
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return NextResponse.json({ error: 'Invalid request.' }, { status: 400 });
  }

  const file = form.get('resume');
  if (!(file instanceof File)) {
    return NextResponse.json({ error: 'A resume file is required.' }, { status: 400 });
  }
  const validationError = validateResume({ type: file.type, size: file.size, name: file.name });
  if (validationError) {
    return NextResponse.json({ error: validationError }, { status: 400 });
  }

  let answers: { q: string; a: string }[] = [];
  const answersRaw = form.get('answers');
  if (typeof answersRaw === 'string') {
    try {
      const parsed = JSON.parse(answersRaw) as AnswerInput[];
      if (Array.isArray(parsed)) {
        answers = parsed
          .map((x) => ({ q: String(x.prompt ?? '').slice(0, 300), a: String(x.answer ?? '').trim().slice(0, 600) }))
          .filter((x) => x.a.length > 0)
          .slice(0, 10);
      }
    } catch (err) {
      // Malformed answers JSON — extraction still works from the resume alone.
      console.error('[experience/analyze] malformed answers payload:', err);
    }
  }

  const hintName = typeof form.get('name') === 'string' ? String(form.get('name')).trim().slice(0, 100) : '';

  try {
    const buffer = Buffer.from(await file.arrayBuffer());
    const { text, chars } = await extractResumeText(buffer, file.name, file.type);
    if (chars < 30) {
      return NextResponse.json(
        { error: "Couldn't read enough text from that resume. Try a different file." },
        { status: 422 },
      );
    }

    const profile = await extractPersona(text, answers, hintName);
    const token = createSession(profile, ip);
    if (!token) {
      return NextResponse.json(
        { error: 'The demo is at capacity right now — try again in a few minutes.' },
        { status: 503 },
      );
    }
    // Only the preview (the ~40% slice) crosses to the client; full profile stays server-side.
    const response = NextResponse.json({ token, preview: buildPreview(profile) });
    // Count this successful build against the per-browser quota (failed builds don't count).
    response.headers.set('Set-Cookie', buildQuotaCookie(quota));
    return response;
  } catch (err) {
    const missingKey = err instanceof Error && /GEMINI_API_KEY/.test(err.message);
    console.error('[experience/analyze] failed:', err);
    return NextResponse.json(
      { error: missingKey ? 'The demo server is missing its AI key.' : 'Failed to build your demo persona.' },
      { status: 500 },
    );
  }
}
