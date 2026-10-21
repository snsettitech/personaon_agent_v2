'use client';

import { useState, useCallback } from 'react';
import type { Source, SourceType } from '@/lib/types/source';
import { SOURCE_GROUP_CONFIG } from './SourceGroupConfig';
import SourceFolderGrid from './SourceFolderGrid';
import SourceFileTable from './SourceFileTable';
import SourceDetailPanel from './SourceDetailPanel';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface SourceExplorerProps {
  groupedSources: Record<string, Source[]>;
  loading: boolean;
  onDelete: (sourceId: string) => void;
  onUpdate: (updated: Source) => void;
}

export default function SourceExplorer({ groupedSources, loading, onDelete, onUpdate }: SourceExplorerProps) {
  const [currentFolder, setCurrentFolder] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);

  const handleRetry = useCallback(async (sourceId: string) => {
    try {
      await authFetchStandalone(`/sources/${sourceId}/retry`, { method: 'POST' });
    } catch (err) {
      console.error('[SourceExplorer] retry failed source_id=%s', sourceId, err);
    }
  }, []);

  const handleDelete = useCallback((sourceId: string) => {
    setSelectedSource(null);
    onDelete(sourceId);
  }, [onDelete]);

  const handleUpdate = useCallback((updated: Source) => {
    onUpdate(updated);
    setSelectedSource(updated);
  }, [onUpdate]);

  const handleOpenFolder = useCallback((type: string) => {
    setCurrentFolder(type);
    setSelectedSource(null);
  }, []);

  const handleBackToRoot = useCallback(() => {
    setCurrentFolder(null);
    setSelectedSource(null);
  }, []);

  if (loading) {
    return (
      <div className="p-20 flex justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
      </div>
    );
  }

  const hasAny = Object.values(groupedSources).some((list) => list.length > 0);
  if (!hasAny) {
    return (
      <div className="p-32 text-center">
        <div className="text-slate-200 mb-6 flex justify-center">
          <svg className="w-24 h-24" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1"
              d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
        </div>
        <h4 className="text-xl font-black text-slate-800">No knowledge yet</h4>
        <p className="text-sm text-slate-500 max-w-xs mx-auto mt-3 font-medium">
          Add a website, document, or link above to start training your persona.
        </p>
      </div>
    );
  }

  const folderLabel = SOURCE_GROUP_CONFIG[currentFolder as SourceType]?.label ?? currentFolder;

  return (
    <>
      {/* Breadcrumb bar */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-slate-100 bg-slate-50/40">
        <button
          onClick={handleBackToRoot}
          disabled={!currentFolder}
          className={`text-xs font-bold transition-colors ${
            currentFolder ? 'text-blue-600 hover:text-blue-700' : 'text-slate-400 cursor-default'
          }`}
        >
          Knowledge
        </button>
        {currentFolder && (
          <>
            <svg className="w-3 h-3 text-slate-300 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M9 5l7 7-7 7" />
            </svg>
            <span className="text-xs font-bold text-slate-700">{folderLabel}</span>
          </>
        )}
      </div>

      {/* Folder grid or file table */}
      {currentFolder ? (
        <SourceFileTable
          folderType={currentFolder as SourceType}
          sources={groupedSources[currentFolder] ?? []}
          selectedSourceId={selectedSource?.id ?? null}
          onSelect={setSelectedSource}
        />
      ) : (
        <SourceFolderGrid
          groupedSources={groupedSources}
          onOpenFolder={handleOpenFolder}
        />
      )}

      {selectedSource && (
        <SourceDetailPanel
          source={selectedSource}
          onClose={() => setSelectedSource(null)}
          onDelete={handleDelete}
          onRetry={handleRetry}
          onUpdate={handleUpdate}
        />
      )}
    </>
  );
}
