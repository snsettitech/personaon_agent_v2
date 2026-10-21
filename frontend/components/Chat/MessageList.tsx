'use client';

import React, { useRef, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAudioPlayback } from '@/lib/hooks/useAudioPlayback';
import { CitationsDrawer, InlineCitation, Citation } from '@/components/ui/CitationsDrawer';
import { CopyButton as SharedCopyButton } from '@/components/share/CopyButton';
import EditAnswer from './EditAnswer';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  citations?: string[];
  citation_details?: Array<{
    id: string;
    filename?: string | null;
    citation_url?: string | null;
    chunk_preview?: string;
  }>;
  answerability_state?: string;
  source_tier?: string;
  review_required?: boolean;
  review_reason?: string | null;
  graph_used?: boolean;
  timestamp?: number; // Unix timestamp in milliseconds
  confidencePercent?: number; // Computed from answerability_state: direct=90, derivable=60, insufficient=30
}

interface MessageListProps {
  messages: Message[];
  loading: boolean;
  isSearching: boolean;
  twinId?: string;
  personaName?: string;      // For "[Name] is thinking..." typing indicator
  personaAvatarUrl?: string; // For avatar next to AI messages
  conversationId?: string | null;
  mode?: 'owner' | 'public' | 'training' | 'assistant';
}

