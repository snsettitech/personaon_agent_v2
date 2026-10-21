'use client';

import { useEffect, useRef, useState } from 'react';
import { useTwin } from '@/lib/context/TwinContext';

export type EnrichmentPhase = 'idle' | 'queued' | 'complete';

export function useEnrichmentStatus(): EnrichmentPhase {
  const { activeTwin, refreshTwins } = useTwin();
  const [phase, setPhase] = useState<EnrichmentPhase>('idle');
  const prevStatus = useRef<string | null>(null);

  const settings = (activeTwin?.settings ?? {}) as Record<string, unknown>;
  const enrichmentStatus =
    typeof settings.enrichment_status === 'string'
      ? settings.enrichment_status
      : 'not_queued';

  useEffect(() => {
    if (enrichmentStatus === 'queued') {
      setPhase('queued');
    } else if (prevStatus.current === 'queued') {
      setPhase('complete');
      const t = setTimeout(() => setPhase('idle'), 3000);
      return () => clearTimeout(t);
    }
    prevStatus.current = enrichmentStatus;
  }, [enrichmentStatus]);

  useEffect(() => {
    if (enrichmentStatus !== 'queued') return;
    const id = setInterval(() => { refreshTwins().catch(() => {}); }, 8000);
    return () => clearInterval(id);
  }, [enrichmentStatus, refreshTwins]);

  return phase;
}
