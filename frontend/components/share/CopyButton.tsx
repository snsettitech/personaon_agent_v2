'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';

interface CopyButtonProps {
  text: string;
  label?: string;
  copiedLabel?: string;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'primary' | 'secondary' | 'ghost';
  onCopied?: () => void;
  className?: string;
  iconOnly?: boolean;
  title?: string;
}

export function CopyButton({
  text,
  label = 'Copy',
  copiedLabel = 'Copied!',
  size = 'md',
  variant = 'primary',
  onCopied,
  className = '',
  iconOnly = false,
  title,
}: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'error'>('idle');
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleCopy = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
      onCopied?.();
      timerRef.current = setTimeout(() => setState('idle'), 2200);
    } catch {
      setState('error');
      timerRef.current = setTimeout(() => setState('idle'), 1500);
    }
  }, [text, onCopied]);

  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  }[size];

  const baseClasses = 'font-semibold rounded-xl transition-all duration-200 cursor-pointer select-none';

  const variantClasses = state === 'copied'
    ? 'bg-emerald-500 text-white scale-105 shadow-lg shadow-emerald-200'
    : state === 'error'
    ? 'bg-red-500 text-white'
    : {
        primary: 'bg-[#0066cc] hover:bg-[#0057ad] text-white shadow-sm hover:shadow-md hover:scale-[1.02]',
        secondary: 'bg-[#F5F0EB] hover:bg-[#E7E5E4] text-[#1C1917]',
        ghost: 'bg-transparent hover:bg-[#eef5ff] text-[#0066cc] border border-[#0066cc]/20',
      }[variant];

  const icon = state === 'copied' ? (
    <svg className="w-4 h-4 mr-1.5 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  ) : (
    <svg className="w-4 h-4 mr-1.5 inline-block opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  );

  return (
    <button
      onClick={handleCopy}
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      title={title}
      aria-label={
        state === 'copied' ? copiedLabel :
        state === 'error'  ? 'Copy failed, try again' :
        label
      }
    >
      {icon}
      <span className={iconOnly ? 'sr-only' : undefined}>
        {state === 'copied' ? copiedLabel : state === 'error' ? 'Try again' : label}
      </span>
    </button>
  );
}
