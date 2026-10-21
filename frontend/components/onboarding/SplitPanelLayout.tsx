'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface SplitPanelLayoutProps {
  children: React.ReactNode;
  onBack?: () => void;
  /** Unique key for the current step — changing it triggers the slide transition. */
  stepKey?: string;
  /** 1 = forward (slide right→left), -1 = back (slide left→right). Default 1. */
  direction?: 1 | -1;
}

const SLIDE_VARIANTS = {
  enter: (dir: number) => ({
    x: dir * 40,
    opacity: 0,
    scale: 0.98,
  }),
  center: {
    x: 0,
    opacity: 1,
    scale: 1,
    transition: { type: 'spring' as const, stiffness: 380, damping: 30, mass: 0.8 },
  },
  exit: (dir: number) => ({
    x: dir * -40,
    opacity: 0,
    scale: 0.98,
    transition: { type: 'tween' as const, duration: 0.18, ease: 'easeIn' as const },
  }),
};

/**
 * Split-panel layout for onboarding screens.
 * Left: white panel with animated content slot. Right: warm gradient.
 */
export function SplitPanelLayout({ children, onBack, stepKey, direction = 1 }: SplitPanelLayoutProps) {
  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: '#FAFAF7' }}>
      <div
        className="w-full max-w-4xl grid grid-cols-1 lg:grid-cols-2 overflow-hidden"
        style={{
          borderRadius: 24,
          boxShadow: '0 25px 60px rgba(15, 23, 42, 0.08)',
          minHeight: 560,
        }}
      >
        {/* Left panel — content */}
        <div className="relative flex flex-col items-center justify-center px-10 py-12 bg-white overflow-hidden">
          {/* Logo */}
          <div className="mb-10">
            <span className="text-2xl font-black tracking-tight" style={{ color: '#0f1c2e' }}>
              PersonaOn
            </span>
          </div>

          {/* Animated content slot */}
          <div className="w-full max-w-sm">
            <AnimatePresence mode="wait" custom={direction} initial={false}>
              <motion.div
                key={stepKey ?? 'default'}
                custom={direction}
                variants={SLIDE_VARIANTS}
                initial="enter"
                animate="center"
                exit="exit"
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Back link */}
          {onBack && (
            <motion.button
              onClick={onBack}
              className="absolute bottom-6 left-8 flex items-center gap-1.5 text-sm transition-colors"
              style={{ color: '#64748b' }}
              whileHover={{ x: -2 }}
              whileTap={{ scale: 0.96 }}
              transition={{ type: 'spring', stiffness: 500, damping: 28 }}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M13 8H3M3 8L7.5 3.5M3 8L7.5 12.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Back
            </motion.button>
          )}
        </div>

        {/* Right panel — warm gradient (decorative) */}
        <div
          className="hidden lg:flex flex-col items-center justify-center gap-8 px-10"
          aria-hidden="true"
          style={{
            background: 'linear-gradient(135deg, var(--primary-600) 0%, var(--primary-800) 40%, var(--primary-500) 70%, var(--primary-400) 100%)',
            borderRadius: '0 24px 24px 0',
          }}
        >
          {/* Floating orb accent */}
          <motion.div
            className="w-32 h-32 rounded-full opacity-20"
            style={{ background: 'white' }}
            animate={{ scale: [1, 1.08, 1], opacity: [0.15, 0.25, 0.15] }}
            transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.div
            className="w-16 h-16 rounded-full opacity-15"
            style={{ background: 'white', marginTop: -60 }}
            animate={{ scale: [1, 1.12, 1], opacity: [0.12, 0.22, 0.12] }}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut', delay: 1.2 }}
          />
        </div>
      </div>
    </div>
  );
}
