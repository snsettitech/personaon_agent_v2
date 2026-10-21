'use client';

import React from 'react';
import type { SharePersona } from '@/lib/share/utils';
import { getShareUrl } from '@/lib/share/utils';

interface PersonaCardProps {
  persona: SharePersona;
  size?: 'sm' | 'md';
  showUrl?: boolean;
}

function Initials({ name }: { name: string }) {
  const parts = name.split(/\s+/).filter(Boolean).slice(0, 2);
  const text = parts.map((p) => p[0]?.toUpperCase() ?? '').join('');
  return (
    <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-[#0F766E] to-[#0D9488] rounded-full">
      <span className="text-white font-bold">{text}</span>
    </div>
  );
}

export function PersonaCard({ persona, size = 'md', showUrl = true }: PersonaCardProps) {
  const url = getShareUrl(persona.handle);
  const avatarSize = size === 'sm' ? 'w-10 h-10 text-base' : 'w-14 h-14 text-xl';
  const nameSize = size === 'sm' ? 'text-base' : 'text-lg';
  const headlineSize = size === 'sm' ? 'text-xs' : 'text-sm';

  return (
    <div className={`bg-white rounded-2xl border border-[#E7E5E4] shadow-sm overflow-hidden ${size === 'sm' ? 'p-4' : 'p-5'}`}>
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className={`${avatarSize} rounded-full overflow-hidden shrink-0`}>
          {persona.avatarUrl ? (
            <img
              src={persona.avatarUrl}
              alt={persona.name}
              className="w-full h-full object-cover"
            />
          ) : (
            <Initials name={persona.name} />
          )}
        </div>
        <div className="min-w-0">
          <div className={`${nameSize} font-bold text-[#1C1917] truncate`}>{persona.name}</div>
          {persona.headline && (
            <div className={`${headlineSize} text-[#57534E] truncate mt-0.5`}>{persona.headline}</div>
          )}
        </div>
      </div>

      {/* CTA bar */}
      {size === 'md' && showUrl && (
        <div className="mt-4 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <div className="text-xs text-[#A8A29E] mb-1">Your public link</div>
            <div className="text-xs font-mono text-[#1C1917] truncate">{url}</div>
          </div>
          <div className="w-8 h-8 rounded-full bg-[#0F766E] flex items-center justify-center shrink-0">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </div>
        </div>
      )}

      {showUrl && size === 'md' && (
        <div className="mt-3 pt-3 border-t border-[#F5F0EB]">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-[#0F766E] hover:underline font-medium"
          >
            Preview live page →
          </a>
        </div>
      )}
    </div>
  );
}
