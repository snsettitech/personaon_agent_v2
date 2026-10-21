'use client';

import Link from 'next/link';
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { parseChatStream } from '@/lib/chat/streamParser';
import { analytics } from '@/lib/analytics/events';
import { storeReferral } from '@/lib/analytics/referral';
import type { TriggerAction } from '@/lib/hooks/useTriggerMatcher';
import {
  useTriggerMatcher,
  executeTriggeredAction,
  MIN_RESIDUAL_CONTENT_LENGTH,
} from '@/lib/hooks/useTriggerMatcher';
import ActionCollectForm from '@/components/Chat/ActionCollectForm';
import BookingCard from '@/components/Chat/BookingCard';
import LeadCaptureModal from '@/components/Chat/LeadCaptureModal';
import VoiceToggle from '@/components/Chat/VoiceToggle';
import VoiceCall from '@/components/Chat/VoiceCall';
import MicButton from '@/components/Chat/MicButton';
import MessageAudio, { autoPlayTTS } from '@/components/Chat/MessageAudio';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Message = {
  role: 'user' | 'assistant';
  content: string;
  citations?: string[];
  citation_details?: Array<{
    id: string;
    filename?: string | null;
    citation_url?: string | null;
    chunk_preview?: string;
  }>;
};

/**
 * The interactive surface of the public persona page: chat (stream + triggers),
 * voice (toggle / live call / TTS), booking, action-collection, and the
 * suggestion chips + input bar. Extracted from `ProfileExperience` so every
 * future layout (Phase 4) can drop the same console into a slot rather than
 * re-implementing chat/voice/booking.
 *
 * Owns all interactive state; talks to the backend via `twinId` / `shareToken`
 * / `apiBaseUrl`. The parent (chrome) keeps the hero, profile card, and the
 * Classic hero→chat collapse — driven here via `onActivityChange`.
 */
interface PersonaConsoleProps {
  twinId: string | null;
  shareToken: string | null;
  apiBaseUrl: string;
  // identity shown inside chat headers / avatars
  personaName: string;
  headline: string;
  avatarUrl?: string;
  // capability flags (today derived in deriveProfileState)
  hasVoice: boolean;
  hasLiveVoice: boolean;
  voiceName: string | null;
  booking: { enabled: boolean; connected: boolean };
  suggestedQuestions: readonly string[];
  pinnedQuestionsVisible: boolean;
  showBranding: boolean; // gates the in-chat "create your own" loop prompt
  handle: string;
  initialConversationId?: string | null; // today read from ?conv=
  // lets the chrome (Classic hero) react to chat starting, without owning chat state
  onActivityChange?: (active: boolean) => void;
  // opens the profile drawer owned by the chrome
  onOpenProfile?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

// Info button icon (circle-i)
function InfoIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 9v5M10 7h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Fallback suggestion questions
const FALLBACK_QUESTIONS = [
  "What do you do?",
  "What's your background?",
  "How can you help me?",
  "Tell me about your expertise",
];

// useLayoutEffect on the server is a no-op that warns; fall back to useEffect
// there. We use the layout variant so the parent's hero collapse and the
// console's chat view flip in the same paint (no one-frame hero+chat overlap).
const useIsomorphicLayoutEffect =
  typeof window !== 'undefined' ? useLayoutEffect : useEffect;

// ---------------------------------------------------------------------------
// PersonaConsole
// ---------------------------------------------------------------------------

export function PersonaConsole({
  twinId,
  shareToken,
  apiBaseUrl,
  personaName,
  headline,
  avatarUrl,
  hasVoice,
  hasLiveVoice,
  voiceName,
  booking,
  suggestedQuestions,
  pinnedQuestionsVisible,
  showBranding,
  handle,
  initialConversationId,
  onActivityChange,
  onOpenProfile,
}: PersonaConsoleProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId ?? null);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [pendingAction, setPendingAction] = useState<{ action: TriggerAction; userText: string } | null>(null);
  const [showBookingCard, setShowBookingCard] = useState(false);
  const [bookingFallbackUrl, setBookingFallbackUrl] = useState<string | undefined>(undefined);
  const [suggestionsVisible, setSuggestionsVisible] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [offerState, setOfferState] = useState<string | null>(null);
  const [streamStarted, setStreamStarted] = useState(false);

