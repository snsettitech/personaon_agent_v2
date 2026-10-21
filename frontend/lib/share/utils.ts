import { PUBLIC_SITE_URL } from '@/lib/constants';

function escHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export interface SharePersona {
  name: string;
  headline: string;
  avatarUrl: string;
  handle: string;
}

export function getShareUrl(handle: string): string {
  const base = PUBLIC_SITE_URL.replace(/\/$/, '');
  return `${base}/p/${encodeURIComponent(handle)}`;
}

export function getEmailSignatureHtml(persona: SharePersona, _platform?: 'gmail' | 'outlook' | 'apple'): string {
  const url = getShareUrl(persona.handle);
  const avatarHtml = persona.avatarUrl
    ? `<img src="${escHtml(persona.avatarUrl)}" width="44" height="44" style="border-radius:50%;object-fit:cover;display:block;" alt="${escHtml(persona.name)}" />`
    : `<div style="width:44px;height:44px;border-radius:50%;background:#0F766E;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;font-family:Arial,sans-serif;">${escHtml(persona.name.charAt(0).toUpperCase())}</div>`;

  return `<table cellpadding="0" cellspacing="0" border="0" style="font-family:Arial,Helvetica,sans-serif;">
  <tr>
    <td style="padding-right:12px;vertical-align:top;">
      ${avatarHtml}
    </td>
    <td style="vertical-align:top;">
      <div style="font-size:15px;font-weight:700;color:#1C1917;line-height:1.2;">${escHtml(persona.name)}</div>
      <div style="font-size:12px;color:#57534E;margin-top:2px;">${escHtml(persona.headline)}</div>
      <div style="margin-top:6px;">
        <a href="${escHtml(url)}" style="display:inline-block;padding:5px 14px;background:#0F766E;color:#fff;text-decoration:none;border-radius:6px;font-size:11px;font-weight:600;font-family:Arial,sans-serif;">
          Chat with my AI &#8599;
        </a>
      </div>
    </td>
  </tr>
</table>`;
}

export function getLinkedInPostText(persona: SharePersona): string {
  const url = getShareUrl(persona.handle);
  return `🤖 I built an AI version of myself — and it actually sounds like me.

Ask it anything about my work, background, or thinking.

Try it: ${url}

(Powered by @PersonaOn)`;
}

export function getSocialBioText(persona: SharePersona): string {
  return `Chat with my AI: ${getShareUrl(persona.handle)}`;
}

export function getXIntentUrl(persona: SharePersona): string {
  const text = encodeURIComponent(
    `I built an AI version of myself with @PersonaOn — ask it anything about me.\n\n${getShareUrl(persona.handle)}`
  );
  return `https://twitter.com/intent/tweet?text=${text}`;
}

export function getLinkedInShareUrl(persona: SharePersona): string {
  const url = encodeURIComponent(getShareUrl(persona.handle));
  const title = encodeURIComponent(`Chat with ${persona.name}'s AI`);
  const summary = encodeURIComponent(getLinkedInPostText(persona));
  return `https://www.linkedin.com/sharing/share-offsite/?url=${url}&title=${title}&summary=${summary}`;
}

export function getWebsiteSnippet(apiKey: string): string {
  return `<script src="https://personaon.com/widget.js" data-key="${escHtml(apiKey)}"></script>`;
}
