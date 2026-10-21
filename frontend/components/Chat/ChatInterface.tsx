'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import MessageList, { Message } from './MessageList';
import SuggestedQuestions from './SuggestedQuestions';
import { useTwin } from '@/lib/context/TwinContext';
import { resolveApiBaseUrl, getChatAuthToken } from '@/lib/api';
import { API_ENDPOINTS } from '@/lib/constants';
import { parseChatStream } from '@/lib/chat/streamParser';
import { analytics } from '@/lib/analytics/events';
import { useTriggerMatcher, TriggerAction, executeTriggeredAction, formatActionResponse, MIN_RESIDUAL_CONTENT_LENGTH } from '@/lib/hooks/useTriggerMatcher';
import { formatPersonaDisplayName } from '@/lib/branding/personaName';
import ActionCollectForm from './ActionCollectForm';
import BookingCard from './BookingCard';
import VoiceToggle from './VoiceToggle';
import MicButton from './MicButton';
import { autoPlayTTS } from './MessageAudio';
import { QuotaBlockedDialog } from '@/components/ui/QuotaBlockedDialog';

const STREAM_IDLE_TIMEOUT_MS = 60000;
const PERSONA_FALLBACK_AVATAR =
  'bg-[linear-gradient(135deg,rgba(0,102,204,0.18),rgba(255,255,255,0.96))] text-[#0b3d91] ring-1 ring-[#0066cc]/12';

export type ChatStreamEventType = 'metadata' | 'clarify' | 'content' | 'done' | 'error';

export interface ChatStreamEvent {
  type: ChatStreamEventType;
  payload?: any;
}

function computeConfidencePercent(answerabilityState?: string): number | undefined {
  if (!answerabilityState) return undefined;
  switch (answerabilityState) {
    case 'direct': return 90;
    case 'derivable': return 60;
    case 'insufficient': return 30;
    default: return undefined;
  }
}

function buildWelcomeMessage(personaName?: string | null, occupation?: string | null): string {
  const cleanedName = (personaName || '').trim();
  const cleanedOccupation = (occupation || '').trim();
  if (cleanedName && cleanedOccupation) {
    return `Hi, I'm ${cleanedName}. Ask me what I can answer from the approved sources.`;
  }
  if (cleanedName) {
    return `Hi, I'm ${cleanedName}. How can I help?`;
  }
  return 'Hi. How can I help?';
}

