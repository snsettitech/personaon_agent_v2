'use client';

import { useState } from 'react';
import type { Source } from '@/lib/types/source';
import { SOURCE_GROUP_CONFIG } from './SourceGroupConfig';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { API_ENDPOINTS } from '@/lib/constants';
import SourceContentPreview from './SourceContentPreview';

const fmtSize = (b: number) => !b || b <= 0 ? '—' : b < 1024 ? `${b} B` : b < 1048576 ? `${(b/1024).toFixed(1)} KB` : `${(b/1048576).toFixed(1)} MB`;
const fmtVec = (c?: number | null) => !c ? '—' : c * 4 < 1024 ? `${c * 4} KB` : `${(c * 4 / 1024).toFixed(1)} MB`;
const fmtDate = (d?: string | null) => !d ? '—' : new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

interface SourceDetailPanelProps {
  source: Source;
  onClose: () => void;
  onDelete: (sourceId: string) => void;
  onRetry: (sourceId: string) => void;
  onUpdate: (updated: Source) => void;
}

export default function SourceDetailPanel({ source, onClose, onDelete, onRetry, onUpdate }: SourceDetailPanelProps) {
  const config = SOURCE_GROUP_CONFIG[source.source_type] ?? SOURCE_GROUP_CONFIG.document;
  const isProfile = source.source_type === 'profile';
  const health = source.health_status ?? 'healthy';
  const isUnhealthy = ['failed', 'error', 'degraded'].includes(health);
  const canRetry = isUnhealthy || ['queued', 'failed', 'error'].includes(source.status ?? '');
  const healthColor = health === 'healthy' ? 'text-green-600 bg-green-50' : isUnhealthy ? 'text-red-600 bg-red-50' : 'text-yellow-600 bg-yellow-50';

  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState(source.filename);
  const [savingName, setSavingName] = useState(false);

  const handleSaveName = async () => {
    const trimmed = nameValue.trim();
    if (!trimmed || trimmed === source.filename) { setEditingName(false); return; }
    setSavingName(true);
    try {
      const res = await authFetchStandalone(API_ENDPOINTS.SOURCE_PATCH(source.id), { method: 'PATCH', body: JSON.stringify({ filename: trimmed }) });
      const json = await res.json();
      if (json.status === 'ok') onUpdate(json.data as Source);
      setEditingName(false);
    } catch (err) {
      console.error('[SourceDetailPanel] rename failed', err);
    } finally {
      setSavingName(false);
    }
  };

  const meta = [
    { label: 'Location', value: `Sources / ${config.label}` },
    { label: 'File Size', value: fmtSize(source.file_size) },
    { label: 'Vectors', value: source.chunk_count != null ? String(source.chunk_count) : '—' },
    { label: 'Vector Size', value: fmtVec(source.chunk_count) },
    { label: 'Created', value: fmtDate(source.created_at) },
    { label: 'Last Updated', value: fmtDate(source.last_event_at ?? source.created_at) },
  ];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/5" onClick={onClose} aria-hidden="true" />
      <div className="fixed right-0 top-0 h-full w-80 bg-white border-l border-slate-200 shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <span className={`text-xl w-9 h-9 flex items-center justify-center rounded-xl ${config.bgColor}`}>{config.icon}</span>
            <p className={`text-xs font-black uppercase tracking-widest ${config.color}`}>{config.label}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1.5 hover:bg-slate-100 rounded-lg transition-colors" aria-label="Close">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            {editingName ? (
              <div className="space-y-2">
                <input autoFocus value={nameValue} onChange={(e) => setNameValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSaveName(); if (e.key === 'Escape') { setEditingName(false); setNameValue(source.filename); } }}
                  className="w-full text-sm font-semibold text-slate-900 border border-blue-400 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
                <div className="flex gap-2">
                  <button onClick={handleSaveName} disabled={savingName} className="flex-1 py-1.5 bg-blue-600 text-white text-xs font-bold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">{savingName ? 'Saving…' : 'Save'}</button>
                  <button onClick={() => { setEditingName(false); setNameValue(source.filename); }} className="flex-1 py-1.5 border border-slate-200 text-slate-600 text-xs font-bold rounded-lg hover:bg-slate-50 transition-colors">Cancel</button>
                </div>
              </div>
            ) : (
              <div className="flex items-start gap-2 group">
                <p className="text-sm font-black text-slate-900 break-words leading-relaxed flex-1">{source.filename}</p>
                {!isProfile && (
                  <button onClick={() => { setEditingName(true); setNameValue(source.filename); }} className="shrink-0 mt-0.5 p-1 text-slate-400 hover:text-blue-500 hover:bg-blue-50 rounded transition-colors" title="Rename">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                  </button>
                )}
              </div>
            )}
          </div>

          <div>
            <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">Health</p>
            <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-black ${healthColor}`}>
              <span className="w-1.5 h-1.5 rounded-full bg-current" />{health.toUpperCase()}
            </span>
          </div>

          <div className="space-y-3 pt-2 border-t border-slate-100">
            {meta.map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-400">{label}</span>
                <span className="text-xs font-bold text-slate-700">{value}</span>
              </div>
            ))}
          </div>

          {source.citation_url && (
            <div className="pt-1">
              <a href={source.citation_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline">
                View original source
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
              </a>
            </div>
          )}

          {source.twin_id && !isProfile && (
            <SourceContentPreview twinId={source.twin_id} sourceId={source.id} />
          )}
        </div>

        {!isProfile && (
          <div className="p-6 border-t border-slate-100 space-y-2.5">
            {canRetry && (
              <button onClick={() => onRetry(source.id)} className="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-bold rounded-xl hover:bg-blue-700 transition-colors">Retry Ingestion</button>
            )}
            <button onClick={() => { onDelete(source.id); onClose(); }} className="w-full px-4 py-2.5 border border-red-200 text-red-600 text-sm font-bold rounded-xl hover:bg-red-50 transition-colors">Delete Source</button>
          </div>
        )}
      </div>
    </>
  );
}
