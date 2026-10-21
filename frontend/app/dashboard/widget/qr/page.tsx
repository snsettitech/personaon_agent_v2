'use client';

import React, { useEffect } from 'react';
import Link from 'next/link';
import { QRCodeDisplay } from '@/components/share/QRCodeDisplay';
import { CopyButton } from '@/components/share/CopyButton';
import { getShareUrl } from '@/lib/share/utils';
import { useSharePersona } from '@/lib/share/useSharePersona';
import { analytics } from '@/lib/analytics/events';


export default function QRPage() {
  const persona = useSharePersona();

  useEffect(() => { analytics.shareStudioOpened('qr'); }, []);

  if (!persona) {
    return <div className="p-8 text-center text-[#57534E]">Complete your profile to generate your QR code.</div>;
  }

  const shareUrl = getShareUrl(persona.handle);

  const handlePrint = () => {
    const card = document.getElementById('print-card');
    if (!card) return;
    const printWindow = window.open('', '_blank', 'width=600,height=400');
    if (!printWindow) return;
    printWindow.document.write(`<!DOCTYPE html><html><head><title>QR Code</title><style>
    body { margin: 0; padding: 0.25in; font-family: Arial, sans-serif; }
    img { max-width: 100%; }
    @media print { @page { size: 3.5in 2in; margin: 0; } body { padding: 0.1in; } }
  </style></head><body>${card.innerHTML}</body></html>`);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => { printWindow.print(); printWindow.close(); }, 300);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-[#A8A29E]">
        <Link href="/dashboard/widget" className="hover:text-[#0F766E] transition-colors">Share Studio</Link>
        <span aria-hidden="true">→</span>
        <span className="text-[#1C1917] font-medium">QR Code &amp; Print</span>
      </div>

      <div>
        <h1 className="text-2xl font-black tracking-tight text-[#1C1917]">QR Code &amp; Print</h1>
        <p className="text-[#57534E] mt-1">
          Use your QR code on business cards, slide decks, event badges, conference posters — anywhere people can&apos;t click.
        </p>
      </div>

      {/* QR display */}
      <div className="bg-white rounded-2xl border border-[#E7E5E4] p-8 flex flex-col items-center gap-6">
        <QRCodeDisplay url={shareUrl} size={240} personaName={persona.name} showDownload onDownload={() => analytics.qrDownloaded('png')} />
        <div className="text-center space-y-1">
          <div className="text-sm font-semibold text-[#1C1917]">{persona.name}</div>
          {persona.headline && <div className="text-xs text-[#57534E]">{persona.headline}</div>}
          <div className="text-xs font-mono text-[#A8A29E]">{shareUrl}</div>
        </div>
      </div>

      {/* Copy link */}
      <div className="flex items-center gap-3 bg-[#F5F0EB] rounded-xl p-4">
        <span className="text-sm font-mono text-[#1C1917] flex-1 truncate">{shareUrl}</span>
        <CopyButton text={shareUrl} label="Copy link" copiedLabel="Copied!" size="sm" variant="secondary" onCopied={() => analytics.shareActionCopied('qr', 'link')} />
      </div>

      {/* Print card */}
      <div className="bg-white rounded-2xl border border-[#E7E5E4] p-5 space-y-4">
        <div>
          <h2 className="text-base font-bold text-[#1C1917]">Print-ready card</h2>
          <p className="text-sm text-[#57534E] mt-1">
            Opens a print dialog with a business-card–sized layout. Use &quot;Save as PDF&quot; in the print dialog to save to file.
          </p>
        </div>

        {/* Print preview */}
        <div
          id="print-card"
          className="border-2 border-dashed border-[#E7E5E4] rounded-2xl p-6 flex items-center gap-6"
        >
          <div className="flex flex-col items-center gap-2 shrink-0">
            <QRCodeDisplay url={shareUrl} size={100} personaName={persona.name} showDownload={false} />
          </div>
          <div className="space-y-1">
            {persona.avatarUrl && (
              <img src={persona.avatarUrl} alt={persona.name} className="w-10 h-10 rounded-full object-cover mb-2" />
            )}
            <div className="text-base font-bold text-[#1C1917]">{persona.name}</div>
            {persona.headline && <div className="text-sm text-[#57534E]">{persona.headline}</div>}
            <div className="text-xs text-[#0F766E] font-medium mt-2">Chat with my AI →</div>
            <div className="text-xs font-mono text-[#A8A29E]">{shareUrl}</div>
          </div>
        </div>

        <button
          type="button"
          onClick={handlePrint}
          className="px-5 py-2.5 text-sm font-semibold bg-[#1C1917] hover:bg-[#374151] text-white rounded-xl transition-colors cursor-pointer"
        >
          🖨️ Open print dialog
        </button>
      </div>

      {/* Use cases */}
      <div className="grid sm:grid-cols-3 gap-3">
        {[
          { icon: '💼', label: 'Business cards', tip: 'Add to the back of your business card' },
          { icon: '📊', label: 'Slide decks', tip: 'Last slide: "Scan to chat with my AI"' },
          { icon: '🎫', label: 'Event badges', tip: 'Conference lanyards and name tags' },
        ].map((item) => (
          <div key={item.label} className="bg-[#F8FAFC] rounded-xl p-4 text-center space-y-1">
            <div className="text-xl" aria-hidden="true">{item.icon}</div>
            <div className="text-sm font-semibold text-[#1C1917]">{item.label}</div>
            <div className="text-xs text-[#57534E]">{item.tip}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