export default function ChatInterface({
  twinId,
  conversationId,
  onConversationStarted,
  resetKey,
  tenantId,
  mode = 'owner',
  trainingSessionId,
  publicShareToken,
  onStreamEvent,
  presetQuestions = [],
  initialInput,
  embedded = false,
}: {
  twinId: string;
  conversationId?: string | null;
  onConversationStarted?: (id: string) => void;
  resetKey?: number;
  tenantId?: string | null;
  mode?: 'owner' | 'public' | 'training' | 'assistant';
  trainingSessionId?: string | null;
  publicShareToken?: string | null;
  onStreamEvent?: (event: ChatStreamEvent) => void;
  presetQuestions?: string[];
  initialInput?: string | null;
  /**
   * Embedded mode: fill the parent container (h-full) instead of forcing a
   * full-viewport min-height. Used when ChatInterface is hosted inside another
   * surface (e.g. the dashboard Assistant Home) rather than owning the route.
   */
  embedded?: boolean;
}) {
  const { user, activeTwin, twins } = useTwin();
  const isE2EBypass =
    process.env.NODE_ENV !== 'production' &&
    process.env.NEXT_PUBLIC_E2E_BYPASS_AUTH === '1';
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastUserMessage, setLastUserMessage] = useState<string | null>(null);
  const [effectiveConversationId, setEffectiveConversationId] = useState<string | null>(conversationId || null);
  const [pendingAction, setPendingAction] = useState<{
    action: TriggerAction;
    userText: string;
  } | null>(null);
  const [collectSubmitting, setCollectSubmitting] = useState(false);
  const [showBookingCard, setShowBookingCard] = useState(false);
  const [bookingFallbackUrl, setBookingFallbackUrl] = useState<string | undefined>(undefined);
  const [activeMode, setActiveMode] = useState<{
    mode: string;
    promptOverride: string;
  } | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [quotaBlocked, setQuotaBlocked] = useState<number | null>(null);

  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seededInputRef = useRef<string | null>(null);
  const quotaDialogShownRef = useRef(false);

  const contextStorageKey = mode === 'training'
    ? `training_${trainingSessionId || 'none'}`
    : mode;

  const storageKey = useMemo(() => {
    const resolvedTenantId = tenantId || user?.tenant_id || 'unknown';
    return `simulator_chat_${resolvedTenantId}_${twinId}_${contextStorageKey}`;
  }, [tenantId, user?.tenant_id, twinId, contextStorageKey]);
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const resolvedTwin = useMemo(() => {
    return twins.find((candidate) => candidate.id === twinId) || (activeTwin?.id === twinId ? activeTwin : null);
  }, [activeTwin, twinId, twins]);
  const rawPersonaName = resolvedTwin?.name || activeTwin?.name || null;
  const personaName = formatPersonaDisplayName(rawPersonaName);
  const hasVoice = Boolean(
    (resolvedTwin?.settings as Record<string, unknown> | undefined)?.voice_id
    || (activeTwin?.settings as Record<string, unknown> | undefined)?.voice_id,
  );
  const personaProfile = useMemo(() => {
    const settings = (resolvedTwin?.settings || activeTwin?.settings || {}) as Record<string, unknown>;
    const pub = (settings.public_profile || {}) as Record<string, unknown>;
    const pp = (settings.persona_profile || {}) as Record<string, unknown>;
    const role =
      (typeof pub.role === 'string' && pub.role.trim()) ||
      (typeof pp.occupation === 'string' && pp.occupation.trim()) ||
      '';
    const organization =
      (typeof pub.organization === 'string' && pub.organization.trim()) ||
      (typeof pp.organization === 'string' && pp.organization.trim()) ||
      '';
    const headline =
      (typeof pub.headline === 'string' && pub.headline.trim()) ||
      (typeof pp.headline === 'string' && pp.headline.trim()) ||
      (typeof pp.short_description === 'string' && pp.short_description.trim()) ||
      '';
    const bio =
      (typeof pub.bio === 'string' && pub.bio.trim()) ||
      (typeof pp.bio === 'string' && pp.bio.trim()) ||
      (typeof pp.short_description === 'string' && pp.short_description.trim()) ||
      '';

    return {
      role,
      organization,
      roleLine: [role, organization].filter(Boolean).join(' at '),
      headline,
      bio,
    };
  }, [resolvedTwin?.settings, activeTwin?.settings]);
  const personaAvatarUrl = useMemo(() => {
    const settings = (resolvedTwin?.settings || activeTwin?.settings || {}) as Record<string, unknown>;
    const pub = (settings.public_profile || {}) as Record<string, unknown>;
    const pp  = (settings.persona_profile || {}) as Record<string, unknown>;
    return (
      (typeof pub.avatar_url === 'string' && pub.avatar_url.trim()) ||
      (typeof pp.image_url   === 'string' && pp.image_url.trim())   ||
      undefined
    ) || undefined;
  }, [resolvedTwin, activeTwin]);
  const welcomeMessage = useMemo(
    () => buildWelcomeMessage(
      personaName,
      personaProfile.roleLine || personaProfile.headline || null,
    ),
    [personaName, personaProfile.roleLine, personaProfile.headline],
  );

  const emitStreamEvent = useCallback((type: ChatStreamEventType, payload?: any) => {
    if (!onStreamEvent) return;
    try {
      onStreamEvent({ type, payload });
    } catch (err) {
      console.error('[ChatInterface] onStreamEvent callback failed', err);
    }
  }, [onStreamEvent]);

  // Derive actions from twin settings for owner/dashboard mode (skip fetch)
  const settingsActions = useMemo(() => {
    if (mode !== 'owner') return undefined;
    const settings = (resolvedTwin?.settings || activeTwin?.settings || {}) as Record<string, unknown>;
    const rawActions = (settings.actions || []) as Array<Record<string, unknown>>;
    return rawActions
      .filter((a) => a.is_active !== false)
      .map((a) => ({
        id: String(a.id || ''),
        type: String(a.type || '') as TriggerAction['type'],
        trigger: String(a.trigger || ''),
        triggers: Array.isArray(a.triggers) ? a.triggers.map(String) : [String(a.trigger || '')],
        label: String(a.label || ''),
        collect_fields: Array.isArray(a.collect_fields) ? a.collect_fields.map(String) : [],
      }));
  }, [mode, resolvedTwin, activeTwin]);

  // For owner mode: pass settings actions directly (no fetch needed)
  // For public mode: pass twinId to fetch available actions from API
  const { checkTrigger, loaded: triggersLoaded } = useTriggerMatcher(
    mode === 'public' ? twinId : null,
    settingsActions,
  );

  // Handle triggered action execution -- uses shared utility for DRY
  // When action has collect_fields, shows inline form instead of executing immediately
  const handleTriggeredAction = useCallback(async (action: TriggerAction, userText: string) => {
    const userMsg: Message = { role: 'user', content: userText, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');

    // Special handling for native_calendar: show BookingCard inline
    if (action.type === 'native_calendar') {
      const assistantMsg: Message = {
        role: 'assistant',
        content: "Let me pull up my calendar for you...",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Extract fallback URL from action config (stored in twin settings)
      const actionConfig = (action as unknown as { config?: { fallback_url?: string } }).config;
      setBookingFallbackUrl(actionConfig?.fallback_url || undefined);
      setShowBookingCard(true);
      return;
    }

    // Special handling for mode_switch: fetch raw result to extract prompt_override
    if (action.type === 'mode_switch') {
      try {
        const response = await fetch(`${apiBaseUrl}/v2/actions/${twinId}/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_id: action.id, collected_data: {} }),
        });

        if (response.ok) {
          const data = await response.json();
          const result = (data.result || {}) as Record<string, unknown>;
          const promptOverride = String(result.prompt_override || '');
          const modeName = String(result.mode || '');
          if (promptOverride) {
            setActiveMode({ mode: modeName, promptOverride });
          }
          const responseText = formatActionResponse(action, result);
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: responseText,
            timestamp: Date.now(),
          }]);
        } else {
          throw new Error('Execution failed');
        }
      } catch {
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: "Sorry, something went wrong switching modes. Please try again.",
          timestamp: Date.now(),
        }]);
      }
      return;
    }

    // If the action requires field collection, show the inline form
    if (action.collect_fields && action.collect_fields.length > 0) {
      // For webhook actions, add a conversational prompt before showing the form
      if (action.type === 'webhook') {
        const collectMsg: Message = {
          role: 'assistant',
          content: `I'd love to help with that! I just need a few details first.`,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, collectMsg]);
      }
      setPendingAction({ action, userText });
      return;
    }

    // No fields to collect -- execute immediately
    try {
      const responseText = await executeTriggeredAction(apiBaseUrl, twinId, action);
      const assistantMsg: Message = {
        role: 'assistant',
        content: responseText,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch {
      const errorMsg: Message = {
        role: 'assistant',
        content: "Sorry, something went wrong with that action. Please try again.",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    }
  }, [apiBaseUrl, twinId]);

  // Submit handler for ActionCollectForm -- executes the pending action with collected data
  const handleCollectSubmit = useCallback(async (data: Record<string, string>) => {
    if (!pendingAction) return;
    setCollectSubmitting(true);
    try {
      const responseText = await executeTriggeredAction(apiBaseUrl, twinId, pendingAction.action, data);
      const assistantMsg: Message = {
        role: 'assistant',
        content: responseText,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch {
      const errorMsg: Message = {
        role: 'assistant',
        content: "Sorry, something went wrong with that action. Please try again.",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setPendingAction(null);
      setCollectSubmitting(false);
    }
  }, [pendingAction, apiBaseUrl, twinId]);

  // Cancel handler for ActionCollectForm -- dismisses form with friendly message
  const handleCollectCancel = useCallback(() => {
    setPendingAction(null);
    const cancelMsg: Message = {
      role: 'assistant',
      content: "No problem! Let me know if you change your mind.",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, cancelMsg]);
  }, []);

  // BookingCard handlers
  const handleBookingBooked = useCallback((result: { booking_id: string; message: string }) => {
    setShowBookingCard(false);
    setBookingFallbackUrl(undefined);
    const confirmMsg: Message = {
      role: 'assistant',
      content: result.message || "Your request has been sent! You'll receive an email confirmation once approved.",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, confirmMsg]);
  }, []);

  const handleBookingCancel = useCallback(() => {
    setShowBookingCard(false);
    setBookingFallbackUrl(undefined);
    const cancelMsg: Message = {
      role: 'assistant',
      content: "No problem! Let me know if you'd like to schedule something later.",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, cancelMsg]);
  }, []);

  useEffect(() => {
    setEffectiveConversationId(conversationId || null);
  }, [conversationId]);

  useEffect(() => {
    const next = (initialInput || '').trim();
    if (!next) return;
    if (seededInputRef.current === next) return;
    seededInputRef.current = next;
    setInput(next);
  }, [initialInput]);


  const persistMessages = useCallback((nextMessages: Message[]) => {
    try {
      if (nextMessages.length === 0) {
        localStorage.removeItem(storageKey);
        return;
      }
      localStorage.setItem(storageKey, JSON.stringify(nextMessages));
    } catch {
      // ignore storage errors
    }
  }, [storageKey]);

  const resetWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
    }
    watchdogRef.current = setTimeout(() => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    }, STREAM_IDLE_TIMEOUT_MS);
  }, []);

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  useEffect(() => {
    const loadHistory = async () => {
      setLastError(null);
      if (!conversationId) {
        let restored = false;
        try {
          const raw = localStorage.getItem(storageKey);
          if (raw) {
            const parsed = JSON.parse(raw) as Message[];
            if (Array.isArray(parsed) && parsed.length > 0) {
              setMessages(parsed);
              restored = true;
            }
          }
        } catch {
          // ignore storage parse errors
        }
        if (!restored) {
          setMessages([]);
        }
        return;
      }

      try {
        const token = await getChatAuthToken();
        if (!token) return;

        const response = await fetch(`${apiBaseUrl}/conversations/${conversationId}/messages`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
          const data = await response.json();
          const history = data.map((m: any) => ({
            role: m.role,
            content: m.content,
            citations: m.citations,
            answerability_state: m.answerability_state,
            source_tier: m.source_tier,
            review_required: m.review_required,
            review_reason: m.review_reason,
          }));
          setMessages(history.length > 0 ? history : []);
        }
      } catch (error) {
        console.error('Error loading history:', error);
      }
    };
    loadHistory();
  }, [conversationId, storageKey, apiBaseUrl, welcomeMessage]);

  useEffect(() => {
    persistMessages(messages);
  }, [messages, persistMessages]);

  useEffect(() => {
    if (!resetKey) return;
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // ignore storage errors
    }
    setMessages([]);
    setLastError(null);
    setLastUserMessage(null);
    setActiveMode(null);
  }, [resetKey, storageKey, welcomeMessage]);

  // Auto-play TTS when voiceEnabled and a new assistant message finishes streaming
  const prevMessageCountRef = useRef(messages.length);
  useEffect(() => {
    if (!voiceEnabled || !hasVoice || loading) {
      prevMessageCountRef.current = messages.length;
      return;
    }
    // Detect new assistant message added (count increased and last is assistant)
    if (messages.length > prevMessageCountRef.current) {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg.role === 'assistant' && lastMsg.content && lastMsg.content.length > 0) {
        autoPlayTTS(lastMsg.content, twinId);
      }
    }
    prevMessageCountRef.current = messages.length;
  }, [messages, loading, voiceEnabled, hasVoice, twinId]);

  // Abort any in-flight streaming request when the component unmounts.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    };
  }, []);

  const sendMessage = async (overrideText?: string, options?: { retry?: boolean }) => {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    // Trigger interception: check if message matches a configured trigger keyword
    if (!options?.retry) {
      const triggerResult = checkTrigger(text);
      if (triggerResult.matched) {
        // Execute the triggered action (renders response as persona message)
        await handleTriggeredAction(triggerResult.action, text);
        // Per CONTEXT.md decision: when trigger found mid-sentence, also send to agent
        const keyword = triggerResult.matchedKeyword.toLowerCase();
        const cleanedText = text.toLowerCase().replace(keyword, '').trim();
        if (cleanedText.length > MIN_RESIDUAL_CONTENT_LENGTH) {
          // Message has substantial content beyond the trigger -- also send to agent
          // Continue with normal sendMessage flow (don't return)
        } else {
          // Message is just the trigger keyword -- only show action response
          return;
        }
      }
    }

    if (!options?.retry) {
      const userMsg: Message = { role: 'user', content: text, timestamp: Date.now() };
      setMessages((prev) => [...prev, userMsg]);
      setInput('');
    }
    setLastUserMessage(text);
    setLastError(null);
    setLoading(true);
    setIsSearching(true);

    analytics.chatMessageSent({
      twin_id: twinId,
      message_length: text.length,
      mode,
      conversation_id: effectiveConversationId ?? undefined,
      is_first_message: messages.length <= 1,
    });

    const assistantMsg: Message = {
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const usePublicShareEndpoint = mode === 'public' && !!publicShareToken;
      abortRef.current = new AbortController();

      // Generate trace ID for Langfuse observability (links frontend action to backend trace)
      const traceId = crypto.randomUUID();

      if (usePublicShareEndpoint) {
        const response = await fetch(`${apiBaseUrl}/v2/chat/public/${twinId}/${publicShareToken}/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Langfuse-Trace-Id': traceId,
          },
          body: JSON.stringify({
            message: text,
            conversation_id: conversationId || null,
            mode_override: activeMode?.promptOverride || null,
          }),
          signal: abortRef.current.signal
        });

        if (!response.ok) {
          throw new Error(`Request failed (${response.status})`);
        }

        const data = await response.json();
        setIsSearching(false);
        const responseType = data.response_type || (data.requires_user_input ? 'clarification' : 'answer');
        const responseMessage = data.message || data.response || 'No response generated.';
        const isClarification = data.status === 'queued' || responseType === 'clarification' || data.requires_user_input;
        setMessages((prev) => {
          const next = [...prev];
          const lastMsg = { ...next[next.length - 1] };

        if (isClarification) {
          lastMsg.content = responseMessage || 'I need clarification.';
          lastMsg.citations = [];
          lastMsg.answerability_state = 'insufficient';
          lastMsg.review_required = true;
          lastMsg.review_reason = 'clarify';
          emitStreamEvent('clarify', data);
        } else {
          lastMsg.content = responseMessage;
          lastMsg.citations = data.citations;
          lastMsg.citation_details = data.citation_details;
          lastMsg.answerability_state = data.answerability_state;
          lastMsg.confidencePercent = computeConfidencePercent(data.answerability_state);
          lastMsg.source_tier = data.source_tier;
          lastMsg.review_required = data.review_required;
          lastMsg.review_reason = data.review_reason;
          emitStreamEvent('metadata', {
            citations: data.citations,
            citation_details: data.citation_details,
            source_tier: data.source_tier,
            review_required: data.review_required,
            review_reason: data.review_reason,
            owner_memory_refs: data.owner_memory_refs || [],
            owner_memory_topics: data.owner_memory_topics || [],
            used_owner_memory: Boolean(data.used_owner_memory),
            dialogue_mode: data.dialogue_mode,
            intent_label: data.intent_label,
            workflow_intent: data.workflow_intent,
            module_ids: data.module_ids,
            routing_decision: data.routing_decision,
            render_strategy: data.render_strategy,
            query_class: data.query_class,
            quote_intent: data.quote_intent,
            answerability_state: data.answerability_state,
            planner_action: data.planner_action,
            retrieval_stats: data.retrieval_stats,
            selected_evidence_block_types: data.selected_evidence_block_types,
            debug_snapshot: data.debug_snapshot,
            grounding_verifier: data.grounding_verifier,
            online_eval: data.online_eval,
          });
          emitStreamEvent('done', data);
        }

          next[next.length - 1] = lastMsg;
          return next;
        });

        return;
      }

      const token = await getChatAuthToken();
      if (!token && !isE2EBypass) {
        setLastError('Please sign in to chat.');
        setMessages((prev) => {
          const last = [...prev];
          last[last.length - 1] = {
            role: 'assistant',
            content: 'Please sign in to chat with this persona.',
            timestamp: Date.now(),
          };
          return last;
        });
        return;
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Langfuse-Trace-Id': traceId,
      };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const ownerStreamPath = mode === 'assistant' ? 'assistant' : 'owner';
      const response = await fetch(`${apiBaseUrl}/v2/chat/${ownerStreamPath}/${twinId}/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId || null,
          mode_override: activeMode?.promptOverride || null,
        }),
        signal: abortRef.current.signal
      });

      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      if (!response.body) throw new Error('No response body');

      const handleClarify = (data: Record<string, unknown>) => {
        setIsSearching(false);
        setLoading(false);
        emitStreamEvent('clarify', data);
        setMessages((prev) => {
          const last = [...prev];
          const lastMsg = { ...last[last.length - 1] };
          lastMsg.content = (data.question as string) || 'I need clarification.';
          last[last.length - 1] = lastMsg;
          return last;
        });
      };

      const handleMetadata = (data: Record<string, unknown>) => {
        setIsSearching(false);
        emitStreamEvent('metadata', data);
        const convId = data.conversation_id as string | undefined;
        if (convId && onConversationStarted && convId !== conversationId) {
          onConversationStarted(convId);
        }
        if (convId) setEffectiveConversationId(convId);
        const graphUsed = (data.graph_context as { graph_used?: boolean })?.graph_used || false;
        setMessages((prev) => {
          const last = [...prev];
          const lastMsg = { ...last[last.length - 1] };
          lastMsg.citations = data.citations as string[] | undefined;
          lastMsg.citation_details = data.citation_details as Message['citation_details'];
          lastMsg.answerability_state = data.answerability_state as string | undefined;
          lastMsg.confidencePercent = computeConfidencePercent(data.answerability_state as string | undefined);
          lastMsg.source_tier = data.source_tier as string | undefined;
          lastMsg.review_required = data.review_required as boolean | undefined;
          lastMsg.review_reason = data.review_reason as string | null | undefined;
          lastMsg.graph_used = graphUsed;
          last[last.length - 1] = lastMsg;
          return last;
        });
      };

      await parseChatStream(response.body, {
        onBytesReceived: resetWatchdog,
        onClarify: handleClarify,
        onMetadata: handleMetadata,
        onContent: (data) => {
          // Check for quota sentinel BEFORE rendering
          if (typeof data.content === 'string' && data.content.includes('[QUOTA_EXCEEDED]')) {
            if (!quotaDialogShownRef.current) {
              quotaDialogShownRef.current = true;
              const match = data.content.match(/limit of ([\d,]+)/);
              const cap = match ? parseInt(match[1].replace(/,/g, ''), 10) : 500;
              setQuotaBlocked(cap);
            }
            return; // don't add the sentinel text to the chat
          }
          emitStreamEvent('content', data);
          setMessages((prev) => {
            const last = [...prev];
            const lastMsg = { ...last[last.length - 1] };
            lastMsg.content += data.content ?? '';
            last[last.length - 1] = lastMsg;
            return last;
          });
        },
        onError: (data) => {
          const payload = data ?? {};
          const message =
            typeof payload.error === 'string' && payload.error.trim().length > 0
              ? payload.error
              : 'Sorry, I could not complete that response.';
          setLastError(message);
          emitStreamEvent('error', payload);
          setMessages((prev) => {
            const last = [...prev];
            const lastMsg = { ...last[last.length - 1] };
            lastMsg.content = message;
            last[last.length - 1] = lastMsg;
            return last;
          });
        },
        onDone: (data) => emitStreamEvent('done', data ?? {}),
      }, { signal: abortRef.current?.signal });
    } catch (error: any) {
      console.error('Error sending message:', error);
      analytics.chatMessageError({ twin_id: twinId, error: error?.message || 'Unknown error' });
      emitStreamEvent('error', {
        name: error?.name,
        message: error?.message,
      });
      const message = error?.name === 'AbortError'
        ? 'Connection stalled. Please retry.'
        : (error?.message || "Sorry, I'm having trouble connecting to my brain right now.");
      setLastError(message);
      setMessages((prev) => {
        const last = [...prev];
        last[last.length - 1] = {
          role: 'assistant',
          content: message
        };
        return last;
      });
    } finally {
      clearWatchdog();
      abortRef.current = null;
      setLoading(false);
      setIsSearching(false);
    }
  };

  const retryLastMessage = async () => {
    if (!lastUserMessage || loading) return;
    await sendMessage(lastUserMessage, { retry: true });
  };

  const clearHistory = () => {
    const confirmed = window.confirm('Clear this chat history for the current persona?');
    if (!confirmed) return;
    analytics.chatHistoryCleared({ twin_id: twinId });
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // ignore storage errors
    }
    setMessages([]);
    setLastError(null);
    setLastUserMessage(null);
    setActiveMode(null);
  };

  // ── Avatar initials fallback ─────────────────────────────────────────────
  const initials = (personaName || 'AI')
    .split(' ')
    .map((w: string) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  const displayMessages =
    messages[0]?.role === 'assistant' && messages[0].content === welcomeMessage
      ? messages.slice(1)
      : messages;
  const showPreviewIntro = displayMessages.length === 0 && !loading && !pendingAction && !showBookingCard;

  return (
    <div
      className={`relative flex w-full flex-col overflow-hidden bg-[#f5f5f7] ${
        embedded ? 'h-full min-h-0 rounded-2xl border border-black/5' : 'min-h-[calc(100vh-88px)]'
      }`}
    >
      <motion.div
        className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-[radial-gradient(circle_at_50%_0%,rgba(0,102,204,0.12),transparent_62%)]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.45, ease: 'easeOut' }}
      />

      <motion.div
        className="relative z-10 flex items-center justify-between px-4 py-4 md:px-8"
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
      >
        <div className="mx-auto flex max-w-3xl items-center gap-3 rounded-full border border-black/10 bg-white/86 px-3 py-2 shadow-[0_16px_48px_rgba(15,23,42,0.10)] backdrop-blur-xl">
          <div className={`h-10 w-10 shrink-0 overflow-hidden rounded-2xl shadow-sm ${PERSONA_FALLBACK_AVATAR}`}>
            {personaAvatarUrl ? (
              <img src={personaAvatarUrl} alt={personaName || 'Persona'} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs font-semibold">
                {initials}
              </div>
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold tracking-tight text-[#111111]">
              {mode === 'assistant' ? 'Your chief of staff' : (personaName || 'Persona')}
            </p>
            <p className="max-w-[56vw] truncate text-xs text-[#6e6e73] md:max-w-md">
              {mode === 'assistant'
                ? 'Keeps your persona sharp · drafts your follow-ups'
                : (personaProfile.roleLine || personaProfile.headline || 'Preview how this persona answers from approved context')}
            </p>
          </div>
          <AnimatePresence>
            {activeMode && (
              <motion.span
                className="hidden rounded-full bg-[#f5f5f7] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#0066cc] md:inline-flex"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.2 }}
              >
                {activeMode.mode}
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="absolute right-4 flex items-center gap-2 md:right-8">
          {hasVoice && mode !== 'assistant' && (
            <VoiceToggle
              enabled={voiceEnabled}
              onToggle={() => setVoiceEnabled((prev) => !prev)}
            />
          )}
          <button
            onClick={clearHistory}
            className="hidden cursor-pointer rounded-full border border-black/10 bg-white/75 px-3 py-1.5 text-[11px] font-semibold text-[#6e6e73] shadow-sm transition hover:bg-white hover:text-[#111111] md:inline-flex"
          >
            Clear
          </button>
        </div>
      </motion.div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden">
        {showPreviewIntro && mode === 'assistant' && (
          <motion.div
            className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 py-8 text-center md:px-0"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[#0066cc]">Chief of staff</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-[#111111] md:text-5xl">
              Let&apos;s sharpen your persona.
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-[#6e6e73] md:text-lg">
              I keep your persona sharp, tell you how it&apos;s landing, and draft your follow-ups. Pick one to start:
            </p>
            <div className="mx-auto mt-8 flex w-full max-w-2xl flex-wrap justify-center gap-2">
              {(presetQuestions.length ? presetQuestions : [
                'Find a gap in my persona',
                'What should visitors know about me?',
                'Draft a follow-up email',
              ]).map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => void sendMessage(q)}
                  disabled={loading || !!pendingAction}
                  className="cursor-pointer rounded-full border border-black/10 bg-white px-4 py-2 text-sm text-[#111111] shadow-sm transition hover:bg-[#f5f5f7] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </motion.div>
        )}
        {showPreviewIntro && mode !== 'assistant' && (
          <motion.div
            className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-5 py-8 text-center md:px-0"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            <div className={`mx-auto mb-5 h-28 w-28 overflow-hidden rounded-[2rem] shadow-[0_24px_70px_rgba(15,23,42,0.20)] ${PERSONA_FALLBACK_AVATAR}`}>
              {personaAvatarUrl ? (
                <img src={personaAvatarUrl} alt={personaName || 'Persona'} className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-3xl font-semibold">
                  {initials}
                </div>
              )}
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[#0066cc]">Persona Preview</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-[-0.045em] text-[#111111] md:text-6xl">
              Chat with {personaName || 'your persona'}.
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-[#6e6e73] md:text-lg">
              {personaProfile.bio || personaProfile.headline || 'Ask questions to see how your persona uses approved sources, profile context, and public boundaries.'}
            </p>
            <div className="mx-auto mt-8 w-full max-w-2xl text-left">
              <SuggestedQuestions
                twinId={twinId}
                presetQuestions={presetQuestions}
                onSelect={(question) => {
                  void sendMessage(question);
                }}
                disabled={loading || !!pendingAction || showBookingCard}
              />
            </div>
          </motion.div>
        )}

        {!showPreviewIntro && (
          <MessageList
            messages={displayMessages}
            loading={loading}
            isSearching={isSearching}
            twinId={twinId}
            personaName={personaName ?? undefined}
            personaAvatarUrl={personaAvatarUrl}
            conversationId={effectiveConversationId}
            mode={mode}
          />
        )}
      </div>

      <div className="relative z-20 shrink-0 px-4 pb-4 pt-3 md:px-8 md:pb-6">
        <AnimatePresence>
          {lastError && (
            <motion.div
              className="mx-auto mb-3 flex max-w-3xl items-center justify-between gap-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
            >
              <span>{lastError}</span>
              <button
                onClick={retryLastMessage}
                className="shrink-0 cursor-pointer rounded-xl border border-red-200 bg-white px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-red-600 transition-colors"
              >
                Retry
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {!showPreviewIntro && displayMessages.length === 0 && !loading && mode !== 'public' && mode !== 'assistant' && (
          <div className="mx-auto mb-3 w-full max-w-3xl">
            <SuggestedQuestions
              twinId={twinId}
              presetQuestions={presetQuestions}
              onSelect={(question) => {
                void sendMessage(question);
              }}
              disabled={loading || !!pendingAction || showBookingCard}
            />
          </div>
        )}

        {pendingAction && (
          <div className="mx-auto mb-3 w-full max-w-3xl">
            <ActionCollectForm
              fields={pendingAction.action.collect_fields}
              actionLabel={pendingAction.action.label}
              description={pendingAction.action.type === 'webhook' ? 'Share your details so we can connect you' : undefined}
              onSubmit={handleCollectSubmit}
              onCancel={handleCollectCancel}
              submitting={collectSubmitting}
            />
          </div>
        )}

        {showBookingCard && (
          <div className="mx-auto mb-3 w-full max-w-3xl">
            <BookingCard
              twinId={twinId}
              apiBaseUrl={apiBaseUrl}
              onBooked={handleBookingBooked}
              onCancel={handleBookingCancel}
              fallbackUrl={bookingFallbackUrl}
            />
          </div>
        )}

        <div
          id="chat-input"
          className="relative mx-auto flex w-full max-w-3xl items-end gap-2 rounded-[1.75rem] border border-black/10 bg-white/90 p-2 shadow-[0_18px_60px_rgba(15,23,42,0.14)] backdrop-blur-xl pb-[calc(0.5rem+env(safe-area-inset-bottom))]"
        >
          <button
            type="button"
            aria-label="Add context"
            className="mb-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[#6e6e73] transition hover:bg-[#f5f5f7] hover:text-[#111111]"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M12 5v14m-7-7h14" />
            </svg>
          </button>
          <div className="relative flex-1 rounded-2xl transition-shadow">
            <textarea
              value={input}
              onChange={(e) => {
                if (pendingAction || showBookingCard) return;
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = Math.min(e.target.scrollHeight, 150) + 'px';
              }}
              onKeyDown={(e) => {
                if (pendingAction || showBookingCard) return;
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                  e.preventDefault();
                  sendMessage();
                }
                if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                  e.preventDefault();
                  sendMessage();
                }
                if (e.key === 'Escape') e.currentTarget.blur();
              }}
              placeholder={
                pendingAction || showBookingCard
                  ? 'Complete the form above...'
                  : 'Ask your persona anything...'
              }
              rows={1}
              disabled={!!pendingAction || showBookingCard}
              aria-label="Chat message input"
              className="max-h-[150px] min-h-[48px] w-full resize-none overflow-hidden bg-transparent px-2 py-3.5 text-[15px] text-[#111111] placeholder:text-[#8e8e93] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>

          <div className="flex items-center gap-1.5 pb-0.5">
            <MicButton
              onTranscript={(text) => {
                setInput(text);
                sendMessage(text);
              }}
              disabled={loading || !!pendingAction || showBookingCard}
            />
            <motion.button
              onClick={() => sendMessage()}
              disabled={loading || !input.trim() || !!pendingAction || showBookingCard}
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
      <QuotaBlockedDialog
        open={quotaBlocked !== null}
        cap={quotaBlocked ?? 500}
        onClose={() => setQuotaBlocked(null)}
      />
    </div>
  );
}
