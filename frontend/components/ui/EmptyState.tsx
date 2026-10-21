'use client';

import React from 'react';
import Link from 'next/link';

export type EmptyStateIllustration = 
  | 'robot-building' 
  | 'robot-sleeping' 
  | 'checkmark' 
  | 'inbox-empty'
  | 'knowledge-empty'
  | 'chat-bubble';

interface EmptyStateProps {
  illustration: EmptyStateIllustration;
  title: string;
  description: string;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  theme?: 'light' | 'dark';
  className?: string;
}

interface EmptyStateAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

// SVG Illustrations
const Illustrations: Record<EmptyStateIllustration, React.ReactNode> = {
  'robot-building': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Robot head */}
      <rect x="35" y="20" width="50" height="45" rx="8" fill="#dbeafe" stroke="#2563EB" strokeWidth="2"/>
      {/* Eyes */}
      <circle cx="50" cy="42" r="6" fill="#2563EB" className="animate-pulse"/>
      <circle cx="70" cy="42" r="6" fill="#2563EB" className="animate-pulse" style={{ animationDelay: '0.2s' }}/>
      {/* Antenna */}
      <line x1="60" y1="20" x2="60" y2="8" stroke="#2563EB" strokeWidth="2"/>
      <circle cx="60" cy="6" r="3" fill="#f59e0b" className="animate-pulse"/>
      {/* Body being built */}
      <rect x="40" y="70" width="40" height="30" rx="4" fill="#f3f4f6" stroke="#9ca3af" strokeWidth="2" strokeDasharray="4 4"/>
      {/* Construction lines */}
      <line x1="30" y1="85" x2="10" y2="85" stroke="#10b981" strokeWidth="2" className="animate-pulse"/>
      <line x1="90" y1="85" x2="110" y2="85" stroke="#10b981" strokeWidth="2" className="animate-pulse" style={{ animationDelay: '0.3s' }}/>
      {/* Tools */}
      <circle cx="20" cy="95" r="5" fill="#f59e0b" opacity="0.6"/>
      <circle cx="100" cy="95" r="5" fill="#f59e0b" opacity="0.6"/>
    </svg>
  ),
  'robot-sleeping': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Robot head */}
      <rect x="35" y="30" width="50" height="40" rx="8" fill="#dbeafe" stroke="#2563EB" strokeWidth="2"/>
      {/* Sleeping eyes (lines) */}
      <line x1="44" y1="48" x2="56" y2="48" stroke="#2563EB" strokeWidth="2" strokeLinecap="round"/>
      <line x1="64" y1="48" x2="76" y2="48" stroke="#2563EB" strokeWidth="2" strokeLinecap="round"/>
      {/* Sleep zzz */}
      <text x="90" y="30" fontSize="12" fill="#9ca3af" className="animate-pulse">Z</text>
      <text x="98" y="22" fontSize="10" fill="#9ca3af" className="animate-pulse" style={{ animationDelay: '0.5s' }}>z</text>
      <text x="104" y="16" fontSize="8" fill="#9ca3af" className="animate-pulse" style={{ animationDelay: '1s' }}>z</text>
      {/* Body */}
      <rect x="40" y="75" width="40" height="25" rx="4" fill="#dbeafe" stroke="#2563EB" strokeWidth="2"/>
    </svg>
  ),
  'checkmark': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Circle background */}
      <circle cx="60" cy="60" r="45" fill="#d1fae5" stroke="#10b981" strokeWidth="2"/>
      {/* Checkmark */}
      <path 
        d="M38 60 L52 74 L82 44" 
        stroke="#10b981" 
        strokeWidth="4" 
        strokeLinecap="round" 
        strokeLinejoin="round"
        fill="none"
        className="animate-in fade-in duration-500"
      />
      {/* Sparkles */}
      <circle cx="25" cy="45" r="3" fill="#f59e0b" className="animate-pulse"/>
      <circle cx="95" cy="35" r="2" fill="#f59e0b" className="animate-pulse" style={{ animationDelay: '0.3s' }}/>
      <circle cx="100" cy="75" r="4" fill="#f59e0b" className="animate-pulse" style={{ animationDelay: '0.6s' }}/>
    </svg>
  ),
  'inbox-empty': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Inbox tray */}
      <path 
        d="M20 40 L20 85 Q20 95 30 95 L90 95 Q100 95 100 85 L100 40 L75 65 L45 65 Z" 
        fill="#f3f4f6" 
        stroke="#9ca3af" 
        strokeWidth="2"
      />
      {/* Paper inside */}
      <rect x="35" y="25" width="50" height="40" rx="2" fill="white" stroke="#d1d5db" strokeWidth="1"/>
      {/* Lines on paper */}
      <line x1="42" y1="38" x2="78" y2="38" stroke="#e5e7eb" strokeWidth="2"/>
      <line x1="42" y1="48" x2="78" y2="48" stroke="#e5e7eb" strokeWidth="2"/>
      <line x1="42" y1="58" x2="65" y2="58" stroke="#e5e7eb" strokeWidth="2"/>
    </svg>
  ),
  'knowledge-empty': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Book/document stack */}
      <rect x="30" y="65" width="60" height="8" rx="1" fill="#dbeafe" stroke="#2563EB" strokeWidth="1.5"/>
      <rect x="32" y="55" width="56" height="8" rx="1" fill="#dbeafe" stroke="#2563EB" strokeWidth="1.5"/>
      <rect x="34" y="45" width="52" height="8" rx="1" fill="#dbeafe" stroke="#2563EB" strokeWidth="1.5"/>
      {/* Plus icon */}
      <circle cx="85" cy="35" r="15" fill="#10b981" className="animate-pulse"/>
      <line x1="85" y1="28" x2="85" y2="42" stroke="white" strokeWidth="3" strokeLinecap="round"/>
      <line x1="78" y1="35" x2="92" y2="35" stroke="white" strokeWidth="3" strokeLinecap="round"/>
    </svg>
  ),
  'chat-bubble': (
    <svg viewBox="0 0 120 120" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Chat bubble 1 */}
      <path 
        d="M20 30 Q20 20 30 20 L70 20 Q80 20 80 30 L80 55 Q80 65 70 65 L50 65 L35 75 L38 65 L30 65 Q20 65 20 55 Z" 
        fill="#dbeafe" 
        stroke="#2563EB" 
        strokeWidth="2"
      />
      {/* Lines in bubble */}
      <line x1="32" y1="35" x2="68" y2="35" stroke="#2563EB" strokeWidth="2" opacity="0.5"/>
      <line x1="32" y1="45" x2="55" y2="45" stroke="#2563EB" strokeWidth="2" opacity="0.5"/>
      {/* Chat bubble 2 */}
      <path 
        d="M40 75 Q40 65 50 65 L90 65 Q100 65 100 75 L100 100 Q100 110 90 110 L70 110 L55 120 L58 110 L50 110 Q40 110 40 100 Z" 
        fill="#f3f4f6" 
        stroke="#9ca3af" 
        strokeWidth="2"
      />
    </svg>
  ),
};

