'use client';

import { useState, useMemo } from 'react';
import type { Source, SourceType } from '@/lib/types/source';
import { SOURCE_GROUP_CONFIG } from './SourceGroupConfig';

type SortKey = 'name' | 'updated' | 'created' | 'size' | 'vectors';
type SortDir = 'asc' | 'desc';
type ViewMode = 'list' | 'grid';

function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatVectorSize(chunks: number | null | undefined): string {
  if (!chunks) return '—';
  const kb = chunks * 4;
  return kb < 1024 ? `${kb} KB` : `${(kb / 1024).toFixed(1)} MB`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return (
    <svg className="w-3 h-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
    </svg>
  );
  return (
    <svg className="w-3 h-3 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5"
        d={dir === 'asc' ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} />
    </svg>
  );
}

interface SourceFileTableProps {
  folderType: SourceType;
  sources: Source[];
  selectedSourceId: string | null;
  onSelect: (source: Source) => void;
}

export default function SourceFileTable({ folderType, sources, selectedSourceId, onSelect }: SourceFileTableProps) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('updated');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [viewMode, setViewMode] = useState<ViewMode>('list');

  const config = SOURCE_GROUP_CONFIG[folderType];

  const sorted = useMemo(() => {
    const q = search.toLowerCase();
    const filtered = sources.filter((s) => !q || s.filename.toLowerCase().includes(q));
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'name') cmp = a.filename.localeCompare(b.filename);
      else if (sortKey === 'updated') cmp = (a.last_event_at ?? a.created_at ?? '').localeCompare(b.last_event_at ?? b.created_at ?? '');
      else if (sortKey === 'created') cmp = (a.created_at ?? '').localeCompare(b.created_at ?? '');
      else if (sortKey === 'size') cmp = (a.file_size ?? 0) - (b.file_size ?? 0);
      else if (sortKey === 'vectors') cmp = (a.chunk_count ?? 0) - (b.chunk_count ?? 0);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [sources, search, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('asc'); }
  };

  const col = (key: SortKey, label: string, cls: string) => (
    <button onClick={() => handleSort(key)}
      className={`${cls} flex items-center gap-1 text-[10px] font-black text-slate-400 uppercase tracking-widest hover:text-slate-600 transition-colors shrink-0`}>
      {label} <SortIcon active={sortKey === key} dir={sortDir} />
    </button>
  );

  return (
    <div>
      {/* Toolbar */}
      <div className="px-6 py-3 border-b border-slate-100 flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input type="text" placeholder="Search files…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" />
        </div>
        <span className="text-xs text-slate-400 font-medium">
          {sorted.length} file{sorted.length !== 1 ? 's' : ''}
        </span>
        {/* View toggle */}
        <div className="flex items-center bg-slate-100 rounded-lg p-0.5 ml-auto">
          {(['list', 'grid'] as ViewMode[]).map((m) => (
            <button key={m} onClick={() => setViewMode(m)}
              className={`px-2.5 py-1 rounded-md transition-all ${viewMode === m ? 'bg-white shadow-sm text-slate-700' : 'text-slate-400 hover:text-slate-600'}`}>
              {m === 'list' ? (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                </svg>
              )}
            </button>
          ))}
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-slate-400">No files match &ldquo;{search}&rdquo;</div>
      ) : viewMode === 'list' ? (
        <>
          {/* Column headers */}
          <div className="flex items-center px-4 py-2 border-b border-slate-100 bg-slate-50/60">
            <div className="w-10 shrink-0" />
            {col('name', 'Name', 'flex-1')}
            {col('updated', 'Updated', 'w-28')}
            {col('created', 'Created', 'w-28')}
            {col('size', 'Size', 'w-20 justify-end')}
            {col('vectors', 'Vector Size', 'w-24 justify-end pr-6')}
          </div>
          {sorted.map((source) => {
            const isSelected = source.id === selectedSourceId;
            const isHealthy = (source.health_status ?? 'healthy') === 'healthy';
            return (
              <button key={source.id} onClick={() => onSelect(source)}
                className={`w-full flex items-center px-4 border-b border-slate-50 last:border-0 text-left transition-colors ${isSelected ? 'bg-blue-50 hover:bg-blue-50' : 'hover:bg-slate-50/60'}`}>
                <div className="w-10 py-3.5 flex items-center justify-center shrink-0">
                  <span className="text-slate-300 text-sm">{config.icon}</span>
                </div>
                <div className="flex-1 min-w-0 py-3.5 pr-4">
                  <span className={`text-sm font-medium truncate block ${isSelected ? 'text-blue-700' : 'text-slate-700'}`}>{source.filename}</span>
                  {!isHealthy && <span className="text-[10px] font-bold text-red-400 mt-0.5 block">{source.health_status}</span>}
                </div>
                <div className="w-28 py-3.5 shrink-0"><span className="text-[11px] text-slate-400">{formatDate(source.last_event_at ?? source.created_at)}</span></div>
                <div className="w-28 py-3.5 shrink-0"><span className="text-[11px] text-slate-400">{formatDate(source.created_at)}</span></div>
                <div className="w-20 py-3.5 shrink-0 text-right"><span className="text-[11px] text-slate-400">{formatFileSize(source.file_size)}</span></div>
                <div className="w-24 py-3.5 shrink-0 text-right pr-6"><span className="text-[11px] text-slate-400">{formatVectorSize(source.chunk_count)}</span></div>
              </button>
            );
          })}
        </>
      ) : (
        /* Grid view */
        <div className="p-6 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
          {sorted.map((source) => {
            const isSelected = source.id === selectedSourceId;
            const isHealthy = (source.health_status ?? 'healthy') === 'healthy';
            return (
              <button key={source.id} onClick={() => onSelect(source)}
                className={`flex flex-col items-start gap-2 p-4 rounded-2xl border text-left transition-all ${isSelected ? 'border-blue-300 bg-blue-50' : 'border-slate-200 hover:border-blue-200 hover:bg-slate-50'}`}>
                <span className="text-2xl">{config.icon}</span>
                <p className="text-xs font-semibold text-slate-700 line-clamp-2 leading-relaxed w-full">{source.filename}</p>
                <div className="flex flex-col gap-1 w-full mt-auto">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">{formatFileSize(source.file_size)}</span>
                    {!isHealthy && <span className="text-[9px] font-bold text-red-400">{source.health_status}</span>}
                  </div>
                  <span className="text-[10px] text-slate-300">{formatDate(source.last_event_at ?? source.created_at)}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
