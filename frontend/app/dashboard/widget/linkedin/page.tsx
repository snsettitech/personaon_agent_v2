'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { PersonaCard } from '@/components/share/PersonaCard';
import { CopyButton } from '@/components/share/CopyButton';
import { getLinkedInPostText, getLinkedInShareUrl, getShareUrl } from '@/lib/share/utils';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';

type Tab = 'post' | 'profile';

const PROFILE_STEPS = [
  'Log in to LinkedIn and click your profile photo in the top nav',
  'Click "View Profile"',
  'Scroll to the "Featured" section — click the + button (or "Add section" if Featured is not there)',
  'Choose "Links" → paste your share link → add a title like "Chat with my AI"',
  'Click Save',
];


export default function LinkedInPage() {
  const persona = useSharePersona();
  const [tab, setTab] = useState<Tab>('post');
  const [postText, setPostText] = useState<string | null>(null);

  useEffect(() => { analytics.shareStudioOpened('linkedin'); }, []);

  if (!persona) {
    return (
      <div className="p-8 text-center text-[#57534E]">
        Complete your profile to share on LinkedIn.
      </div>
    );
  }

  const defaultPostText = getLinkedInPostText(persona);
  const editablePost = postText ?? defaultPostText;
  const shareUrl = getShareUrl(persona.handle);
  const linkedInShareUrl = getLinkedInShareUrl(persona);

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">LinkedIn</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">LinkedIn</h1>
        <p className="text-[#57534E] mt-1">
          Share your AI persona with your professional network. Most views happen in the first 2 hours after posting.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[#F5F0EB] p-1 rounded-xl w-fit">
        {(['post', 'profile'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-sm font-semibold rounded-lg transition-all cursor-pointer ${
              tab === t ? 'bg-white text-[#1C1917] shadow-sm' : 'text-[#57534E] hover:text-[#1C1917]'
            }`}
          >
            {t === 'post' ? 'Post about it' : 'Add to profile'}
          </button>
        ))}
      </div>

      {tab === 'post' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
            {/* LinkedIn-style post header */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full overflow-hidden bg-gradient-to-br from-[#0F766E] to-[#0D9488] flex items-center justify-center text-white font-bold text-sm shrink-0">
                {persona.avatarUrl ? (
                  <img src={persona.avatarUrl} alt={persona.name} className="w-full h-full object-cover" />
                ) : (
                  <span>{persona.name.charAt(0).toUpperCase()}</span>
                )}
              </div>
              <div>
                <div className="text-sm font-semibold text-[#1C1917]">{persona.name}</div>
                <div className="text-xs text-[#57534E]">{persona.headline || 'LinkedIn Member'}</div>
              </div>
            </div>

            <textarea
              value={editablePost}
              onChange={(e) => setPostText(e.target.value)}
              rows={8}
              className="w-full text-sm text-[#374151] leading-relaxed resize-none border-0 focus:outline-none focus:ring-0 bg-transparent"
              placeholder="Write your post here…"
            />

            <div className="flex items-center justify-between pt-3 border-t border-[#F5F0EB]">
              <button
                type="button"
                onClick={() => setPostText(null)}
                disabled={postText === null}
                className="text-xs text-[#A8A29E] hover:text-[#57534E] cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Reset to default
              </button>
              <div className="flex gap-2">
                <CopyButton text={editablePost} label="Copy post" copiedLabel="Copied!" size="sm" variant="secondary" onCopied={() => analytics.shareActionCopied('linkedin', 'post')} />
                <a
                  href={linkedInShareUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => analytics.shareActionClicked('linkedin', 'post_on_linkedin')}
                  className="px-4 py-1.5 text-sm font-semibold bg-[#0A66C2] hover:bg-[#004182] text-white rounded-xl transition-colors"
                >
                  Post on LinkedIn ↗
                </a>
              </div>
            </div>
          </div>

          <p className="text-xs text-[#A8A29E]">
            The text is pre-written to feel authentic. Feel free to edit it — just keep the link.
          </p>
        </div>
      )}

      {tab === 'profile' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
            <div>
              <h2 className="text-base font-bold text-[#1C1917]">Add to your LinkedIn Profile</h2>
              <p className="text-sm text-[#57534E] mt-1">
                Adding your AI to the &quot;Featured&quot; section means every profile visitor can start chatting — forever, not just for a day after a post.
              </p>
            </div>

            {/* Copy link row */}
            <div className="flex items-center gap-3 bg-[#F5F0EB] rounded-xl p-3">
              <span className="text-xs font-mono text-[#1C1917] flex-1 truncate">{shareUrl}</span>
              <CopyButton text={shareUrl} label="Copy" copiedLabel="Copied!" size="sm" variant="secondary" onCopied={() => analytics.shareActionCopied('linkedin', 'link')} />
            </div>

            {/* Steps */}
            <ol className="space-y-3">
              {PROFILE_STEPS.map((step, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-[#0A66C2] text-white text-xs font-bold flex items-center justify-center mt-0.5">
                    {i + 1}
                  </span>
                  <span className="text-sm text-[#374151] leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
          </div>

          <p className="text-xs text-[#A8A29E]">
            Tip: Use &quot;Chat with my AI&quot; or &quot;Talk to my persona&quot; as the link title. Both perform well.
          </p>
        </div>
      )}

      {/* Persona card */}
      <div className="space-y-2">
        <p className="text-xs font-medium text-[#57534E]">Your AI persona</p>
        <PersonaCard persona={persona} size="sm" showUrl />
      </div>
    </div>
  );
}