interface ActionButtonProps {
  action: EmptyStateAction;
  variant: 'primary' | 'secondary';
}

function ActionButton({ action, variant }: ActionButtonProps) {
  const baseClasses = variant === 'primary'
    ? 'px-6 py-2.5 bg-blue-600 text-white font-semibold rounded-xl hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'
    : 'px-6 py-2.5 bg-white text-slate-700 font-semibold rounded-xl border border-slate-200 hover:bg-slate-50 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2';

  if (action.href) {
    return (
      <Link href={action.href} className={baseClasses}>
        {action.label}
      </Link>
    );
  }

  return (
    <button type="button" onClick={action.onClick} className={baseClasses}>
      {action.label}
    </button>
  );
}

export function EmptyState({
  illustration,
  title,
  description,
  primaryAction,
  secondaryAction,
  theme = 'light',
  className = '',
}: EmptyStateProps) {
  const titleClass = theme === 'dark' ? 'text-white' : 'text-slate-900';
  const descriptionClass = theme === 'dark' ? 'text-slate-300' : 'text-slate-500';

  return (
    <div className={`flex flex-col items-center justify-center text-center p-8 ${className}`}>
      {/* Illustration */}
      <div className="w-32 h-32 mb-6">
        {Illustrations[illustration]}
      </div>

      {/* Title */}
      <h3 className={`text-xl font-bold mb-2 ${titleClass}`}>
        {title}
      </h3>

      {/* Description */}
      <p className={`max-w-sm mb-6 ${descriptionClass}`}>
        {description}
      </p>

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-center gap-3">
        {primaryAction && <ActionButton action={primaryAction} variant="primary" />}
        {secondaryAction && <ActionButton action={secondaryAction} variant="secondary" />}
      </div>
    </div>
  );
}

// Specialized empty states for common scenarios
export function EmptyDashboard({ onCreateTwin }: { onCreateTwin?: () => void }) {
  return (
    <EmptyState
      illustration="robot-building"
      title="Create your first persona"
      description="Train an AI that answers questions in your voice from your sources."
      primaryAction={{
        label: 'Get Started',
        href: '/dashboard/studio',
      }}
      secondaryAction={onCreateTwin ? {
        label: 'Learn More',
        onClick: onCreateTwin,
      } : undefined}
    />
  );
}

export function EmptyTwinNoActivity({ twinName }: { twinName?: string }) {
  return (
    <EmptyState
      illustration="robot-sleeping"
      title={twinName ? `${twinName} is ready` : 'Your persona is ready'}
      description="Your persona is ready but hasn't had any conversations yet. Test it out!"
      primaryAction={{
        label: 'Test Your Persona',
        href: '/dashboard/chat',
      }}
    />
  );
}

export function EmptyKnowledge({ onAddSource }: { onAddSource?: () => void }) {
  return (
    <EmptyState
      illustration="knowledge-empty"
      title="Add your sources"
      description="Upload documents, connect URLs, or paste text to build your persona."
      primaryAction={{
        label: 'Add Source',
        onClick: onAddSource,
        href: '/dashboard/knowledge',
      }}
    />
  );
}

export default EmptyState;