  // ── Lead capture state ──────────────────────────────────────────────
  // completedTurns counts full assistant turns so the capture offer fires
  // only after the visitor has had a real exchange.
  const [completedTurns, setCompletedTurns] = useState(0);
  const [leadCaptureEnabled, setLeadCaptureEnabled] = useState(false);
  // captureSubmitted is the unified terminal-dismiss flag: set to true on both
  // successful submit AND on skip (code review CRITICAL #6 fix — skip must
  // permanently prevent re-show on subsequent messages, not just hide for one
  // turn).
  const [captureSubmitted, setCaptureSubmitted] = useState(false);
  const [showCaptureForm, setShowCaptureForm] = useState(false);

  // ponytail: actions / slash-command feature disabled 2026-06-26 — it invented fake
  // commands ("/connect") and added no value. Passing null means no triggers ever
  // match, so the interception in sendMessage is inert and every message goes to
  // normal chat. Booking stays reachable via the booking button. The trigger UI/state
  // is left dormant for a proper rebuild later.
  const { checkTrigger } = useTriggerMatcher(null);

  const markdownComponents = useMemo((): Components => ({
    a: ({ href, children }) => {
      if (!href || !/^https?:\/\//i.test(href)) return <>{children}</>;
      const isBooking = /^https?:\/\/(cal\.com|calendly\.com|zcal\.co|savvycal\.com|tidycal\.com|doodle\.com|meetings\.hubspot\.com|app\.hubspot\.com\/meetings)\//i.test(href);
      if (isBooking) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full bg-[#eef5ff] border border-[#0066cc]/20 text-[#0066cc] px-3 py-1 text-xs font-semibold hover:bg-[#d6e8fb] transition-colors"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 text-[#0066cc] hover:text-[#0b3d91]">
          {children}
        </a>
      );
    },
  }), []);

  const displayName = personaName;
  const avatarSrc = avatarUrl;
  const initials = getInitials(displayName) || 'P';
  const suggestionChips =
    suggestedQuestions && suggestedQuestions.length > 0
      ? suggestedQuestions.slice(0, 3)
      : FALLBACK_QUESTIONS.slice(0, 3);

  const hasMessages = messages.length > 0;

  // Let the chrome (Classic hero / top bar) react to chat starting without
  // owning chat state. Layout effect so the collapse happens in the same paint.
  useIsomorphicLayoutEffect(() => {
    onActivityChange?.(hasMessages);
  }, [hasMessages, onActivityChange]);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Thread the conversation + lead across turns AND across reloads. Capturing the
  // session_id (in onMetadata below) is what turns one-message visits into real
  // multi-turn sessions; persisting it lets a visitor reload /p and continue, and
  // lets public lead-capture progress (offer_state) across turns.
  useEffect(() => {
    if (!twinId || typeof window === 'undefined') return;
    try {
      const storedConv = window.sessionStorage.getItem(`_pon_pub_conv_${twinId}`);
      const storedLead = window.sessionStorage.getItem(`_pon_pub_lead_${twinId}`);
      const storedOffer = window.sessionStorage.getItem(`_pon_pub_offer_${twinId}`);
      if (storedConv && !conversationId) setConversationId(storedConv);
      if (storedLead) setLeadId(storedLead);
      if (storedOffer) setOfferState(storedOffer);
    } catch {
      /* sessionStorage unavailable — threading degrades to in-memory (per-visit) */
    }
    // hydrate once per twin; conversationId intentionally omitted from deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [twinId]);

  useEffect(() => {
    if (!twinId || typeof window === 'undefined') return;
    try {
      if (conversationId) window.sessionStorage.setItem(`_pon_pub_conv_${twinId}`, conversationId);
      if (leadId) window.sessionStorage.setItem(`_pon_pub_lead_${twinId}`, leadId);
      if (offerState) {
        window.sessionStorage.setItem(`_pon_pub_offer_${twinId}`, offerState);
      } else {
        window.sessionStorage.removeItem(`_pon_pub_offer_${twinId}`);
      }
    } catch {
      /* ignore persistence failures */
    }
  }, [twinId, conversationId, leadId, offerState]);

  // Hydrate captureSubmitted from sessionStorage on mount so a visitor who
  // already submitted (or deliberately skipped) this session is not asked again
  // even after a page reload.  Must run before the trigger effect so the
  // terminal flag is in place before any turn count check fires.
  useEffect(() => {
    if (!twinId || typeof window === 'undefined') return;
    try {
      const stored = window.sessionStorage.getItem(`_pon_pub_cap_${twinId}`);
      if (stored === 'true') setCaptureSubmitted(true);
    } catch {
      /* sessionStorage unavailable — degrade gracefully */
    }
  }, [twinId]);

  // Show the capture form once the visitor has completed 2 turns and lead
  // capture is enabled.  Uses captureSubmitted as the single terminal-dismiss
  // gate for both submit and skip paths (code review CRITICAL #6 fix).
  useEffect(() => {
    if (
      leadCaptureEnabled &&
      completedTurns >= 2 &&
      !captureSubmitted &&
      !showCaptureForm
    ) {
      // Guard: only show if we have a leadId — if leadId is null at this point
      // we log a warning and do NOT show the modal rather than silently failing
      // (code review HIGH #5 fix).
      if (!leadId) {
        console.error(
          '[PersonaConsole] lead_capture_enabled=true but leadId is null — capture modal suppressed'
        );
        return;
      }
      setShowCaptureForm(true);
    }
  }, [leadCaptureEnabled, completedTurns, captureSubmitted, showCaptureForm, leadId]);

  // Auto-play TTS when voiceEnabled and a new assistant message arrives
  const prevMsgCountRef = useRef(messages.length);
  useEffect(() => {
    if (!voiceEnabled || !hasVoice || !twinId || isSending) {
      prevMsgCountRef.current = messages.length;
      return;
    }
    if (messages.length > prevMsgCountRef.current) {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg.role === 'assistant' && lastMsg.content && lastMsg.content.length > 0) {
        autoPlayTTS(lastMsg.content, twinId, true);
      }
    }
    prevMsgCountRef.current = messages.length;
  }, [messages, isSending, voiceEnabled, hasVoice, twinId]);

  // Chat send function
  const sendMessage = async (text: string) => {
    if (!text.trim() || isSending || !twinId || !shareToken) return;

    const trimmedText = text.trim();
    let triggerHandled = false;

    // Trigger interception: check if message matches a configured trigger
    const triggerResult = checkTrigger(trimmedText);
    if (triggerResult.matched) {
      const action = triggerResult.action;
      setSuggestionsVisible(false);

      // Add user message
      setMessages((prev) => [...prev, { role: 'user', content: trimmedText }]);
      setInput('');

      // If action is native_calendar, show BookingCard
      if (action.type === 'native_calendar') {
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: "Let me pull up my calendar for you...",
        }]);
        const actionConfig = (action as unknown as { config?: { fallback_url?: string } }).config;
        setBookingFallbackUrl(actionConfig?.fallback_url || undefined);
        setShowBookingCard(true);
        return;
      }

      // If action requires field collection, show form instead of executing
      if (action.collect_fields && action.collect_fields.length > 0) {
        if (action.type === 'webhook') {
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: "I'd love to help with that! I just need a few details first.",
          }]);
        }
        setPendingAction({ action, userText: trimmedText });
        // Always return when showing the form — don't also send to agent.
        // The form submission handles execution; mid-sentence content is
        // deferred until after the form completes (avoids double-handle).
        return;
      } else {
        // No fields to collect — execute immediately
        setIsSending(true);
        try {
          const responseText = await executeTriggeredAction(apiBaseUrl, twinId, action);
          setMessages((prev) => [...prev, { role: 'assistant', content: responseText }]);
        } catch {
          setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, something went wrong with that action.' }]);
        } finally {
          setIsSending(false);
        }

        // Check mid-sentence fallthrough
        const keyword = triggerResult.matchedKeyword.toLowerCase();
        const cleanedText = trimmedText.toLowerCase().replace(keyword, '').trim();
        if (cleanedText.length <= MIN_RESIDUAL_CONTENT_LENGTH) {
          return;
        }
        triggerHandled = true;
      }
    }

    // Normal chat flow (non-trigger messages, or mid-sentence triggers with extra content)
    setSuggestionsVisible(false);
    setIsSending(true);
    setStreamStarted(false);
    setOfferState(null);

    // Only add user message if trigger block didn't already add it
    if (!triggerHandled) {
      setMessages((prev) => [...prev, { role: 'user', content: trimmedText }]);
      setInput('');
    }

    try {
      const response = await fetch(`${apiBaseUrl}/v2/chat/public/${twinId}/${shareToken}/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmedText, conversation_id: conversationId, lead_id: leadId }),
      });
      if (!response.ok) throw new Error('Chat failed');

      if (!response.body) throw new Error('No response body');

      let fullText = '';

      // Add placeholder assistant message for streaming
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      await parseChatStream(response.body, {
        onContent: (data) => {
          setStreamStarted(true);
          fullText += data.content ?? '';
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = { ...last, content: fullText };
            }
            return updated;
          });
        },
        onMetadata: (data) => {
          // Session event: carries session_id (the conversation id used to thread
          // subsequent turns) + lead_id (public lead-capture). The public backend
          // sends session_id, NOT conversation_id — capturing it here is what makes
          // multi-turn threading work.
          if (data.session_id || data.conversation_id || data.lead_id || data.offer_state) {
            const sid = (data.conversation_id as string) || (data.session_id as string);
            if (sid) setConversationId(sid);
            if (data.lead_id) setLeadId(data.lead_id as string);
            if (data.lead_capture_enabled) setLeadCaptureEnabled(true);
            if (data.offer_state) setOfferState(data.offer_state as string);
            if (data.offer_state === 'email_captured') setCaptureSubmitted(true);
            return;
          }
          // Citation metadata
          const citations = (data.citations as string[]) ?? [];
          const citationDetails = (data.citation_details as Message['citation_details']) ?? [];
          if (citations.length > 0 || citationDetails.length) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = { ...last, citations, citation_details: citationDetails };
              }
              return updated;
            });
          }
        },
        onError: () => {
          if (!fullText) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = { ...last, content: 'Sorry, something went wrong. Please try again.' };
              }
              return updated;
            });
          }
        },
      });
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ]);
    } finally {
      setIsSending(false);
      // Count every completed normal-chat turn (trigger-only early-returns above
      // don't reach here, which is intentional for native_calendar / form flows).
      setCompletedTurns((prev) => prev + 1);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  };

  return (
    <>
      {/* ─── Floating pill header (chat mode) ─────────────────────────────── */}
      {hasMessages && (
        <motion.div
          className="relative z-20 shrink-0 px-4 pt-4 pb-2 md:px-8"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
        >
          <div className="mx-auto flex max-w-3xl items-center gap-3 rounded-full border border-black/10 bg-white/86 px-3 py-2 shadow-[0_16px_48px_rgba(15,23,42,0.10)] backdrop-blur-xl">
            {/* Avatar */}
            <div className="h-10 w-10 shrink-0 overflow-hidden rounded-2xl bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-xs font-semibold text-[#0b3d91] shadow-sm ring-1 ring-[#0066cc]/12">
              {avatarSrc
                ? <img src={avatarSrc} alt={displayName} className="h-full w-full object-cover" />
                : <div className="flex h-full w-full items-center justify-center">{initials}</div>}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold tracking-tight text-[#111111]">{displayName}</p>
              {headline && <p className="truncate text-xs text-[#6e6e73] max-w-[56vw] md:max-w-md">{headline}</p>}
            </div>
            {hasVoice && (
              <VoiceToggle enabled={voiceEnabled} onToggle={() => setVoiceEnabled((prev) => !prev)} />
            )}
            {hasLiveVoice && twinId && (
              <VoiceCall
                twinId={twinId}
                twinName={displayName}
                avatarUrl={avatarSrc}
                voiceName={voiceName}
                showVoiceProof={false}
                isPublic
                shareToken={shareToken}
              />
            )}
            {booking.enabled && booking.connected && (
              <button
                onClick={() => {
                  if (twinId) {
                    analytics.bookingButtonClicked({ twin_id: twinId, surface: 'persistent_chip' });
                  }
                  setBookingFallbackUrl(undefined);
                  setShowBookingCard(true);
                }}
                aria-label="Schedule a meeting"
                className="flex h-9 items-center gap-1.5 rounded-full bg-[#e8f2ff] px-3 text-xs font-semibold text-[#0066cc] transition hover:bg-[#d6e8fb] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0066cc]/40"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                </svg>
                <span className="hidden sm:inline">Book</span>
              </button>
            )}
            <button
              onClick={() => onOpenProfile?.()}
              aria-label="View profile"
              className="flex items-center justify-center w-9 h-9 rounded-full text-[#6e6e73] transition hover:bg-black/6 hover:text-[#111111] focus:outline-none"
            >
              <InfoIcon />
            </button>
          </div>
        </motion.div>
      )}

      {/* ─── Active chat — message list ─────────────────────────────────────── */}
      {hasMessages && (
        <div
          className="flex-1 overflow-y-auto px-4 py-6 md:px-8"
          aria-live="polite"
          aria-atomic="false"
          aria-label="Conversation"
        >
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
            {messages
              .filter((msg, i) => !(isSending && i === messages.length - 1 && msg.role === 'assistant' && !msg.content))
              .map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={`group flex animate-in fade-in slide-in-from-bottom-4 duration-500 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div className={`flex max-w-[88%] gap-3 md:max-w-[80%] ${message.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    {/* Persona avatar beside assistant messages */}
                    {message.role === 'assistant' && (
                      <div className="mt-1 h-9 w-9 shrink-0 overflow-hidden rounded-2xl bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-xs font-semibold text-[#0b3d91] shadow-sm ring-1 ring-[#0066cc]/12">
                        {avatarSrc
                          ? <img src={avatarSrc} alt="" className="h-full w-full object-cover" />
                          : <div className="flex h-full w-full items-center justify-center">{initials}</div>}
                      </div>
                    )}
                    <div className="space-y-1.5">
                      <div className={`relative rounded-[1.35rem] px-4 py-3.5 text-sm leading-7 shadow-sm ${
                        message.role === 'user'
                          ? 'rounded-tr-md bg-[#0066cc] text-white shadow-[0_14px_36px_rgba(0,102,204,0.20)]'
                          : 'rounded-tl-md border border-black/10 bg-white/90 text-[#1d1d1f] shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur'
                      }`}>
                        {message.role === 'assistant' ? (
                          <div className="prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2 prose-strong:text-[#111111] prose-pre:bg-[#1d1d1f] prose-pre:text-white prose-code:rounded prose-code:bg-[#f5f5f7] prose-code:px-1 prose-code:py-0.5 prose-code:text-[#0066cc] prose-code:before:content-none prose-code:after:content-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{message.content}</ReactMarkdown>
                            {message.citation_details && message.citation_details.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                {message.citation_details.map((cite, cIdx) => (
                                  <span
                                    key={cite.id || cIdx}
                                    className="inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-full bg-[rgba(0,102,204,0.10)] text-[#0066cc] border border-[rgba(0,102,204,0.20)]"
                                    title={cite.chunk_preview || cite.filename || ''}
                                  >
                                    {cite.filename || `Source ${cIdx + 1}`}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap font-medium">{message.content}</p>
                        )}
                        {message.role === 'assistant' && hasVoice && twinId && message.content && (
                          <div className="mt-1.5 flex justify-end">
                            <MessageAudio text={message.content} twinId={twinId} isPublic />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}

            {/* Typing indicator */}
            {isSending && !streamStarted && !messages[messages.length - 1]?.content && (
              <div className="flex justify-start animate-in fade-in duration-300">
                <div className="flex gap-3">
                  <div className="mt-1 h-9 w-9 shrink-0 overflow-hidden rounded-2xl bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] ring-1 ring-[#0066cc]/12">
                    {avatarSrc
                      ? <img src={avatarSrc} alt="" className="h-full w-full object-cover" />
                      : <div className="flex h-full w-full items-center justify-center text-xs font-semibold text-[#0b3d91]">{initials}</div>}
                  </div>
                  <div className="rounded-[1.35rem] rounded-tl-md border border-black/10 bg-white/90 px-5 py-4 shadow-[0_18px_48px_rgba(15,23,42,0.08)] backdrop-blur">
                    <span className="inline-flex gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#6e6e73]" style={{ animation: 'typingBounce 1.2s ease-in-out infinite', animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-[#6e6e73]" style={{ animation: 'typingBounce 1.2s ease-in-out infinite', animationDelay: '150ms' }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-[#6e6e73]" style={{ animation: 'typingBounce 1.2s ease-in-out infinite', animationDelay: '300ms' }} />
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Visitor → owner loop prompt: appears once the persona has
                answered (chat reply or booking confirmation both append an
                assistant message). Same gating as the branding footer. */}
            {showBranding && !isSending
              && messages.some((m) => m.role === 'assistant' && m.content.length > 0) && (
              <div className="flex justify-center pt-1 animate-in fade-in duration-700">
                <Link
                  href={`/auth/signup?ref=${encodeURIComponent(handle)}&utm_source=persona_page`}
                  onClick={() => {
                    storeReferral(handle, 'persona_page');
                    analytics.personaPageCtaClicked({ handle, surface: 'chat_loop_prompt' });
                  }}
                  className="rounded-full border border-black/8 bg-white/80 px-4 py-2 text-xs font-medium text-[#6e6e73] shadow-sm backdrop-blur transition hover:text-[#0066cc]"
                >
                  This page answers for {displayName}. <span className="font-semibold text-[#0066cc]">Make yours free →</span>
                </Link>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* ─── Lead capture modal ──────────────────────────────────────────── */}
      {/* leadId guard: if somehow leadId is null when showCaptureForm fires we
          suppress the modal rather than crash (code review HIGH #5 fix).
          onSkip sets captureSubmitted=true (same terminal flag as onSuccess) so
          the modal cannot re-appear on subsequent messages (CRITICAL #6 fix). */}
      {showCaptureForm && leadId && twinId && (
        <LeadCaptureModal
          leadId={leadId}
          personaName={personaName}
          apiBaseUrl={apiBaseUrl}
          onSuccess={(name, email) => {
            setShowCaptureForm(false);
            setCaptureSubmitted(true);
            try {
              window.sessionStorage.setItem(`_pon_pub_cap_${twinId}`, 'true');
            } catch { /* ignore */ }
            setMessages((prev) => [
              ...prev,
              {
                role: 'assistant',
                content: `Thanks${name ? `, ${name}` : ''}! I'll follow up at ${email}.`,
              },
            ]);
          }}
          onSkip={() => {
            // Treat skip as a terminal dismiss — same flag as submit — so the
            // modal does NOT re-appear when completedTurns increments again
            // (code review CRITICAL #6 fix).
            setShowCaptureForm(false);
            setCaptureSubmitted(true);
            try {
              window.sessionStorage.setItem(`_pon_pub_cap_${twinId}`, 'true');
            } catch { /* ignore */ }
          }}
        />
      )}

      {/* ─── BookingCard ─────────────────────────────────────────────────── */}
      {showBookingCard && twinId && (
        <div className="px-4 pb-2 md:px-8">
          <div className="mx-auto max-w-3xl">
            <BookingCard
              twinId={twinId}
              apiBaseUrl={apiBaseUrl}
              personaName={displayName}
              leadId={leadId}
              onBooked={(result) => {
                setShowBookingCard(false);
                setBookingFallbackUrl(undefined);
                setMessages((prev) => [...prev, {
                  role: 'assistant',
                  content: result.message || "Your request has been sent! You'll receive an email confirmation once approved.",
                }]);
              }}
              onCancel={() => {
                setShowBookingCard(false);
                setBookingFallbackUrl(undefined);
                setMessages((prev) => [...prev, {
                  role: 'assistant',
                  content: "No problem! Let me know if you'd like to schedule something later.",
                }]);
              }}
              fallbackUrl={bookingFallbackUrl}
            />
          </div>
        </div>
      )}

      {/* ─── Action Collect Form ─────────────────────────────────────────── */}
      {pendingAction && (
        <div className="px-4 pb-2 md:px-8">
          <div className="mx-auto max-w-3xl">
            <ActionCollectForm
              fields={pendingAction.action.collect_fields || []}
              actionLabel={pendingAction.action.label}
              description={pendingAction.action.type === 'webhook' ? 'Please fill in the details below:' : undefined}
              submitting={isSending}
              onSubmit={async (collectedData: Record<string, string>) => {
                setIsSending(true);
                setPendingAction(null);
                try {
                  const responseText = await executeTriggeredAction(
                    apiBaseUrl, twinId!, pendingAction.action, collectedData
                  );
                  setMessages((prev) => [...prev, { role: 'assistant', content: responseText }]);
                } catch {
                  setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }]);
                } finally {
                  setIsSending(false);
                }
              }}
              onCancel={() => {
                setPendingAction(null);
                setMessages((prev) => [...prev, { role: 'assistant', content: 'No problem! Let me know if you need anything else.' }]);
              }}
            />
          </div>
        </div>
      )}

      {/* ─── Suggested questions above input ─────────────────────────────── */}
      {suggestionsVisible && pinnedQuestionsVisible && !pendingAction && !showBookingCard && (
        <div className="shrink-0 px-4 pt-3 md:px-6">
          <div className="mx-auto w-full max-w-[760px]">
            <div className="flex flex-wrap gap-2 [scrollbar-width:none] [-ms-overflow-style:none]">
              {booking.enabled && booking.connected && (
                <button
                  onClick={() => {
                    if (twinId) analytics.bookingButtonClicked({ twin_id: twinId, surface: 'persistent_chip' });
                    setBookingFallbackUrl(undefined);
                    setShowBookingCard(true);
                  }}
                  disabled={isSending}
                  className="rounded-full border border-[#0066cc]/20 bg-[#eef5ff] px-3.5 py-1.5 text-[13px] text-[#0066cc] font-medium shadow-sm whitespace-nowrap transition-all duration-200 focus:outline-none hover:bg-[#d6e8fb] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  Book a meeting
                </button>
              )}
              {suggestionChips.map((question) => (
                <button
                  key={question}
                  onClick={() => void sendMessage(question)}
                  disabled={isSending}
                  className="rounded-full border border-black/10 bg-white/85 px-3.5 py-1.5 text-[13px] text-[#3a3a3c] shadow-sm whitespace-nowrap transition-all duration-200 focus:outline-none hover:border-[#0066cc]/30 hover:bg-white hover:text-[#0066cc] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {question.length > 40 ? question.slice(0, 40) + '…' : question}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ─── Offer state confirmation strip ──────────────────────────────── */}
      {(offerState === 'offered' || offerState === 'booked') && !showBookingCard && (
        <div className="shrink-0 px-4 pb-1 md:px-6">
          <div className="mx-auto w-full max-w-[760px]">
            <div className="flex items-center gap-2 rounded-full bg-emerald-50 border border-emerald-200 px-4 py-2 text-xs text-emerald-800">
              <svg className="h-3.5 w-3.5 shrink-0 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span className="flex-1">{offerState === 'booked' ? 'Booking requested — you\'ll hear back by email.' : 'A meeting offer has been shared — book anytime above.'}</span>
              <button
                type="button"
                onClick={() => setOfferState(null)}
                aria-label="Dismiss"
                className="text-emerald-500 hover:text-emerald-700 transition-colors ml-1"
              >
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Floating input bar ───────────────────────────────────────────── */}
      <div className="relative z-10 shrink-0 px-4 pb-4 pt-2 md:px-6">
        <div className="relative mx-auto flex w-full max-w-[760px] items-end gap-2 rounded-[1.75rem] border border-black/10 bg-white/90 p-2 shadow-[0_18px_60px_rgba(15,23,42,0.14)] backdrop-blur-xl">
          <div className="relative flex-1 rounded-2xl">
            <textarea
              value={input}
              rows={1}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                pendingAction || showBookingCard
                  ? 'Complete the form above...'
                  : 'Ask me anything...'
              }
              disabled={isSending || !!pendingAction || showBookingCard || showCaptureForm}
              aria-label="Chat input"
              className="max-h-[150px] min-h-[48px] w-full resize-none overflow-hidden bg-transparent px-3 py-3.5 text-[15px] text-[#111111] placeholder:text-[#8e8e93] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <div className="flex items-center gap-1.5 pb-0.5">
            <MicButton
              onTranscript={(text) => {
                setInput(text);
                void sendMessage(text);
              }}
              disabled={isSending || !!pendingAction || showBookingCard || showCaptureForm}
            />
            <motion.button
              onClick={() => void sendMessage(input)}
              disabled={isSending || !input.trim() || showCaptureForm}
              aria-label="Send message"
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full text-white shadow-[0_10px_24px_rgba(0,102,204,0.26)] transition-opacity disabled:cursor-not-allowed disabled:opacity-45"
              style={{ background: '#0066cc' }}
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.95 }}
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </motion.button>
          </div>
        </div>
      </div>
    </>
  );
}

export default PersonaConsole;
