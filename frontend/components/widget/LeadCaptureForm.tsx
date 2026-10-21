'use client';

import { useState } from 'react';

interface LeadCaptureFormProps {
  prompt: string;
  personaName: string;
  bubbleColor?: string;
  onSubmit: (lead: { name: string; email: string }) => Promise<void>;
  onSkip?: () => void;
}

export function LeadCaptureForm({ prompt, personaName, bubbleColor = '#0F766E', onSubmit, onSkip }: LeadCaptureFormProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !email.includes('@')) {
      setError('Please enter a valid email');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), email: email.trim() });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Something went wrong';
      setError(msg);
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center h-full p-6 bg-white">
      <div
        className="w-14 h-14 rounded-full mb-4 flex items-center justify-center"
        style={{ backgroundColor: bubbleColor }}
      >
        <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      </div>

      <h2 className="text-lg font-bold text-[#1C1917] mb-1">Chat with {personaName}</h2>
      <p className="text-sm text-[#57534E] text-center mb-6 px-2">{prompt}</p>

      {error && (
        <div className="w-full mb-3 p-2 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs text-center">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="w-full space-y-3">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          maxLength={120}
          className="w-full px-3 py-2 text-sm border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/30"
        />
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Your email"
          required
          maxLength={255}
          className="w-full px-3 py-2 text-sm border border-[#D6D3D1] rounded-xl text-[#1C1917] placeholder-[#A8A29E] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/30"
        />

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2.5 rounded-xl text-white font-semibold text-sm transition-all disabled:opacity-50"
          style={{ backgroundColor: bubbleColor }}
        >
          {submitting ? 'Starting…' : 'Start chatting'}
        </button>

        {onSkip && (
          <button
            type="button"
            onClick={onSkip}
            className="w-full text-xs text-[#A8A29E] hover:text-[#57534E] py-1 cursor-pointer"
          >
            Skip for now
          </button>
        )}
      </form>

      <p className="text-[10px] text-[#A8A29E] text-center mt-4 px-2">
        Your email stays with {personaName}. No spam, no sharing.
      </p>
    </div>
  );
}
