import { GoogleGenerativeAI } from '@google/generative-ai';

import { CHAT_MESSAGE_LIMIT, type ChatTurn } from './session';
import type { DemoPreview, DemoProfile, SampleQA } from './types';

const MODEL = process.env.GEMINI_MODEL || 'gemini-2.5-flash';

function genAI(): GoogleGenerativeAI {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error('GEMINI_API_KEY is not set — add it to frontend/.env.local.');
  return new GoogleGenerativeAI(key);
}

// ── coercion (never trust raw model JSON) ────────────────────────────
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');
const strArr = (v: unknown, limit: number): string[] =>
  Array.isArray(v)
    ? v.filter((x): x is string => typeof x === 'string' && x.trim().length > 0).map((x) => x.trim()).slice(0, limit)
    : [];
function objArr<T>(v: unknown, map: (o: Record<string, unknown>) => T, limit: number): T[] {
  if (!Array.isArray(v)) return [];
  return v
    .filter((o): o is Record<string, unknown> => !!o && typeof o === 'object' && !Array.isArray(o))
    .map(map)
    .slice(0, limit);
}

function coerceProfile(raw: Record<string, unknown>, fallbackName: string): DemoProfile {
  const sampleQA = objArr<SampleQA>(raw.sampleQA, (o) => ({ question: str(o.question), answer: str(o.answer) }), 3).filter(
    (x) => x.question && x.answer,
  );
  return {
    name: str(raw.name) || fallbackName || 'Your Persona',
    headline: str(raw.headline),
    occupation: str(raw.occupation),
    bio: str(raw.bio),
    speakingStyle: str(raw.speakingStyle),
    personalityTraits: strArr(raw.personalityTraits, 6),
    expertise: strArr(raw.expertise, 10),
    achievements: strArr(raw.achievements, 8),
    contributions: strArr(raw.contributions, 8),
    workExperience: objArr(
      raw.workExperience,
      (o) => ({ company: str(o.company), role: str(o.role), description: str(o.description), period: str(o.period) }),
      6,
    ),
    education: objArr(
      raw.education,
      (o) => ({ institution: str(o.institution), degree: str(o.degree), field: str(o.field), period: str(o.period) }),
      4,
    ),
    sampleQA,
    suggestedQuestions: strArr(raw.suggestedQuestions, 4),
  };
}

const EXTRACTION_INSTRUCTION = `You are PersonaOn's profile compiler. From the RESUME and QUESTIONNAIRE below,
produce a first-person digital-twin profile of THIS SPECIFIC PERSON. Return ONLY a JSON object (no markdown fences)
with EXACTLY these keys:
- name (string: the person's REAL full name, taken from the top/header of the resume. If the header letters are spaced out (e.g. "S A I N A T H  S E T T I"), reconstruct the normal name ("Sainath Setti"). This is a PERSON'S NAME — never a job title, role, or field.)
- headline (string, one line: the person's most SENIOR professional identity + focus — who they are at their most senior and highest-impact, not their most recent or most junior role)
- occupation (string: the primary professional identity, chosen by SENIORITY, SCOPE, IMPACT, and TENURE — not by the resume's summary line, keyword frequency, or the most recent job. If the career spans multiple domains, lead with the most senior / highest-impact one; do NOT reduce a senior engineer, leader, architect, or founder to a junior-sounding title.)
- bio (string: 2-4 sentence first-person summary reflecting the FULL arc — seniority, breadth, and signature achievements)
- speakingStyle (string: how this person communicates)
- personalityTraits (string[])
- expertise (string[], ordered with the most senior / highest-impact competency first)
- achievements (string[])
- contributions (string[])
- workExperience (array of {company, role, description, period}; include ALL substantial roles, most senior / highest-impact first)
- education (array of {institution, degree, field, period})
- sampleQA (array of EXACTLY 3 {question, answer}; answers written in FIRST PERSON as this person, grounded in the resume; draw at least one from the person's most senior / highest-impact role, and attribute each achievement to the CORRECT employer)
- suggestedQuestions (array of 4 short questions a visitor might ask this persona)

Rules: ground every fact in the resume/answers; NEVER invent employers, titles, dates, or credentials; if something
is unknown, omit it rather than fabricate; keep arrays concise and specific. Weight SENIORITY, SCOPE, and BUSINESS
IMPACT over recency and the self-summary when choosing the identity.`;

