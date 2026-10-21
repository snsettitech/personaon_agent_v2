import { useCallback, useRef, useState } from 'react';
import { resolveApiBaseUrl } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AskPersona {
  twin_id: string;
  display_name: string;
  occupation: string;
  headline: string;
  avatar_url: string;
  verified_profile: boolean;
  public_url: string | null;
}

export interface AskResult {
  persona: AskPersona;
  snippet: string;
  relevance: number;
}

interface AskResponse {
  results: AskResult[];
  query: string;
}

interface UseMarketplaceAskReturn {
  results: AskResult[];
  query: string;
  loading: boolean;
  error: string | null;
  ask: (question: string) => void;
  clear: () => void;
  isAskMode: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Detect whether input looks like a question (semantic search)
 * vs a keyword lookup (name/occupation search).
 */
function looksLikeQuestion(input: string): boolean {
  const trimmed = input.trim();
  if (trimmed.length < 12) return false;
  if (trimmed.includes('?')) return true;
  const questionStarters = /^(how|what|why|when|where|who|can|should|is|are|do|does|tell me|explain|help me|i want|i need)/i;
  return questionStarters.test(trimmed);
}

const DEBOUNCE_MS = 600;

export function useMarketplaceAsk(): UseMarketplaceAskReturn {
  const [results, setResults] = useState<AskResult[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAskMode, setIsAskMode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const ask = useCallback((question: string) => {
    const trimmed = question.trim();

    // Clear any pending debounce
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    // Not a question — exit ask mode
    if (!looksLikeQuestion(trimmed)) {
      setIsAskMode(false);
      setResults([]);
      setQuery('');
      setError(null);
      return;
    }

    setIsAskMode(true);

    // Debounce the actual API call
    timerRef.current = setTimeout(async () => {
      // Abort previous in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError(null);
      setQuery(trimmed);

      try {
        const base = resolveApiBaseUrl();
        const res = await fetch(`${base}/public/marketplace/ask`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: trimmed, limit: 10 }),
          signal: controller.signal,
        });

        if (!res.ok) {
          throw new Error(`Search failed (${res.status})`);
        }

        const data = (await res.json()) as AskResponse;
        setResults(data.results);
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        const msg = err instanceof Error ? err.message : 'Search failed';
        setError(msg);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
  }, []);

  const clear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (abortRef.current) abortRef.current.abort();
    setResults([]);
    setQuery('');
    setError(null);
    setIsAskMode(false);
    setLoading(false);
  }, []);

  return { results, query, loading, error, ask, clear, isAskMode };
}
