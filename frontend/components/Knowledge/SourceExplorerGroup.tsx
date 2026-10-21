'use client';

import { useState } from 'react';
import type { Source, SourceType } from '@/lib/types/source';
import { SOURCE_GROUP_CONFIG } from './SourceGroupConfig';

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  });
}

interface SourceExplorerGroupProps {
  type: SourceType;
  sources: Source[];
  defaultOpen?: boolean;
  selectedSourceId: string | null;
  onSelect: (source: Source) => void;
}

export default function SourceExplorerGroup({
  type,
  sources,
  defaultOpen = false,
  selectedSourceId,
  onSelect,
}: SourceExplorerGroupProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const config = SOURCE_GROUP_CONFIG[type];

  return (
    <div>
      {/* Folder header row */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-3 px-6 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100"
      >
        <svg
          className={`w-4 h-4 shrink-0 transition-colors ${isOpen ? 'text-blue-500' : 'text-slate-300'}`}
          fill={isOpen ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.5"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
          />
        </svg>
        <span className="text-base leading-none">{config.icon}</span>
        <span className="font-bold text-sm text-slate-700">{config.label}</span>
        <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${config.bgColor} ${config.color}`}>
          {sources.length}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-slate-300 ml-auto transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* File rows */}
      {isOpen && sources.map((source) => {
        const isSelected = source.id === selectedSourceId;
        const health = source.health_status ?? 'healthy';
        const isHealthy = health === 'healthy';
        const isUnhealthy = ['failed', 'error', 'degraded'].includes(health);

        return (
          <button
            key={source.id}
            onClick={() => onSelect(source)}
            className={`w-full flex items-center border-b border-slate-50 last:border-0 text-left transition-colors pl-6 ${
              isSelected ? 'bg-blue-50 hover:bg-blue-50' : 'hover:bg-slate-50/70'
            }`}
          >
            {/* Indent spacer + file icon */}
            <div className="w-12 flex justify-center shrink-0 py-3.5 pl-2">
              <span className="text-sm text-slate-300">{config.icon}</span>
            </div>

            {/* Name */}
            <div className="flex-1 min-w-0 py-3.5 pr-4">
              <span className={`text-sm font-medium truncate block ${isSelected ? 'text-blue-700' : 'text-slate-700'}`}>
                {source.filename}
              </span>
            </div>

            {/* Health */}
            <div className="w-28 py-3.5 shrink-0">
              <span className={`inline-flex items-center gap-1.5 text-[10px] font-black ${
                isHealthy ? 'text-green-600' : isUnhealthy ? 'text-red-500' : 'text-yellow-600'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${
                  isHealthy ? 'bg-green-500' : isUnhealthy ? 'bg-red-400' : 'bg-yellow-400 animate-pulse'
                }`} />
                {health.toUpperCase()}
              </span>
            </div>

            {/* Updated date */}
            <div className="w-28 py-3.5 pr-6 shrink-0 text-right">
              <span className="text-[11px] font-medium text-slate-400">
                {formatDate(source.last_event_at ?? source.created_at)}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
