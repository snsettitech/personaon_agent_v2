'use client';

import { useCallback, useEffect, useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

interface Conversation {
  id: string;
  twin_id: string;
  user_id: string | null;
  surface: string | null;
  share_token: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

interface Message {
  id: string;
  role: string;
  content: string;
  citations: unknown[] | null;
  created_at: string;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function truncate(text: string, limit = 120): string {
  if (!text) return '';
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

export default function AdminConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadConversations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetchStandalone('/admin/conversations/recent?limit=100');
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      setConversations(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMessages = useCallback(async (conversationId: string) => {
    setSelectedId(conversationId);
    setLoadingMessages(true);
    try {
      const res = await authFetchStandalone(
        `/admin/conversations/${conversationId}/messages?limit=200`
      );
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      setMessages(await res.json());
    } catch {
      setMessages([]);
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  return (
    <div className="flex gap-6" style={{ minHeight: 'calc(100vh - 180px)' }}>
      {/* Conversation list */}
      <div className="w-96 flex-shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 bg-slate-50 px-5 py-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Conversations</h2>
            <button
              onClick={() => void loadConversations()}
              className="text-xs text-blue-600 hover:underline"
            >
              Refresh
            </button>
          </div>
        </div>
        <div className="divide-y divide-slate-100 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 240px)' }}>
          {loading ? (
            <div className="px-5 py-12 text-center text-sm text-slate-500">Loading...</div>
          ) : error ? (
            <div className="px-5 py-4 text-sm text-rose-600">{error}</div>
          ) : conversations.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-slate-500">No conversations</div>
          ) : (
            conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => void loadMessages(c.id)}
                className={`w-full px-5 py-3 text-left transition-colors hover:bg-slate-50 ${
                  selectedId === c.id ? 'bg-blue-50' : ''
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-slate-900 truncate" style={{ maxWidth: 200 }}>
                    {c.twin_id.slice(0, 8)}...
                  </div>
                  <span className="text-xs text-slate-400">{timeAgo(c.created_at)}</span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                  {c.surface && (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5">{c.surface}</span>
                  )}
                  {c.share_token && (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">public</span>
                  )}
                  {c.user_id ? (
                    <span>user: {c.user_id.slice(0, 8)}</span>
                  ) : (
                    <span className="text-slate-400">anonymous</span>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Message thread */}
      <div className="flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        {!selectedId ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            Select a conversation to view messages
          </div>
        ) : loadingMessages ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            Loading messages...
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            No messages in this conversation
          </div>
        ) : (
          <div className="overflow-y-auto p-5" style={{ maxHeight: 'calc(100vh - 200px)' }}>
            <div className="mb-4 text-xs text-slate-500">
              {messages.length} messages in conversation {selectedId.slice(0, 12)}...
            </div>
            <div className="space-y-4">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm ${
                      m.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-100 text-slate-900'
                    }`}
                  >
                    <div className="mb-1 text-xs opacity-60">
                      {m.role} &middot; {timeAgo(m.created_at)}
                    </div>
                    <div className="whitespace-pre-wrap">{m.content}</div>
                    {m.citations && Array.isArray(m.citations) && m.citations.length > 0 && (
                      <div className="mt-2 border-t border-black/10 pt-2 text-xs opacity-70">
                        {m.citations.length} citation(s)
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
