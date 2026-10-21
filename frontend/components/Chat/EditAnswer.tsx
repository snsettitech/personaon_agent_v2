'use client';

import React, { useState } from 'react';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

interface EditAnswerProps {
  question: string;        // The user message (Q) paired with this assistant message
  originalAnswer: string;  // The assistant message content
  conversationId: string;  // For the promote endpoint URL
}

export default function EditAnswer({ question, originalAnswer, conversationId }: EditAnswerProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedAnswer, setEditedAnswer] = useState(originalAnswer);
  const [isPromoting, setIsPromoting] = useState(false);
  const [promoted, setPromoted] = useState(false);

  const handlePromote = async () => {
    setIsPromoting(true);
    try {
      const apiBase = resolveApiBaseUrl();
      const res = await authFetchStandalone(
        `${apiBase}/v2/chat/conversations/${conversationId}/promote`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, answer: editedAnswer.trim() }),
        }
      );
      if (res.ok) {
        setPromoted(true);
        setIsEditing(false);
      } else {
        console.error('[EditAnswer] Promote failed:', res.status);
      }
    } catch (err) {
      console.error('[EditAnswer] Promote error:', err);
    } finally {
      setIsPromoting(false);
    }
  };

  if (promoted) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
        </svg>
        Answer Improved
      </span>
    );
  }

  if (isEditing) {
    return (
      <div className="mt-2 space-y-2">
        <textarea
          value={editedAnswer}
          onChange={(e) => setEditedAnswer(e.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-800 leading-relaxed focus:border-[#0066cc] focus:ring-1 focus:ring-[#0066cc]/30 outline-none resize-y min-h-[80px]"
        />
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsEditing(false)}
            className="text-xs text-slate-500 hover:text-slate-700 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handlePromote}
            disabled={isPromoting || editedAnswer.trim() === '' || editedAnswer.trim() === originalAnswer.trim()}
            className="text-xs font-medium text-white bg-[#0066cc] hover:bg-[#0057ad] px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            {isPromoting ? 'Saving...' : 'Save & Improve'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={() => {
        setIsEditing(true);
        setEditedAnswer(originalAnswer);
      }}
      className="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-slate-500 hover:text-[#0b3d91] hover:bg-[#eef5ff] transition-all"
    >
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
      Edit Answer
    </button>
  );
}
