'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

interface Conversation {
  id: string;
  twin_id: string;
  tenant_id: string | null;
  surface: string;
  user_id: string | null;
  created_at: string;
  updated_at: string;
  first_message_preview?: string;
}

type PromotedSet = Set<string>;
type EditingState = { idx: number; answer: string } | null;

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function getDisplayInfo(conv: Conversation): { name: string; icon: 'user' | 'anonymous' } {
  return conv.surface === 'owner'
    ? { name: 'Me', icon: 'user' }
    : { name: 'Anonymous User', icon: 'anonymous' };
}

// ── Surface badge ──────────────────────────────────────────────────

function SurfaceBadge({ surface }: { surface: string }) {
  const styles: Record<string, { bg: string; color: string }> = {
    owner:  { bg: 'var(--primary-50)',        color: 'var(--primary-700)' },
    public: { bg: 'var(--bg-surface)',         color: 'var(--text-secondary)' },
    widget: { bg: 'var(--accent-trust-light)', color: 'var(--accent-trust-dark)' },
  };
  const s = styles[surface] ?? { bg: 'var(--bg-surface)', color: 'var(--text-muted)' };
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-medium leading-tight"
      style={{ backgroundColor: s.bg, color: s.color }}
    >
      {surface}
    </span>
  );
}

// ── Animation variants ─────────────────────────────────────────────

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.3, ease: 'easeOut' as const, delay: i * 0.06 },
  }),
};

const rowIn: Variants = {
  hidden: { opacity: 0, x: -6 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { duration: 0.22, ease: 'easeOut' as const, delay: i * 0.04 },
  }),
};

// ── Main page ──────────────────────────────────────────────────────

