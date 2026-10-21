'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';
import { useRequestLogger } from '@/lib/hooks/useRequestLogger';
import type { RequestLog } from '@/lib/hooks/useRequestLogger';

export function DebugPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const { logs, isEnabled, clearLogs, toggleEnabled } = useRequestLogger();
  const [activeTab, setActiveTab] = useState<'requests' | 'config'>('requests');
  const [replayResult, setReplayResult] = useState<{logId: string; status: number; statusText: string; duration: number} | null>(null);
  const [replayingId, setReplayingId] = useState<string | null>(null);

  const getStatusColor = (status?: number) => {
    if (!status) return 'text-gray-500';
    if (status >= 200 && status < 300) return 'text-green-600';
    if (status >= 400) return 'text-red-600';
    return 'text-yellow-600';
  };

  const replayRequest = useCallback(async (log: RequestLog) => {
    setReplayingId(log.id);
    setReplayResult(null);
    
    const startTime = performance.now();
    try {
      // Strip Authorization header for security - user must be re-authenticated
      const headers: Record<string, string> = {};
      if (log.requestHeaders) {
        Object.entries(log.requestHeaders).forEach(([key, value]) => {
          // Skip auth headers - they'll be re-added by useAuthFetch if needed
          if (key.toLowerCase() !== 'authorization') {
            headers[key] = value;
          }
        });
      }

      const response = await fetch(log.url, {
        method: log.method,
        headers,
        body: log.requestBody || undefined,
      });
      
      const duration = Math.round(performance.now() - startTime);
      setReplayResult({
        logId: log.id,
        status: response.status,
        statusText: response.statusText,
        duration
      });
    } catch (error) {
      const duration = Math.round(performance.now() - startTime);
      setReplayResult({
        logId: log.id,
        status: 0,
        statusText: error instanceof Error ? error.message : 'Network Error',
        duration
      });
    } finally {
      setReplayingId(null);
    }
  }, []);

  const shouldShowDebugPanel =
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_SHOW_DEBUG_PANEL === 'true';

  if (!shouldShowDebugPanel) return null;

  return (
    <>
      {/* Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-4 left-4 z-50 w-10 h-10 bg-slate-800 text-white rounded-full shadow-lg flex items-center justify-center hover:bg-slate-700 transition-colors"
        title="Debug Panel"
      >
        D
      </button>

      {/* Panel */}
      {isOpen && (
        <div className="fixed bottom-16 left-4 z-50 w-[500px] max-h-[600px] bg-white rounded-lg shadow-2xl border border-slate-200 flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50 rounded-t-lg">
            <div className="flex items-center gap-4">
              <h3 className="font-semibold text-slate-700">Debug Panel</h3>
              <div className="flex gap-2">
                <button
                  onClick={() => setActiveTab('requests')}
                  className={`px-3 py-1 text-xs rounded ${activeTab === 'requests' ? 'bg-slate-200' : 'hover:bg-slate-100'}`}
                >
                  Requests ({logs.length})
                </button>
                <button
                  onClick={() => setActiveTab('config')}
                  className={`px-3 py-1 text-xs rounded ${activeTab === 'config' ? 'bg-slate-200' : 'hover:bg-slate-100'}`}
                >
                  Config
                </button>
              </div>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="text-slate-400 hover:text-slate-600"
            >
              x
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-auto p-4">
            {activeTab === 'requests' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={toggleEnabled}
                    />
                    Log requests
                  </label>
                  {logs.length > 0 && (
                    <button
                      onClick={clearLogs}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      Clear logs
                    </button>
                  )}
                </div>

                <div className="space-y-2">
                  {logs.length === 0 ? (
                    <p className="text-sm text-slate-400 text-center py-8">
                      No requests logged yet
                    </p>
                  ) : (
                    logs.map((log) => (
                      <div
                        key={log.id}
                        className="text-xs border border-slate-100 rounded p-2 hover:bg-slate-50"
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono">{log.method}</span>
                          <span className={`font-bold ${getStatusColor(log.status)}`}>
                            {log.status || 'ERR'}
                          </span>
                          <span className="text-slate-400 ml-auto">
                            {log.duration}ms
                          </span>
                        </div>
                        <div className="text-slate-500 truncate mt-1">
                          {log.url}
                        </div>
                        {log.error && (
                          <div className="text-red-600 mt-1">
                            {log.error}
                          </div>
                        )}
                        <div className="flex items-center justify-between mt-2">
                          <span className="text-slate-300">
                            {log.timestamp.toLocaleTimeString()}
                          </span>
                          <button
                            onClick={() => replayRequest(log)}
                            disabled={replayingId === log.id}
                            className="px-2 py-1 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded text-[10px] font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            title="Replay this request"
                          >
                            {replayingId === log.id ? 'Replaying...' : 'Replay'}
                          </button>
                        </div>
                        {replayResult?.logId === log.id && (
                          <div className={`mt-2 p-2 rounded ${replayResult.status >= 200 && replayResult.status < 300 ? 'bg-green-50 border border-green-100' : 'bg-red-50 border border-red-100'}`}>
                            <div className="flex items-center gap-2">
                              <span className="text-slate-500">Replay:</span>
                              <span className={`font-bold ${getStatusColor(replayResult.status)}`}>
                                {replayResult.status || 'ERR'}
                              </span>
                              <span className="text-slate-400 ml-auto">
                                {replayResult.duration}ms
                              </span>
                            </div>
                            {replayResult.statusText && replayResult.status !== replayResult.status && (
                              <div className="text-slate-500 mt-0.5">{replayResult.statusText}</div>
                            )}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {activeTab === 'config' && (
              <div className="space-y-4 text-sm">
                <div>
                  <div className="font-medium text-slate-500 uppercase text-xs tracking-wider mb-1">
                    API Base URL
                  </div>
                  <code className="bg-slate-100 px-2 py-1 rounded block">
                    {API_BASE_URL}
                  </code>
                </div>

                <div>
                  <div className="font-medium text-slate-500 uppercase text-xs tracking-wider mb-1">
                    Environment
                  </div>
                  <div>{process.env.NODE_ENV}</div>
                </div>

                <div>
                  <div className="font-medium text-slate-500 uppercase text-xs tracking-wider mb-2">
                    Available Endpoints
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <a
                      href={`${API_BASE_URL}/docs`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      /docs (Swagger)
                    </a>
                    <a
                      href={`${API_BASE_URL}/health`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      /health
                    </a>
                    <a
                      href={`${API_BASE_URL}/version`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      /version
                    </a>
                    <a
                      href={`${API_BASE_URL}/cors-test`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      /cors-test
                    </a>
                  </div>
                </div>

                <div>
                  <div className="font-medium text-slate-500 uppercase text-xs tracking-wider mb-2">
                    Quick Tests
                  </div>
                  <div className="space-y-2">
                    <button
                      onClick={async () => {
                        const res = await fetch(`${API_BASE_URL}/health`);
                        alert(`Health check: ${res.status}`);
                      }}
                      className="w-full text-left px-3 py-2 bg-slate-50 hover:bg-slate-100 rounded text-xs"
                    >
                      Test /health endpoint
                    </button>
                    <button
                      onClick={async () => {
                        const res = await fetch(`${API_BASE_URL}/version`);
                        const data = await res.json();
                        alert(`Version: ${data.git_sha}\nEnvironment: ${data.environment}`);
                      }}
                      className="w-full text-left px-3 py-2 bg-slate-50 hover:bg-slate-100 rounded text-xs"
                    >
                      Test /version endpoint
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
