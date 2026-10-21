'use client';

import { useState, useRef, useEffect } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { analytics } from '@/lib/analytics/events';

interface OTPVerifyScreenProps {
  email: string;
  context: 'signup' | 'login';
  onSuccess: (session: { access_token: string; user: { id: string; email?: string } }) => void;
  onBack: () => void;
}

export function OTPVerifyScreen({ email, context, onSuccess, onBack }: OTPVerifyScreenProps) {
  const [digits, setDigits] = useState(['', '', '', '', '', '', '', '']);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [attempts, setAttempts] = useState(0);
  const [resendCooldown, setResendCooldown] = useState(30);
  const [resending, setResending] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const supabase = getSupabaseClient();

  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => setResendCooldown(c => c - 1), 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  const handleDigitChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, '').slice(-1);
    const newDigits = [...digits];
    newDigits[index] = digit;
    setDigits(newDigits);
    setError('');

    if (digit && index < 7) {
      inputRefs.current[index + 1]?.focus();
    }

    if (newDigits.every(d => d !== '') && digit) {
      verify(newDigits.join(''));
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 8);
    if (pasted.length === 8) {
      const newDigits = pasted.split('');
      setDigits(newDigits);
      setError('');
      verify(pasted);
    }
  };

  const verify = async (token: string) => {
    setLoading(true);
    setError('');
    const newAttempts = attempts + 1;
    setAttempts(newAttempts);

    const { data, error: verifyError } = await supabase.auth.verifyOtp({
      email,
      token,
      type: 'email',
    });

    if (verifyError) {
      analytics.otpFailed({ context, error: verifyError.message, attempts: newAttempts });
      setError('Incorrect code — please check and try again.');
      setDigits(['', '', '', '', '', '', '', '']);
      setLoading(false);
      inputRefs.current[0]?.focus();
      return;
    }

    if (data.session) {
      analytics.otpVerified({ context });
      onSuccess({
        access_token: data.session.access_token,
        user: { id: data.session.user.id, email: data.session.user.email },
      });
    }
    setLoading(false);
  };

  const handleResend = async () => {
    setResending(true);
    setError('');
    const { error: resendError } = await supabase.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true },
    });
    if (resendError) {
      setError('Failed to resend — please try again.');
    } else {
      analytics.otpResent({ context });
      setResendCooldown(30);
      setDigits(['', '', '', '', '', '', '', '']);
      setTimeout(() => inputRefs.current[0]?.focus(), 50);
    }
    setResending(false);
  };

  return (
    <div className="text-center">
      <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-[var(--signal)] flex items-center justify-center">
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      </div>

      <h1 className="text-2xl font-bold text-[#1d1d1f] mb-2">Check your email</h1>
      <p className="text-[rgba(29,29,31,0.58)] mb-1">We sent an 8-digit code to</p>
      <p className="text-[#1d1d1f] font-semibold mb-8">{email}</p>

      {error && (
        <div className="mb-4 p-3 bg-[#FEE2E2] border border-[#DC2626]/30 rounded-xl text-[#DC2626] text-sm">
          {error}
        </div>
      )}

      <div className="flex gap-3 justify-center mb-6" onPaste={handlePaste}>
        {digits.map((digit, i) => (
          <input
            key={i}
            ref={el => { inputRefs.current[i] = el; }}
            type="text"
            inputMode="numeric"
            maxLength={1}
            value={digit}
            onChange={e => handleDigitChange(i, e.target.value)}
            onKeyDown={e => handleKeyDown(i, e)}
            disabled={loading}
            className={`w-12 h-14 text-center text-xl font-bold rounded-xl border-2 transition-all outline-none
              ${digit ? 'border-[var(--signal)] bg-[rgba(0,102,204,0.05)]' : 'border-[rgba(29,29,31,0.10)] bg-white'}
              ${loading ? 'opacity-50' : ''}
              focus:border-[var(--signal)] focus:ring-4 focus:ring-[rgba(0,102,204,0.14)]
              text-[#1d1d1f]`}
          />
        ))}
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 text-[rgba(29,29,31,0.58)] text-sm mb-4">
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          Verifying...
        </div>
      )}

      <div className="flex items-center justify-center gap-4 text-sm">
        {resendCooldown > 0 ? (
          <span className="text-[rgba(29,29,31,0.40)]">Resend in {resendCooldown}s</span>
        ) : (
          <button
            onClick={handleResend}
            disabled={resending}
            className="text-[var(--signal)] hover:text-[var(--signal-deep)] font-medium cursor-pointer disabled:opacity-50"
          >
            {resending ? 'Sending...' : 'Resend code'}
          </button>
        )}
        <span className="text-[rgba(29,29,31,0.18)]">·</span>
        <button onClick={onBack} className="text-[rgba(29,29,31,0.58)] hover:text-[#1d1d1f] cursor-pointer">
          ← Back
        </button>
      </div>

      <p className="text-xs text-[rgba(29,29,31,0.40)] mt-6">Code expires in 10 minutes</p>
    </div>
  );
}
