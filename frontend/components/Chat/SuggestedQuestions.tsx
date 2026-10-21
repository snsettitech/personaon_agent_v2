'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';

import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';

interface Question {
  question: string;
  count: number;
  citation_rate?: number;
}

interface SuggestedQuestionsProps {
  twinId: string;
  onSelect: (question: string) => void;
  disabled?: boolean;
  presetQuestions?: string[];
}

// Default fallback questions when no data available
const DEFAULT_QUESTIONS = [
  'What can you help me with?',
  'Tell me about yourself',
  'What topics do you know about?',
  'How do you work?',
];

// Onboarding questions for new twins
const ONBOARDING_QUESTIONS = [
  "What's your main area of expertise?",
  'How would you describe your approach?',
  'What makes you different?',
  'What should I know about you?',
];

export default function SuggestedQuestions({ twinId, onSelect, disabled, presetQuestions }: SuggestedQuestionsProps) {
  const [questions, setQuestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDefaults, setUsingDefaults] = useState(false);

  const supabase = getSupabaseClient();

  const getAuthToken = useCallback(async (): Promise<string | null> => {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token || null;
  }, [supabase]);

  const fetchQuestions = useCallback(async () => {
    const normalizedPreset = Array.isArray(presetQuestions)
      ? presetQuestions
          .map((q) => (typeof q === 'string' ? q.trim() : ''))
          .filter((q) => q.length > 0)
      : [];

    if (normalizedPreset.length > 0) {
      setQuestions(Array.from(new Set(normalizedPreset)).slice(0, 12));
      setUsingDefaults(false);
      setError(null);
      setLoading(false);
      return;
    }

    if (!twinId) {
      setQuestions(ONBOARDING_QUESTIONS);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const token = await getAuthToken();
      
      // Try to fetch top questions from API
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.METRICS_TOP_QUESTIONS(twinId)}?limit=5`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      });

      if (response.ok) {
        const data: Question[] = await response.json();
        
        if (data && data.length > 0) {
          // Use real questions from API
          setQuestions(data.map(q => q.question));
          setUsingDefaults(false);
        } else {
          // No questions yet, use defaults
          setQuestions(DEFAULT_QUESTIONS);
          setUsingDefaults(true);
        }
      } else if (response.status === 404) {
        // API not available, use defaults
        setQuestions(DEFAULT_QUESTIONS);
        setUsingDefaults(true);
      } else {
        throw new Error(`API error: ${response.status}`);
      }
    } catch (err) {
      console.error('Failed to fetch suggested questions:', err);
      setError('Failed to load suggestions');
      setQuestions(DEFAULT_QUESTIONS);
      setUsingDefaults(true);
    } finally {
      setLoading(false);
    }
  }, [twinId, getAuthToken, presetQuestions]);

  useEffect(() => {
    fetchQuestions();
  }, [fetchQuestions]);

  if (loading) {
    return (
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-9 w-40 flex-shrink-0 animate-pulse rounded-full bg-black/5"
          />
        ))}
      </div>
    );
  }

  if (questions.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {/* Label */}
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6e6e73]">
        {Array.isArray(presetQuestions) && presetQuestions.length > 0
          ? 'Popular Questions to this Profile'
          : usingDefaults
            ? 'Suggested questions'
            : 'Popular questions'}
      </p>
      
      {/* Questions */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide -mx-1 px-1">
        {questions.map((question, index) => (
          <button
            key={index}
            onClick={() => !disabled && onSelect(question)}
            disabled={disabled}
            className={`flex-shrink-0 rounded-full border border-black/10 bg-white px-4 py-2 text-sm text-[#1d1d1f] shadow-sm
              whitespace-nowrap transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#0066cc]/25 focus:ring-offset-1
              ${disabled
                ? 'opacity-50 cursor-not-allowed'
                : 'cursor-pointer hover:border-[#0066cc]/30 hover:bg-[#f5f5f7] hover:text-[#0066cc]'
              }`}
            title={question}
          >
            {question.length > 40 ? question.slice(0, 40) + '...' : question}
          </button>
        ))}
      </div>
      
      {/* Error indicator (subtle) */}
      {error && usingDefaults && (
        <p className="text-xs text-slate-400 italic">
          Showing default suggestions
        </p>
      )}
    </div>
  );
}

// Horizontal scrollbar hide utility
const scrollbarHideStyles = `
  .scrollbar-hide::-webkit-scrollbar {
    display: none;
  }
  .scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
  }
`;

// Inject styles if not already present
if (typeof document !== 'undefined') {
  const styleId = 'suggested-questions-styles';
  if (!document.getElementById(styleId)) {
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = scrollbarHideStyles;
    document.head.appendChild(style);
  }
}
