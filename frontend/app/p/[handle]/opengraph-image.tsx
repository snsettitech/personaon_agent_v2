import { readFileSync } from 'fs';
import { join } from 'path';

import { ImageResponse } from 'next/og';

import { getProfile } from '@/lib/seo/profiles';

// Generated social card for /p/[handle] — what a shared portfolio looks like
// on LinkedIn/X/iMessage. File-convention OG images take precedence over
// config metadata, so this replaces the old raw-avatar og:image.

export const revalidate = 3600;
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';
export const alt = 'PersonaOn portfolio card';

// Official PersonaOn lockup (color, tight-cropped 1273×218), embedded once.
// Satori can't render the gradient/mask SVG, so we use the kit PNG export.
// Fail-safe: this route is ISR (revalidate), so a missing asset must not
// crash the module — fall back to the brand text instead.
function loadWordmark(): string | null {
  try {
    return `data:image/png;base64,${readFileSync(
      join(process.cwd(), 'public/brand/wordmark.png'),
    ).toString('base64')}`;
  } catch (err) {
    console.error('[OG] persona lockup asset missing — falling back to text', err);
    return null;
  }
}
const WORDMARK_DATA_URI = loadWordmark();
const WORDMARK_H = 30;
const WORDMARK_W = Math.round((WORDMARK_H * 1273) / 218);

// The profile pack can carry fields at the top level or nested under
// `.profile` depending on the backend path — read both, like the page does.
function field(pack: Record<string, unknown>, key: string): string | undefined {
  const direct = pack[key];
  if (typeof direct === 'string' && direct.trim()) return direct.trim();
  const nested = (pack.profile as Record<string, unknown> | undefined)?.[key];
  if (typeof nested === 'string' && nested.trim()) return nested.trim();
  return undefined;
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max).trimEnd()}…` : text;
}

// next/og's bundled font only shapes Latin glyphs; Arabic/Hebrew/CJK/emoji
// throw at render time ("substFormat: 3 not supported") and would 500 the
// route. Strip text to the renderable Latin subset so a non-Latin name
// degrades to a clean card (handle + brand) instead of a broken preview.
function toRenderable(text: string): string {
  const stripped = text
    .replace(/[^ -ɏ‐-‧]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return stripped;
}

/** Fetch the avatar and inline it as a data URI; any failure → initials. */
async function avatarDataUri(url: string | undefined): Promise<string | null> {
  if (!url || !/^https?:\/\//.test(url)) return null;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2500) });
    if (!res.ok) return null;
    const type = res.headers.get('content-type') ?? '';
    if (!type.startsWith('image/')) return null;
    const buf = await res.arrayBuffer();
    if (buf.byteLength > 3_000_000) return null; // keep the card render fast
    return `data:${type};base64,${Buffer.from(buf).toString('base64')}`;
  } catch {
    return null;
  }
}

export default async function OgImage({
  params,
}: {
  params: Promise<{ handle: string }>;
}) {
  const { handle } = await params;
  const data = await getProfile(handle);

  const pack = (data?.profile ?? {}) as Record<string, unknown>;
  const rawName = field(pack, 'name') ?? field(pack, 'display_name') ?? 'PersonaOn';
  const rawHeadline = field(pack, 'occupation') ?? field(pack, 'headline') ?? '';
  // Render only glyphs the OG font can shape; a non-Latin name falls back to
  // the brand headline so the card is clean rather than broken.
  const safeName = toRenderable(rawName);
  const name = safeName || 'PersonaOn';
  const headline = toRenderable(rawHeadline);
  const avatar = await avatarDataUri(field(pack, 'image_url') ?? field(pack, 'avatar_url'));
  // Treat an un-renderable name like a generic card (no broken text block).
  const isGeneric = !data || !safeName;

  try {
    return buildCard({ name, headline, avatar, handle, isGeneric });
  } catch {
    // Last-resort guarantee: never 500 a share preview. Render the fully
    // generic brand card with zero dynamic text.
    return buildCard({ name: 'PersonaOn', headline: '', avatar: null, handle, isGeneric: true });
  }
}

function buildCard({
  name,
  headline,
  avatar,
  handle,
  isGeneric,
}: {
  name: string;
  headline: string;
  avatar: string | null;
  handle: string;
  isGeneric: boolean;
}) {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: 72,
          backgroundColor: '#f5f5f7',
          backgroundImage: 'linear-gradient(135deg, #f5f5f7 60%, #e3eefc 100%)',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
          {avatar ? (
            <img
              src={avatar}
              alt=""
              width={160}
              height={160}
              style={{ borderRadius: 48, objectFit: 'cover' }}
            />
          ) : (
            <div
              style={{
                width: 160,
                height: 160,
                borderRadius: 48,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: '#0066cc',
                color: '#ffffff',
                fontSize: 64,
                fontWeight: 700,
              }}
            >
              {isGeneric ? 'P' : initialsOf(name)}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 64, fontWeight: 700, color: '#111111', lineHeight: 1.1 }}>
              {isGeneric ? 'Your portfolio, but it answers' : truncate(name, 40)}
            </div>
            {!isGeneric && headline && (
              <div style={{ fontSize: 32, color: '#6e6e73' }}>{truncate(headline, 70)}</div>
            )}
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              fontSize: 30,
              color: '#0066cc',
              fontWeight: 600,
            }}
          >
            {isGeneric ? 'personaon.com' : 'Ask my page anything →'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ fontSize: 28, color: '#6e6e73' }}>
              {isGeneric ? '' : `personaon.com/p/${truncate(handle, 30)}`}
            </div>
            {WORDMARK_DATA_URI ? (
              // eslint-disable-next-line @next/next/no-img-element -- brand asset in ImageResponse
              <img
                src={WORDMARK_DATA_URI}
                alt="PersonaOn"
                width={WORDMARK_W}
                height={WORDMARK_H}
                style={{ display: 'block' }}
              />
            ) : (
              <div style={{ fontSize: 28, fontWeight: 700, color: '#111111' }}>PersonaOn</div>
            )}
          </div>
        </div>
      </div>
    ),
    size,
  );
}
