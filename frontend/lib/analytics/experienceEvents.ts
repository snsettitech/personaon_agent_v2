/**
 * /experience demo funnel — pre-signup, no twin_id (session is ephemeral).
 * Kept out of events.ts to avoid growing that file past the 400-line module
 * limit; merged into the `analytics` namespace there so call sites are
 * unchanged (`analytics.experienceStepViewed(...)`, etc.).
 */

import posthog from 'posthog-js';

function capture(event: string, properties?: Record<string, unknown>): void {
  if (typeof window === 'undefined') return;
  try {
    posthog.capture(event, properties);
  } catch {
    // PostHog not initialized — no-op
  }
}

export type ExperienceStep = 'upload' | 'questions' | 'analyzing' | 'reveal' | 'limited';
export type SignupWallContext = 'reveal' | 'chat_locked' | 'limit_reached';

function experienceStepViewed(props: { step: ExperienceStep }): void {
  capture('experience_step_viewed', props);
}

function experienceResumeUploaded(props: { file_type: string; file_size: number }): void {
  capture('experience_resume_uploaded', props);
}

function experienceQuestionsSubmitted(props: { answered_count: number }): void {
  capture('experience_questions_submitted', props);
}

function experienceAnalyzeSucceeded(props: { duration_ms: number }): void {
  capture('experience_analyze_succeeded', props);
}

function experienceAnalyzeFailed(props: { error: string }): void {
  capture('experience_analyze_failed', props);
}

function experienceRevealViewed(): void {
  capture('experience_reveal_viewed');
}

function experienceChatMessageSent(props: { turn_number: number; message_length: number }): void {
  capture('experience_chat_message_sent', props);
}

function experienceChatLimitReached(): void {
  capture('experience_chat_limit_reached');
}

function experienceChatMessageFailed(props: { error: string }): void {
  capture('experience_chat_message_failed', props);
}

function experienceSignupWallClicked(props: { context: SignupWallContext }): void {
  capture('experience_signup_wall_clicked', props);
}

export const experienceAnalytics = {
  experienceStepViewed,
  experienceResumeUploaded,
  experienceQuestionsSubmitted,
  experienceAnalyzeSucceeded,
  experienceAnalyzeFailed,
  experienceRevealViewed,
  experienceChatMessageSent,
  experienceChatLimitReached,
  experienceChatMessageFailed,
  experienceSignupWallClicked,
} as const;