export async function extractPersona(
  resumeText: string,
  answers: { q: string; a: string }[],
  hintName: string,
): Promise<DemoProfile> {
  const model = genAI().getGenerativeModel({
    model: MODEL,
    // temperature 0: identity extraction must be deterministic and grounded — no
    // creative drift that mis-frames seniority or fabricates/blends achievements.
    generationConfig: { responseMimeType: 'application/json', temperature: 0 },
  });
  const qa = answers.map((x) => `Q: ${x.q}\nA: ${x.a}`).join('\n\n');
  const prompt = `${EXTRACTION_INSTRUCTION}\n\n=== RESUME ===\n${resumeText || '(none provided)'}\n\n=== QUESTIONNAIRE ===\n${qa || '(none)'}`;
  const res = await model.generateContent(prompt);
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(res.response.text()) as Record<string, unknown>;
  } catch (err) {
    console.error('[experience/gemini] extractPersona: failed to parse model JSON:', err);
    // Surface this as a failure rather than silently returning a near-empty
    // profile as a fake HTTP 200 success — the caller's catch block turns
    // this into a proper error response.
    throw new Error('Gemini returned an unparsable profile response.');
  }
  return coerceProfile(raw, hintName);
}

/** Truncate to a short gist with an ellipsis — used for the partial-reveal teasers. */
function clip(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? `${t.slice(0, max).trimEnd()}…` : t;
}

/** The ~40% slice + locked counts + short teasers. Full content stays server-side. */
export function buildPreview(profile: DemoProfile): DemoPreview {
  const teaser = profile.expertise.length
    ? `Your twin can speak to ${profile.expertise.slice(0, 3).join(', ')}${profile.expertise.length > 3 ? ', and more' : ''}.`
    : 'Your twin is ready to represent your background.';
  const firstQA: SampleQA = profile.sampleQA[0] ?? {
    question: 'What do you do?',
    answer: profile.bio || profile.headline || '',
  };
  const firstWork = profile.workExperience[0];
  const firstEdu = profile.education[0];
  return {
    name: profile.name,
    headline: profile.headline,
    knowsTeaser: teaser,
    expertisePreview: profile.expertise.slice(0, 2),
    sampleQA: firstQA,
    suggestedQuestions: profile.suggestedQuestions.slice(0, 4),
    locked: {
      expertise: Math.max(0, profile.expertise.length - 2),
      achievements: profile.achievements.length,
      contributions: profile.contributions.length,
      workExperience: profile.workExperience.length,
      education: profile.education.length,
      hasBio: Boolean(profile.bio),
      hasVoice: Boolean(profile.speakingStyle),
    },
    // A gist of each locked section — the FIRST item, shown fuller (a couple of
    // sentences) so the card has something to expand into via the "i" button. The
    // remaining items and the other sections' full content still stay server-side;
    // this is the intentional partial reveal, enough to entice, not the whole value.
    teasers: {
      bio: profile.bio ? clip(profile.bio, 260) : undefined,
      work: firstWork
        ? clip(
            [firstWork.role, firstWork.company].filter(Boolean).join(' · ') +
              (firstWork.description ? ` — ${firstWork.description}` : ''),
            180,
          ) || undefined
        : undefined,
      achievement: profile.achievements[0] ? clip(profile.achievements[0], 150) : undefined,
      education: firstEdu
        ? [firstEdu.degree, firstEdu.field, firstEdu.institution].filter(Boolean).join(' · ') || undefined
        : undefined,
      contribution: profile.contributions[0] ? clip(profile.contributions[0], 150) : undefined,
      voice: profile.speakingStyle ? clip(profile.speakingStyle, 150) : undefined,
    },
    chatLimit: CHAT_MESSAGE_LIMIT,
  };
}

function chatSystemInstruction(p: DemoProfile): string {
  const facts = {
    name: p.name,
    headline: p.headline,
    occupation: p.occupation,
    bio: p.bio,
    expertise: p.expertise,
    achievements: p.achievements,
    contributions: p.contributions,
    workExperience: p.workExperience,
    education: p.education,
    personalityTraits: p.personalityTraits,
  };
  return `You ARE the AI digital twin of ${p.name}. Speak in the FIRST PERSON as ${p.name}, in their voice: ${
    p.speakingStyle || 'clear, warm, and professional'
  }.
Ground every answer ONLY in the profile facts below. If asked something the profile does not cover, say warmly that
it is not something you have shared here and offer to connect after sign-up — never invent facts, employers, or dates.
Keep replies to 2-4 sentences.

PROFILE (JSON):
${JSON.stringify(facts)}`;
}

export async function chatReply(profile: DemoProfile, history: ChatTurn[], message: string): Promise<string> {
  const model = genAI().getGenerativeModel({
    model: MODEL,
    systemInstruction: chatSystemInstruction(profile),
    generationConfig: { temperature: 0.7, maxOutputTokens: 400 },
  });
  const contents = [
    ...history.map((h) => ({ role: h.role, parts: [{ text: h.text }] })),
    { role: 'user' as const, parts: [{ text: message }] },
  ];
  const res = await model.generateContent({ contents });
  return res.response.text().trim();
}
