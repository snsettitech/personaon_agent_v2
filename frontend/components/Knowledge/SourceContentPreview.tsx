'use client';

import { useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { API_ENDPOINTS } from '@/lib/constants';

interface Chunk {
  id: string;
  content: string;
  privacy_level: string;
}

interface SourceContentPreviewProps {
  twinId: string;
  sourceId: string;
}

export default function SourceContentPreview({ twinId, sourceId }: SourceContentPreviewProps) {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setChunks([]);

    authFetchStandalone(API_ENDPOINTS.TWIN_SOURCE_CHUNKS(twinId, sourceId))
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled) setChunks(json.data ?? []);
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load content');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [twinId, sourceId]);

  return (
    <div className="pt-2 border-t border-slate-100">
      <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">Raw Content</p>

      {loading && (
        <div className="py-4 text-center text-xs text-slate-400">Loading…</div>
      )}

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}

      {!loading && !error && chunks.length === 0 && (
        <p className="text-xs text-slate-400">No content indexed yet.</p>
      )}

      {!loading && chunks.length > 0 && (
        <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-100 bg-slate-50 p-3 space-y-3">
          {chunks.map((chunk, i) => (
            <div key={chunk.id}>
              {i > 0 && <div className="border-t border-slate-200 mb-3" />}
              <p className="text-[11px] text-slate-600 leading-relaxed whitespace-pre-wrap break-words">
                {chunk.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
