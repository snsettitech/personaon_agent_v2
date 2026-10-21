import { readFileSync } from 'fs';
import { join } from 'path';

import { ImageResponse } from 'next/og';

// PersonaOn OpenGraph image — 1200x630 PNG generated at build time.
// Shown in social previews on Twitter/X, LinkedIn, Slack, iMessage,
// Discord, Telegram, Facebook, etc. when personaon.com is shared.
//
// The lockup is the official brand asset: we embed the white-on-ink
// PersonaOn lockup PNG from the brand kit (Satori can't render the
// gradient/mask SVG directly, so we use the rasterised export) on the
// --ink ground. --signal blue stays as the legitimate UI accent (pill,
// glow); the logo carries its own gradient inside the PNG.

export const alt = 'PersonaOn — your digital persona, always on';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

// Embedded once at module eval — the tight-cropped white lockup (1273×218).
// Fail-safe: if the asset isn't on disk (e.g. standalone server without
// public/), fall back to text rather than crashing the route at load.
function loadLockup(): string | null {
  try {
    return `data:image/png;base64,${readFileSync(
      join(process.cwd(), 'public/brand/wordmark-white.png'),
    ).toString('base64')}`;
  } catch (err) {
    console.error('[OG] white lockup asset missing — falling back to text', err);
    return null;
  }
}
const LOCKUP_DATA_URI = loadLockup();
const LOCKUP_H = 132;
const LOCKUP_W = Math.round((LOCKUP_H * 1273) / 218); // preserve aspect

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '80px',
          backgroundColor: '#1d1d1f',
          backgroundImage:
            'radial-gradient(circle at 85% 15%, rgba(0,102,204,0.40), transparent 55%)',
          color: '#f5f5f7',
        }}
      >
        {/* Top: small status pill (UI accent --signal, not the logo) */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '8px 16px',
            border: '1px solid rgba(245,245,247,0.16)',
            borderRadius: 9999,
            backgroundColor: 'rgba(245,245,247,0.06)',
            fontSize: 18,
            fontWeight: 600,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'rgba(245,245,247,0.72)',
            alignSelf: 'flex-start',
          }}
        >
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: 9999,
              backgroundColor: '#0066cc',
              boxShadow: '0 0 0 4px rgba(0,102,204,0.32)',
            }}
          />
          PERSONAON
        </div>

        {/* Middle: official lockup + tagline */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 36 }}>
          {LOCKUP_DATA_URI ? (
            // eslint-disable-next-line @next/next/no-img-element -- brand asset in ImageResponse
            <img
              src={LOCKUP_DATA_URI}
              alt="PersonaOn"
              width={LOCKUP_W}
              height={LOCKUP_H}
              style={{ display: 'block' }}
            />
          ) : (
            <div style={{ fontSize: 132, fontWeight: 600, color: '#f5f5f7', lineHeight: 1 }}>
              PersonaOn
            </div>
          )}
          <div
            style={{
              fontSize: 36,
              fontWeight: 400,
              lineHeight: 1.3,
              letterSpacing: '-0.015em',
              color: 'rgba(245,245,247,0.72)',
              maxWidth: 900,
            }}
          >
            Your digital persona, always on. Trained on approved context, ready to answer questions and join meetings as a named participant.
          </div>
        </div>

        {/* Bottom: domain */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            fontSize: 22,
            fontWeight: 500,
            color: 'rgba(245,245,247,0.40)',
          }}
        >
          personaon.com
        </div>
      </div>
    ),
    size,
  );
}
