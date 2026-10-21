'use client';

import React from 'react';

interface QuotaBlockedDialogProps {
  open: boolean;
  cap: number;
  onClose: () => void;
}

export function QuotaBlockedDialog({ open, cap, onClose }: QuotaBlockedDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full p-8 text-center">
        <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="text-xl font-black text-[#1C1917]">Monthly limit reached</h2>
        <p className="text-[#57534E] mt-2 text-sm leading-relaxed">
          You&apos;ve used all {cap.toLocaleString()} messages for this period.
          Upgrade to Pro for 5,000 messages/month, widget embed, lead capture, and voice calls.
        </p>
        <div className="mt-6 flex flex-col gap-2">
          <a
            href="/dashboard/billing"
            className="block w-full py-2.5 bg-[#0F766E] hover:bg-[#0D9488] text-white text-sm font-semibold rounded-xl transition-colors"
          >
            Upgrade to Pro →
          </a>
          <button
            onClick={onClose}
            className="w-full py-2.5 text-sm text-[#57534E] hover:text-[#1C1917] cursor-pointer"
          >
            Maybe later
          </button>
        </div>
      </div>
    </div>
  );
}