export default function ConversationsPage(): React.JSX.Element {
  const { activeTwin, isLoading: twinsLoading } = useTwin();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [promoted, setPromoted] = useState<PromotedSet>(new Set());
  const [promoting, setPromoting] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditingState>(null);

  const apiBase = resolveApiBaseUrl();

  const fetchConversations = useCallback(async () => {
    if (!activeTwin?.id) return;
    setLoading(true);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/chat/conversations?twin_id=${activeTwin.id}&limit=50`
      );
      if (res.ok) {
        const data = await res.json() as { conversations: Conversation[] };
        setConversations(data.conversations || []);
      }
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [activeTwin?.id, apiBase]);

  useEffect(() => {
    if (!twinsLoading && activeTwin?.id) void fetchConversations();
  }, [twinsLoading, activeTwin?.id, fetchConversations]);

  const loadMessages = useCallback(async (conversationId: string) => {
    setSelectedConversation(conversationId);
    setEditing(null);
    setMessagesLoading(true);
    try {
      const res = await authFetchStandalone(`${apiBase}/v2/chat/conversations/${conversationId}/messages`);
      if (res.ok) {
        const data = await res.json() as { messages: Message[] };
        setMessages(data.messages || []);
      }
    } catch {
      // silently fail
    } finally {
      setMessagesLoading(false);
    }
  }, [apiBase]);

  const promoteToKnowledge = useCallback(async (question: string, answer: string) => {
    if (!selectedConversation) return;
    const key = `${question}:${answer}`;
    setPromoting(key);
    try {
      const res = await authFetchStandalone(
        `${apiBase}/v2/chat/conversations/${selectedConversation}/promote`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, answer }),
        }
      );
      if (res.ok) {
        setPromoted((prev) => { const next = new Set(prev); next.add(key); return next; });
      }
    } catch {
      // silently fail
    } finally {
      setPromoting(null);
    }
  }, [selectedConversation, apiBase]);

  // Group messages into Q&A pairs
  const qaPairs: Array<{ question: Message; answer: Message }> = [];
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'user' && i + 1 < messages.length && messages[i + 1].role === 'assistant') {
      qaPairs.push({ question: msg, answer: messages[i + 1] });
    }
  }

  if (twinsLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
        />
      </div>
    );
  }

  return (
    <div className="pb-12 pt-4 space-y-7">

      {/* Header */}
      <motion.div initial="hidden" animate="visible" custom={0} variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
          Conversations
        </h1>
        <p className="mt-0.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Review past chats and edit answers to improve your persona&apos;s future responses.
        </p>
      </motion.div>

      {/* Two-panel grid */}
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">

        {/* ── Left: Conversation list ─────────────────────────── */}
        <motion.div
          className="rounded-3xl overflow-hidden"
          style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          initial="hidden" animate="visible" custom={1} variants={fadeUp}
        >
          {/* Header */}
          <div className="px-4 py-3.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <h2 className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
              {conversations.length} conversation{conversations.length !== 1 ? 's' : ''}
            </h2>
          </div>

          <div className="max-h-[600px] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <div
                  className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
                  style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
                />
              </div>
            ) : conversations.length === 0 ? (
              <div className="px-6 py-16 text-center">
                <svg
                  className="mx-auto h-10 w-10 mb-3"
                  style={{ color: 'var(--border-default)' }}
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
                </svg>
                <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>No conversations yet</p>
                <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                  When visitors chat with your persona, they&apos;ll appear here.
                </p>
              </div>
            ) : conversations.map((conv, i) => {
              const { name, icon } = getDisplayInfo(conv);
              const preview = conv.first_message_preview || 'No messages yet';
              const timeLabel = formatTimeAgo(conv.updated_at || conv.created_at);
              const isSelected = selectedConversation === conv.id;

              return (
                <motion.button
                  key={conv.id}
                  custom={i}
                  initial="hidden"
                  animate="visible"
                  variants={rowIn}
                  onClick={() => loadMessages(conv.id)}
                  className="w-full cursor-pointer px-4 py-3 text-left transition-colors"
                  style={{
                    borderBottom: '1px solid var(--border-subtle)',
                    borderLeft: isSelected ? '3px solid var(--accent-cta)' : '3px solid transparent',
                    backgroundColor: isSelected ? 'var(--bg-surface)' : 'transparent',
                    paddingLeft: isSelected ? '13px' : '16px',
                  }}
                  whileHover={{ backgroundColor: 'var(--bg-surface)' }}
                >
                  <div className="flex items-start gap-3">
                    {icon === 'user' ? (
                      <div
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                        style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
                      >
                        M
                      </div>
                    ) : (
                      <div
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                        style={{ backgroundColor: 'var(--bg-surface)' }}
                      >
                        <svg className="h-4 w-4" style={{ color: 'var(--text-muted)' }} fill="currentColor" viewBox="0 0 24 24">
                          <path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z" />
                        </svg>
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{name}</span>
                        <span className="shrink-0 text-[10px]" style={{ color: 'var(--text-muted)' }}>{timeLabel}</span>
                      </div>
                      <p className="mt-0.5 truncate text-xs" style={{ color: 'var(--text-secondary)' }}>{preview}</p>
                      <div className="mt-1"><SurfaceBadge surface={conv.surface} /></div>
                    </div>
                  </div>
                </motion.button>
              );
            })}
          </div>
        </motion.div>

        {/* ── Right: Q&A detail ───────────────────────────────── */}
        <motion.div
          className="rounded-3xl overflow-hidden"
          style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
          initial="hidden" animate="visible" custom={2} variants={fadeUp}
        >
          <AnimatePresence mode="wait">
            {!selectedConversation ? (
              <motion.div
                key="empty"
                className="flex min-h-[400px] flex-col items-center justify-center text-center px-6"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                <svg
                  className="h-10 w-10 mb-3"
                  style={{ color: 'var(--border-default)' }}
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                </svg>
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Select a conversation to view messages</p>
              </motion.div>
            ) : messagesLoading ? (
              <motion.div
                key="loading"
                className="flex min-h-[400px] items-center justify-center"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <div
                  className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
                  style={{ borderColor: 'var(--brand-primary)', borderTopColor: 'transparent' }}
                />
              </motion.div>
            ) : qaPairs.length === 0 ? (
              <motion.div
                key="nopairs"
                className="flex min-h-[400px] items-center justify-center"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No Q&amp;A pairs in this conversation</p>
              </motion.div>
            ) : (
              <motion.div
                key="pairs"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                {/* Panel header */}
                <div className="px-5 py-3.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <h2 className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
                    {qaPairs.length} Q&amp;A pair{qaPairs.length !== 1 ? 's' : ''}
                  </h2>
                  <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    Edit answers to improve future responses
                  </p>
                </div>

                {/* Q&A list */}
                <div className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
                  {qaPairs.map(({ question, answer }, idx) => {
                    const key = `${question.content}:${answer.content}`;
                    const isPromoted = promoted.has(key);
                    const isPromoting = promoting === key;
                    const isEditing = editing?.idx === idx;

                    return (
                      <motion.div
                        key={idx}
                        custom={idx}
                        initial="hidden"
                        animate="visible"
                        variants={rowIn}
                        className="p-5 space-y-3"
                      >
                        {/* Q */}
                        <div className="flex gap-3">
                          <div
                            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                            style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)' }}
                          >
                            Q
                          </div>
                          <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                            {question.content}
                          </p>
                        </div>

                        {/* A */}
                        <div className="flex gap-3">
                          <div
                            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                            style={{ backgroundColor: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' }}
                          >
                            A
                          </div>
                          {isEditing ? (
                            <textarea
                              className="flex-1 rounded-xl p-3 text-sm leading-relaxed outline-none resize-y"
                              style={{
                                backgroundColor: 'var(--bg-base)',
                                border: '1px solid var(--border-accent)',
                                color: 'var(--text-primary)',
                              }}
                              rows={4}
                              value={editing.answer}
                              onChange={(e) => setEditing({ idx, answer: e.target.value })}
                              autoFocus
                            />
                          ) : (
                            <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                              {answer.content}
                            </p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex justify-end gap-2">
                          {isPromoted ? (
                            <span
                              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
                              style={{ backgroundColor: 'var(--accent-emerald-light)', color: 'var(--accent-emerald)' }}
                            >
                              <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                              </svg>
                              Answer Improved
                            </span>
                          ) : isEditing ? (
                            <>
                              <button
                                onClick={() => setEditing(null)}
                                className="rounded-xl px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer"
                                style={{ border: '1px solid var(--border-default)', color: 'var(--text-secondary)' }}
                              >
                                Cancel
                              </button>
                              <motion.button
                                onClick={() => {
                                  void promoteToKnowledge(question.content, editing.answer);
                                  setEditing(null);
                                }}
                                disabled={isPromoting || !editing.answer.trim()}
                                className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 cursor-pointer"
                                style={{ background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-secondary))' }}
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.97 }}
                              >
                                {isPromoting ? (
                                  <div className="h-3 w-3 animate-spin rounded-full border border-white border-t-transparent" />
                                ) : (
                                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                                Save Improved Answer
                              </motion.button>
                            </>
                          ) : (
                            <button
                              onClick={() => setEditing({ idx, answer: answer.content })}
                              className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer"
                              style={{
                                backgroundColor: 'var(--bg-surface)',
                                color: 'var(--text-secondary)',
                                border: '1px solid var(--border-subtle)',
                              }}
                            >
                              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                              </svg>
                              Edit Answer
                            </button>
                          )}
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    </div>
  );
}