function formatTimestamp(ts?: number): string {
  if (!ts) return '';
  const date = new Date(ts);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function getPersonaInitials(name?: string): string {
  const cleaned = (name || '').trim();
  if (!cleaned) return 'AI';

  return cleaned
    .split(/\s+/)
    .map((part) => part[0] || '')
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

function MessageCopyButton({ content }: { content: string }) {
  return (
    <SharedCopyButton
      text={content}
      label="Copy message"
      copiedLabel="Copied"
      size="sm"
      variant="ghost"
      iconOnly
      title="Copy to clipboard"
      className="rounded-lg border-0 text-[#8e8e93] opacity-0 transition group-hover:opacity-100 hover:bg-black/5 hover:text-[#111111]"
    />
  );
}

// Audio playback button for text-to-speech
function AudioButton({ content, twinId }: { content: string; twinId?: string }) {
  const { isPlaying, isLoading, error, togglePlayback } = useAudioPlayback(twinId);

  return (
    <button
      onClick={() => togglePlayback(content)}
      disabled={isLoading || !twinId}
      className={`opacity-0 group-hover:opacity-100 p-1.5 rounded-lg transition-all ${
        isPlaying
          ? 'bg-[#0066cc]/10 text-[#0066cc]'
          : 'text-[#8e8e93] hover:bg-black/5 hover:text-[#111111]'
      } ${isLoading ? 'animate-pulse' : ''}`}
      aria-label={isPlaying ? 'Stop audio' : 'Read aloud'}
      title={error || (isPlaying ? 'Stop' : 'Read aloud')}
    >
      {isLoading ? (
        <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
      ) : isPlaying ? (
        <svg className="w-4 h-4" fill="currentColor" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
          <rect x="10" y="8" width="2" height="8" fill="currentColor" />
          <rect x="14" y="6" width="2" height="12" fill="currentColor" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
        </svg>
      )}
    </button>
  );
}

// Skeleton loader for messages
export function MessageSkeleton() {
  return (
    <div className="flex justify-start animate-pulse">
      <div className="flex gap-4 max-w-[80%]">
        <div className="w-10 h-10 rounded-2xl bg-black/10" />
        <div className="space-y-3 flex-1">
          <div className="rounded-3xl rounded-tl-none bg-white p-5 space-y-2">
            <div className="h-4 bg-black/10 rounded w-3/4" />
            <div className="h-4 bg-black/10 rounded w-1/2" />
            <div className="h-4 bg-black/10 rounded w-2/3" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Memoized component to prevent re-rendering of the message list when input changes.
// This improves performance significantly as the message list grows.
const MessageList = React.memo(({
  messages,
  loading,
  isSearching: _isSearching,
  twinId,
  personaName,
  personaAvatarUrl,
  conversationId,
  mode,
}: MessageListProps) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Citations drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeCitations, setActiveCitations] = useState<Citation[]>([]);

  const openCitationsDrawer = (citations: Citation[]) => {
    setActiveCitations(citations);
    setDrawerOpen(true);
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const personaInitials = getPersonaInitials(personaName);

  return (
    <div className="flex-1 overflow-y-auto bg-transparent px-4 py-8 md:px-8">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          if (!isUser && !msg.content) return null;
          return (
            <div key={idx} className={`group flex ${isUser ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-4 duration-500`}>
              <div className={`flex max-w-[92%] gap-3 md:max-w-[82%] ${isUser ? 'flex-row-reverse' : ''}`}>
                {!isUser && (
                  <div className="mt-1 h-9 w-9 shrink-0 overflow-hidden rounded-2xl bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-xs font-semibold text-[#0b3d91] shadow-sm ring-1 ring-[#0066cc]/12">
                    {personaAvatarUrl
                      ? <img src={personaAvatarUrl} alt="" className="h-full w-full object-cover" />
                      : <div className="flex h-full w-full items-center justify-center">{personaInitials}</div>}
                  </div>
                )}

                <div className={`space-y-2 ${isUser ? 'items-end' : 'items-start'}`}>
                  <div className={`relative rounded-[1.35rem] px-4 py-3.5 text-sm leading-7 shadow-sm transition-all duration-300 md:px-5 ${isUser
                    ? 'rounded-tr-md bg-[#0066cc] text-white shadow-[0_14px_36px_rgba(0,102,204,0.20)]'
                    : 'rounded-tl-md border border-black/10 bg-white/90 text-[#1d1d1f] shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur'
                  }`}>
                    {msg.role === 'assistant' ? (
                      <div className="prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2 prose-strong:text-[#111111] prose-pre:bg-[#1d1d1f] prose-pre:text-white prose-code:rounded prose-code:bg-[#f5f5f7] prose-code:px-1 prose-code:py-0.5 prose-code:text-[#0066cc] prose-code:before:content-none prose-code:after:content-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                        {msg.citation_details && msg.citation_details.length > 0 && (
                          <span className="ml-1 inline-flex gap-0.5">
                            {msg.citation_details.map((citation, citeIdx) => (
                              <InlineCitation
                                key={citation.id}
                                number={citeIdx + 1}
                                sourceName={citation.filename ?? undefined}
                                chunkPreview={citation.chunk_preview}
                                citationUrl={citation.citation_url}
                                onClick={() => openCitationsDrawer(msg.citation_details || [])}
                              />
                            ))}
                          </span>
                        )}
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap font-medium">{msg.content}</p>
                    )}

                    {msg.content && msg.role === 'assistant' && (
                      <div className="absolute -right-2 -top-2 flex gap-1">
                        <AudioButton content={msg.content} twinId={twinId} />
                        <MessageCopyButton content={msg.content} />
                      </div>
                    )}
                  </div>

                  {msg.role === 'assistant' && msg.confidencePercent !== undefined && (
                    <div className="mt-1 h-1 max-w-[220px] overflow-hidden rounded-full bg-black/5">
                      <div
                        className="h-full rounded-full bg-[#0066cc] transition-all duration-500"
                        style={{ width: `${msg.confidencePercent}%` }}
                      />
                    </div>
                  )}

                  <div className={`flex items-center gap-2 px-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
                    {msg.timestamp && (
                      <span className="text-[10px] font-medium text-[#8e8e93]">
                        {formatTimestamp(msg.timestamp)}
                      </span>
                    )}

                    {msg.role === 'user' && msg.content && (
                      <MessageCopyButton content={msg.content} />
                    )}

                    {msg.role === 'assistant' && mode === 'owner' && conversationId && (
                      <EditAnswer
                        question={(() => {
                          for (let i = idx - 1; i >= 0; i--) {
                            if (messages[i].role === 'user') return messages[i].content;
                          }
                          return '';
                        })()}
                        originalAnswer={msg.content}
                        conversationId={conversationId}
                      />
                    )}
                  </div>

                  {msg.role === 'assistant' && msg.graph_used && (
                    <div className="flex flex-wrap gap-2 px-1">
                      <div className="flex items-center gap-1.5 rounded-full border border-[#0066cc]/15 bg-[#0066cc]/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#0066cc]">
                        From approved context
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex max-w-[92%] gap-3 md:max-w-[82%]">
              <div className="mt-1 h-9 w-9 shrink-0 overflow-hidden rounded-2xl bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-xs font-semibold text-[#0b3d91] shadow-sm ring-1 ring-[#0066cc]/12">
                {personaAvatarUrl
                  ? <img src={personaAvatarUrl} alt="" className="h-full w-full object-cover" />
                  : <div className="flex h-full w-full items-center justify-center">{personaInitials}</div>}
              </div>
              <div className="rounded-[1.35rem] rounded-tl-md border border-black/10 bg-white/90 px-5 py-4 shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur">
                <div className="flex items-center gap-3">
                  <div className="flex gap-1">
                    <div className="h-2 w-2 animate-bounce rounded-full bg-[#0066cc]" style={{ animationDelay: '0ms' }} />
                    <div className="h-2 w-2 animate-bounce rounded-full bg-[#0066cc]" style={{ animationDelay: '150ms' }} />
                    <div className="h-2 w-2 animate-bounce rounded-full bg-[#0066cc]" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="text-sm font-medium text-[#6e6e73]">
                    {personaName ? `${personaName} is thinking...` : 'Thinking...'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <CitationsDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        citations={activeCitations}
      />
    </div>
  );
});

MessageList.displayName = 'MessageList';

export default MessageList;
