'use client';

import React from 'react';

interface VoiceToggleProps {
  enabled: boolean;
  onToggle: () => void;
}

export default function VoiceToggle({ enabled, onToggle }: VoiceToggleProps) {
  return (
    <button
      onClick={onToggle}
      aria-label={enabled ? 'Disable auto-play voice' : 'Enable auto-play voice'}
      title={enabled ? 'Voice ON — auto-playing responses' : 'Voice OFF'}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-wider transition-all border cursor-pointer ${
        enabled
          ? 'bg-[#eef5ff] text-[#0066cc] border-[#0066cc]/20 shadow-sm'
          : 'bg-white/60 text-slate-400 border-white/60 hover:text-slate-600 hover:bg-[#f1efec]'
      }`}
    >
      {/* Speaker icon */}
      <svg
        className={`w-3.5 h-3.5 ${enabled ? 'text-[#0066cc]' : ''}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
        />
      </svg>
      <span>Voice</span>
      <span
        className={`inline-block w-6 h-3.5 rounded-full relative transition-colors ${
          enabled ? 'bg-[#0066cc]' : 'bg-slate-300'
        }`}
      >
        <span
          className={`absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white shadow-sm transition-transform ${
            enabled ? 'translate-x-3' : 'translate-x-0.5'
          }`}
        />
      </span>
    </button>
  );
}
