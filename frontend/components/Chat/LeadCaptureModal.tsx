'use client';

import React, { useState, useEffect, useRef } from 'react';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface LeadCaptureModalProps {
  leadId: string;
  personaName: string;
  capturePrompt?: string;
  apiBaseUrl: string;
  onSuccess: (name: string, email: string) => void;
  onSkip: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const RATE_LIMIT_COOLDOWN_MS = 60_000; // 60 s before re-enabling the button after a 429

export default function LeadCaptureModal({
  leadId,
  personaName,
  capturePrompt,
  apiBaseUrl,
  onSuccess,
  onSkip,
}: LeadCaptureModalProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState(false);

  const nameInputRef = useRef<HTMLInputElement>(null);
  const skipButtonRef = useRef<HTMLButtonElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Auto-focus name input on mount
  useEffect(() => {
    nameInputRef.current?.focus();
  }, []);

  // Focus trap: keep Tab navigation inside the modal
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      onSkip();
      return;
    }

    if (e.key !== 'Tab') return;

    const focusable = cardRef.current?.querySelectorAll<HTMLElement>(
      'input:not([disabled]), button:not([disabled])',
    );
    if (!focusable || focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      // Shift+Tab from first element → wrap to last
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      // Tab from last element → wrap to first
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const handleSubmit = async () => {
    // Client-side validation
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      setValidationError('Please enter a valid email address.');
      return;
    }

    setValidationError(null);
    setSubmitError(null);
    setLoading(true);

    try {
      const res = await fetch(`${apiBaseUrl}/widget/lead/${leadId}/capture`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          visitor_name: name.trim() || '',
          visitor_email: trimmedEmail,
        }),
      });

      if (!res.ok) {
        if (res.status === 429) {
          setRateLimited(true);
          setSubmitError('Too many attempts. Please wait a few minutes.');
          setLoading(false);
          // Re-enable button after cooldown
          setTimeout(() => {
            setRateLimited(false);
            setSubmitError(null);
          }, RATE_LIMIT_COOLDOWN_MS);
          return;
        }
        throw new Error(`Request failed with status ${res.status}`);
      }

      onSuccess(name.trim(), trimmedEmail);
    } catch {
      setSubmitError('Something went wrong. Try again.');
      setLoading(false);
    }
  };

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setEmail(e.target.value);
    if (validationError) {
      setValidationError(null);
    }
  };

  const headline = capturePrompt ?? 'Stay in the loop';
  const descriptionId = 'lead-capture-description';

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-label="Stay in the loop"
      aria-describedby={descriptionId}
    >
      {/* Card — focus trap boundary */}
      <div
        ref={cardRef}
        className="w-full max-w-sm rounded-2xl bg-white shadow-2xl p-6 mx-4 space-y-4"
      >

        {/* Logo */}
        <div className="text-center">
          <span className="text-base font-bold text-[#0066cc]">PersonaOn</span>
        </div>

        {/* Divider */}
        <div className="border-t border-slate-100" />

        {/* Headline */}
        <div className="space-y-1 text-center">
          <h2 className="text-base font-bold text-slate-800">{headline}</h2>
          <p id={descriptionId} className="text-sm text-slate-500">
            Leave your details and {personaName} will follow up.
          </p>
        </div>

        {/* Form */}
        <div className="space-y-3">
          {/* Name */}
          <input
            ref={nameInputRef}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={loading || rateLimited}
            placeholder="Your name (optional)"
            maxLength={200}
            className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          />

          {/* Email */}
          <div className="space-y-1">
            <input
              type="email"
              value={email}
              onChange={handleEmailChange}
              disabled={loading || rateLimited}
              placeholder="Email address"
              className={`w-full rounded-xl border px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/20 focus:border-[#0066cc] transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                validationError ? 'border-rose-300' : 'border-slate-200'
              }`}
            />
            {validationError && (
              <p className="text-xs text-rose-500">{validationError}</p>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="space-y-2 pt-1">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading || rateLimited}
            className="w-full bg-[#0066cc] text-white rounded-xl py-2.5 text-sm font-bold hover:brightness-105 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-95"
          >
            {loading ? 'Sending...' : 'Continue'}
          </button>

          {submitError && (
            <p className="text-xs text-red-500 text-center">{submitError}</p>
          )}

          <div className="text-center">
            <button
              ref={skipButtonRef}
              type="button"
              onClick={onSkip}
              disabled={loading}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors disabled:cursor-not-allowed"
            >
              Skip for now
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
