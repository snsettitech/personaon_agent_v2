'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Minimum character length of residual text (after removing trigger keyword)
 * to consider the message as "more than just the trigger." When exceeded, the
 * message is also forwarded to the agent alongside the action response.
 */
export const MIN_RESIDUAL_CONTENT_LENGTH = 5;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape returned by the GET /v2/actions/{twin_id}/available endpoint. */
export interface TriggerAction {
  id: string;
  type: 'booking_link' | 'webhook' | 'respond_with_message' | 'mode_switch' | 'native_calendar';
  trigger: string;      // Legacy single trigger (backward compat)
  triggers: string[];   // Multi-keyword array (primary)
  label: string;
  collect_fields: string[];
}

/** Discriminated union: either a match with its action or no match. */
export type TriggerMatchResult =
  | { matched: true; action: TriggerAction; matchedKeyword: string }
  | { matched: false };

// ---------------------------------------------------------------------------
// Pure functions
// ---------------------------------------------------------------------------

/**
 * Case-insensitive contains-match against all configured trigger keywords.
 * Returns the first match found (first action, first keyword).
 */
export function matchTrigger(
  message: string,
  actions: TriggerAction[],
): TriggerMatchResult {
  const normalizedMessage = message.toLowerCase().trim();
  if (!normalizedMessage) return { matched: false };

  for (const action of actions) {
    const keywords =
      action.triggers?.length ? action.triggers : [action.trigger];

    for (const keyword of keywords) {
      if (!keyword) continue;
      const normalizedKeyword = keyword.toLowerCase().trim();
      if (!normalizedKeyword) continue;

      if (normalizedMessage.includes(normalizedKeyword)) {
        return { matched: true, action, matchedKeyword: keyword };
      }
    }
  }

  return { matched: false };
}

/**
 * Format an action execution result into a natural persona message.
 * Pure function -- handles all 4 action types + fallback.
 */
export function formatActionResponse(
  action: TriggerAction,
  result: Record<string, unknown>,
): string {
  if (action.type === 'booking_link' && result.url) {
    return result.message
      ? `${result.message}\n\n${result.url}`
      : `Sure! Here's my calendar -- pick a time that works for you:\n\n${result.url}`;
  } else if (action.type === 'respond_with_message' && result.message) {
    return String(result.message);
  } else if (action.type === 'webhook') {
    // Check for webhook failure (backend returns webhook_status for HTTP errors)
    const webhookStatus = result.webhook_status as number | undefined;
    if (webhookStatus && webhookStatus >= 400) {
      return "I tried to send your information, but the service is temporarily unavailable. Please try again later.";
    }
    return String(result.confirmation || "Got it! I've noted your request.");
  } else if (action.type === 'mode_switch') {
    return String(result.message || `Switched to ${result.mode || 'a different'} mode.`);
  } else if (action.type === 'native_calendar') {
    // native_calendar is handled by BookingCard inline — this is a fallback
    return String(result.message || "Let me pull up my calendar for you...");
  }
  return String(result.message || 'Done!');
}

/**
 * Execute a triggered action via the backend and return formatted response text.
 * Calls POST /v2/actions/{twin_id}/execute and uses formatActionResponse for DRY.
 */
export async function executeTriggeredAction(
  apiBaseUrl: string,
  twinId: string,
  action: TriggerAction,
  collectedData?: Record<string, string>,
): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/v2/actions/${twinId}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action_id: action.id,
      collected_data: collectedData || {},
    }),
  });

  if (response.ok) {
    const data = await response.json();
    const result = (data.result || {}) as Record<string, unknown>;
    return formatActionResponse(action, result);
  }
  return "Sorry, I couldn't process that right now. Please try again.";
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * React hook that provides trigger matching for chat messages.
 *
 * - For **owner/dashboard** mode: pass `actions` directly (from twin settings)
 *   and set `twinId` to `null` to skip the API fetch.
 * - For **public** chat: pass `twinId` to fetch available actions from the API
 *   and omit `actions`.
 *
 * Actions are cached for the session (only re-fetched on twinId change).
 */
export function useTriggerMatcher(
  twinId: string | null,
  actions?: TriggerAction[],
) {
  const [fetchedActions, setFetchedActions] = useState<TriggerAction[]>([]);
  const [loaded, setLoaded] = useState(false);
  const fetchedForRef = useRef<string | null>(null);

  useEffect(() => {
    // If actions are provided directly (dashboard mode), use those
    if (actions) {
      setFetchedActions(actions);
      setLoaded(true);
      return;
    }

    // If no twinId, nothing to fetch
    if (!twinId) {
      setFetchedActions([]);
      setLoaded(true);
      return;
    }

    // Skip re-fetch if we already fetched for this twinId
    if (fetchedForRef.current === twinId) return;

    let cancelled = false;
    const fetchActions = async () => {
      try {
        const apiBaseUrl = resolveApiBaseUrl();
        const res = await fetch(
          `${apiBaseUrl}/v2/actions/${twinId}/available`,
        );
        if (!res.ok) {
          setFetchedActions([]);
          setLoaded(true);
          return;
        }
        const data = await res.json();
        const rawActions = (data.actions || []) as Array<Record<string, unknown>>;
        if (!cancelled) {
          const mapped: TriggerAction[] = rawActions.map((a) => ({
            id: String(a.id || ''),
            type: String(a.type || '') as TriggerAction['type'],
            trigger: String(a.trigger || ''),
            triggers: Array.isArray(a.triggers)
              ? a.triggers.map(String)
              : [String(a.trigger || '')],
            label: String(a.label || ''),
            collect_fields: Array.isArray(a.collect_fields)
              ? a.collect_fields.map(String)
              : [],
          }));
          setFetchedActions(mapped);
          fetchedForRef.current = twinId;
          setLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setFetchedActions([]);
          setLoaded(true);
        }
      }
    };

    void fetchActions();
    return () => {
      cancelled = true;
    };
  }, [twinId, actions]);

  const resolvedActions = actions || fetchedActions;

  const checkTrigger = useCallback(
    (message: string): TriggerMatchResult => {
      return matchTrigger(message, resolvedActions);
    },
    [resolvedActions],
  );

  return { actions: resolvedActions, loaded, checkTrigger };
}
