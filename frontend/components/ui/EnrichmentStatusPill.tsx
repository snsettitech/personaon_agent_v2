'use client';

import { Circle } from 'lucide-react';
import { useEnrichmentStatus } from '@/lib/hooks/useEnrichmentStatus';
import { useTwin } from '@/lib/context/TwinContext';
import { formatStatus } from '@/lib/utils/formatStatus';

export function EnrichmentStatusPill() {
  const phase = useEnrichmentStatus();
  const { activeTwin } = useTwin();
  const status = formatStatus(activeTwin?.status);

  if (phase === 'queued') {
    return (
      <div
        className="hidden items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold md:flex"
        style={{ backgroundColor: '#e8f2ff', color: '#0b5cab' }}
        title="Enriching persona in the background"
      >
        <span className="h-2.5 w-2.5 animate-spin rounded-full border-[1.5px] border-[#0066cc] border-t-transparent" />
        Enriching…
      </div>
    );
  }

  if (phase === 'complete') {
    return (
      <div
        className="hidden items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold md:flex"
        style={{ backgroundColor: '#dcfce7', color: '#15803d' }}
      >
        <svg className="h-2.5 w-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
        </svg>
        Enriched!
      </div>
    );
  }

  return (
    <div
      className="hidden items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold md:flex"
      style={{ backgroundColor: status.background, color: status.color }}
      title={status.detail}
    >
      <Circle className="h-2.5 w-2.5 fill-current" />
      {status.label}
    </div>
  );
}
