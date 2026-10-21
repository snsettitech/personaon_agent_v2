'use client';

import { useState, useMemo } from 'react';
import type { Source, SourceType } from '@/lib/types/source';
import { SOURCE_GROUP_CONFIG, SOURCE_GROUP_ORDER } from './SourceGroupConfig';

type SortKey = 'name' | 'files' | 'size' | 'updated';
type SortDir = 'asc' | 'desc';

function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

interface SourceFolderGridProps {
  groupedSources: Record<string, Source[]>;
  onOpenFolder: (type: SourceType) => void;
}

export default function SourceFolderGrid({ groupedSources, onOpenFolder }: SourceFolderGridProps) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const folders = useMemo(() =>
    SOURCE_GROUP_ORDER
      .filter((t) => (groupedSources[t]?.length ?? 0) > 0)
      .map((t) => {
        const sources = groupedSources[t] ?? [];
        return {
          type: t as SourceType,
          sources,
          totalSize: sources.reduce((s, x) => s + (x.file_size ?? 0), 0),
          lastUpdated: sources.reduce((latest, x) => {
            const d = x.last_event_at ?? x.created_at ?? '';
            return d > latest ? d : latest;
          }, ''),
        };
      }),
  [groupedSources]);

  const sorted = useMemo(() => {
    const q = search.toLowerCase();
    const filtered = folders.filter(
      (f) => !q || SOURCE_GROUP_CONFIG[f.type].label.toLowerCase().includes(q),
    );
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'name') cmp = SOURCE_GROUP_CONFIG[a.type].label.localeCompare(SOURCE_GROUP_CONFIG[b.type].label);
      else if (sortKey === 'files') cmp = a.sources.length - b.sources.length;
      else if (sortKey === 'size') cmp = a.totalSize - b.totalSize;
      else if (sortKey === 'updated') cmp = (a.lastUpdated ?? '').localeCompare(b.lastUpdated ?? '');
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [folders, search, sortKey, sortDir]);

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
      <div className="px-6 py-3 border-b border-slate-100 flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input type="text" placeholder="Search folders…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" />
        </div>
        <span className="text-xs text-slate-400 font-medium ml-auto">
          {sorted.length} folder{sorted.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="flex items-center px-6 py-2 border-b border-slate-100 bg-slate-50/60">
        <div className="w-8 shrink-0" />
        {col('name', 'Name', 'flex-1')}
        {col('files', 'Files', 'w-20 justify-center')}
        {col('size', 'Total Size', 'w-28')}
        {col('updated', 'Last Updated', 'w-36 justify-end pr-6')}
      </div>

      {sorted.length === 0 ? (
        <div className="py-16 text-center text-sm text-slate-400">No folders match &ldquo;{search}&rdquo;</div>
      ) : sorted.map(({ type, sources, totalSize, lastUpdated }) => {
        const config = SOURCE_GROUP_CONFIG[type];
        return (
          <button key={type} onClick={() => onOpenFolder(type)}
            className="w-full flex items-center gap-3 px-6 py-3.5 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-0 text-left group">
            <svg className="w-4 h-4 text-slate-400 shrink-0 group-hover:text-blue-400 transition-colors"
              fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
            </svg>
            <span className="text-base leading-none shrink-0">{config.icon}</span>
            <span className="font-semibold text-sm text-slate-700 group-hover:text-blue-600 transition-colors flex-1">
              {config.label}
            </span>
            <div className="w-20 text-center shrink-0">
              <span className="text-xs font-bold text-slate-500">{sources.length}</span>
            </div>
            <div className="w-28 shrink-0">
              <span className="text-[11px] font-medium text-slate-400">{formatFileSize(totalSize)}</span>
            </div>
            <div className="w-36 flex items-center justify-end gap-2 pr-6 shrink-0">
              <span className="text-[11px] font-medium text-slate-400">{formatDate(lastUpdated)}</span>
              <svg className="w-3.5 h-3.5 text-slate-300 group-hover:text-blue-400 transition-colors shrink-0"
                fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </button>
        );
      })}
    </div>
  );
}
