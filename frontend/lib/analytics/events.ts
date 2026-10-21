/**
 * PersonaOn Analytics Event Taxonomy
 *
 * Typed event helpers for PostHog. Every user-facing action flows through here
 * so we get a single source of truth for event names and properties.
 *
 * Usage:
 *   import { analytics } from '@/lib/analytics/events';
 *   analytics.authLoginAttempted({ method: 'google' });
 */

import posthog from 'posthog-js';

import { experienceAnalytics } from './experienceEvents';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capture(event: string, properties?: Record<string, unknown> | object): void {
  if (typeof window === 'undefined') return;
  try {
    posthog.capture(event, properties as Record<string, unknown>);
  } catch {
    // PostHog not initialized — no-op
  }
}

// ---------------------------------------------------------------------------
// Auth events
// ---------------------------------------------------------------------------

interface AuthMethodProps {
  method: 'google' | 'linkedin' | 'email_password' | 'email_otp';
}

function authSignupStarted(props: AuthMethodProps): void {
  capture('auth_signup_started', props);
}

function authSignupCompleted(props: AuthMethodProps): void {
  capture('auth_signup_completed', props);
}

function authSignupFailed(props: AuthMethodProps & { error: string }): void {
  capture('auth_signup_failed', props);
}

function authLoginAttempted(props: AuthMethodProps): void {
  capture('auth_login_attempted', props);
}

function authLoginCompleted(props: AuthMethodProps): void {
  capture('auth_login_completed', props);
}

function authLoginFailed(props: AuthMethodProps & { error: string }): void {
  capture('auth_login_failed', props);
}

function authLogout(): void {
  capture('auth_logout');
}

function authPasswordResetRequested(): void {
  capture('auth_password_reset_requested');
}

function otpSent(props: { context: 'signup' | 'login' }): void {
  capture('otp_sent', props);
}

function otpVerified(props: { context: 'signup' | 'login' }): void {
  capture('otp_verified', props);
}

function otpFailed(props: { context: 'signup' | 'login'; error: string; attempts: number }): void {
  capture('otp_failed', props);
}

function otpResent(props: { context: 'signup' | 'login' }): void {
  capture('otp_resent', props);
}

// ---------------------------------------------------------------------------
// Onboarding events
// ---------------------------------------------------------------------------

interface OnboardingProps {
  twin_id?: string;
  input_source?: string;
}

function onboardingStarted(props?: OnboardingProps): void {
  capture('onboarding_started', props);
}

function onboardingStepViewed(props: { step: string; step_index: number }): void {
  capture('onboarding_step_viewed', props);
}

function onboardingExtractionStarted(props: OnboardingProps): void {
  capture('onboarding_extraction_started', props);
}

function onboardingExtractionComplete(props: OnboardingProps & { status: string; duration_seconds?: number }): void {
  capture('onboarding_extraction_complete', props);
}

function onboardingExtractionFailed(props: OnboardingProps & { error: string }): void {
  capture('onboarding_extraction_failed', props);
}

function onboardingProfileEdited(props: { twin_id: string; fields_edited: string[] }): void {
  capture('onboarding_profile_edited', props);
}

function onboardingPublished(props: { twin_id: string; handle: string }): void {
  capture('onboarding_published', props);
}

// ---------------------------------------------------------------------------
// Chat events
// ---------------------------------------------------------------------------

interface ChatMessageProps {
  twin_id: string;
  message_length: number;
  mode: 'owner' | 'public' | 'training' | 'assistant';
  conversation_id?: string;
  is_first_message?: boolean;
}

function chatMessageSent(props: ChatMessageProps): void {
  capture('chat_message_sent', props);
}

function chatMessageReceived(props: {
  twin_id: string;
  conversation_id?: string;
  answerability?: string;
  citations_count?: number;
  duration_ms?: number;
}): void {
  capture('chat_message_received', props);
}

function chatMessageError(props: { twin_id: string; error: string }): void {
  capture('chat_message_error', props);
}

function chatSuggestedQuestionClicked(props: { twin_id: string; question: string; position: number }): void {
  capture('chat_suggested_question_clicked', props);
}

function chatHistoryCleared(props: { twin_id: string }): void {
  capture('chat_history_cleared', props);
}

// ---------------------------------------------------------------------------
// Dashboard events
// ---------------------------------------------------------------------------

function dashboardLoaded(props: { twin_count: number; has_active_twin: boolean }): void {
  capture('dashboard_loaded', props);
}

function dashboardActionClicked(props: { action: string; twin_id?: string }): void {
  capture('dashboard_action_clicked', props);
}

export type DashboardWalkthroughSurface = 'desktop_sidebar' | 'mobile_tabbar';

interface DashboardWalkthroughProps {
  surface: DashboardWalkthroughSurface;
  twin_id?: string;
}

interface DashboardWalkthroughStepProps extends DashboardWalkthroughProps {
  step_id: string;
  step_index: number;
  step_count: number;
}

function dashboardWalkthroughStarted(props: DashboardWalkthroughProps & { step_count: number }): void {
  capture('dashboard_walkthrough_started', props);
}

function dashboardWalkthroughStepViewed(props: DashboardWalkthroughStepProps): void {
  capture('dashboard_walkthrough_step_viewed', props);
}

function dashboardWalkthroughCompleted(props: DashboardWalkthroughProps & { step_count: number }): void {
  capture('dashboard_walkthrough_completed', props);
}

function dashboardWalkthroughSkipped(props: DashboardWalkthroughStepProps): void {
  capture('dashboard_walkthrough_skipped', props);
}

// ---------------------------------------------------------------------------
// Knowledge / Ingestion events
// ---------------------------------------------------------------------------

function knowledgeSourceUploaded(props: { source_type: string; file_size?: number; twin_id: string }): void {
  capture('knowledge_source_uploaded', props);
}

function knowledgeSourceDeleted(props: { source_id: string; twin_id: string }): void {
  capture('knowledge_source_deleted', props);
}

function knowledgeViewChanged(props: { view: 'list' | 'graph' }): void {
  capture('knowledge_view_changed', props);
}

// ---------------------------------------------------------------------------
// Marketplace events
// ---------------------------------------------------------------------------

function marketplaceSearched(props: { query: string; result_count: number }): void {
  capture('marketplace_searched', props);
}

function marketplaceFilterApplied(props: { filter_type: string; filter_value: string }): void {
  capture('marketplace_filter_applied', props);
}

function marketplacePersonaClicked(props: { persona_id: string; position: number }): void {
  capture('marketplace_persona_clicked', props);
}

function marketplaceChatStarted(props: { persona_id: string; handle: string }): void {
  capture('marketplace_chat_started', props);
}

// ---------------------------------------------------------------------------
// Settings events
// ---------------------------------------------------------------------------

function settingsTabChanged(props: { tab: string }): void {
  capture('settings_tab_changed', props);
}

function settingsProfileUpdated(props: { fields_changed: string[] }): void {
  capture('settings_profile_updated', props);
}

function settingsTwinDeleted(props: { twin_id: string }): void {
  capture('settings_twin_deleted', props);
}

function notificationPreferencesUpdated(props: {
  category: 'product_education' | 'daily_activity' | 'weekly_report' | 'hot_lead_alert' | 'meeting';
  enabled: boolean;
  source: 'settings' | 'unsubscribe';
}): void {
  capture('notification_preferences_updated', props);
}

// ---------------------------------------------------------------------------
// Help / education events
// ---------------------------------------------------------------------------

function helpArticleViewed(props: { slug: string; source?: string }): void {
  capture('help_article_viewed', props);
}

function helpCtaClicked(props: { slug: string; cta: string; target: string }): void {
  capture('help_cta_clicked', props);
}

// ---------------------------------------------------------------------------
// Share / Public persona events
// ---------------------------------------------------------------------------

function sharePageViewed(props: { twin_id: string; handle?: string }): void {
  capture('share_page_viewed', props);
}

function shareLinkCopied(props: { twin_id: string; handle?: string }): void {
  capture('share_link_copied', props);
}

// ---------------------------------------------------------------------------
// Booking events — calendar booking funnel telemetry (Bug 6)
// Helps surface "all dates returning zero slots" or "submit-time conflicts
// spiking" in PostHog dashboards instead of waiting for a human to report.
// ---------------------------------------------------------------------------

function bookingButtonClicked(props: { twin_id: string; surface: 'persistent_chip' | 'trigger' }): void {
  capture('booking_button_clicked', props);
}

function bookingDatesLoaded(props: { twin_id: string }): void {
  capture('booking_dates_loaded', props);
}

function bookingSlotsLoaded(props: { twin_id: string; date: string; count: number }): void {
  capture('booking_slots_loaded', props);
}

function bookingSlotsLoadFailed(props: { twin_id: string; date: string; reason: 'not_connected' | 'server_error' | 'unknown' }): void {
  capture('booking_slots_load_failed', props);
}

function bookingSlotSelected(props: { twin_id: string; date: string }): void {
  capture('booking_slot_selected', props);
}

function bookingSubmitted(props: { twin_id: string; date: string }): void {
  capture('booking_submitted', props);
}

function bookingSubmitFailed(props: { twin_id: string; reason: 'slot_taken' | 'validation' | 'server' }): void {
  capture('booking_submit_failed', props);
}

// ---------------------------------------------------------------------------
// Share Studio events
// ---------------------------------------------------------------------------

function shareStudioOpened(surface: 'email-signature' | 'linkedin' | 'social' | 'website' | 'qr' | 'settings'): void {
  capture('share_studio_opened', { surface });
}

function shareActionCopied(surface: string, artifact: 'link' | 'snippet' | 'post' | 'signature' | 'qr'): void {
  capture('share_action_copied', { surface, artifact });
}

function shareActionClicked(surface: string, cta: string): void {
  capture('share_action_clicked', { surface, cta });
}

function qrDownloaded(format: 'png' | 'svg'): void {
  capture('qr_downloaded', { format });
}

// ---------------------------------------------------------------------------
// Viral loop events
// ---------------------------------------------------------------------------

function personaPageCtaClicked(props: { handle: string; surface: string }): void {
  capture('persona_page_cta_clicked', props);
}

// ---------------------------------------------------------------------------
// Deep research events
// ---------------------------------------------------------------------------

function researchStarted(props: { twin_id: string; query?: string }): void {
  capture('research_started', props);
}

function researchCompleted(props: { twin_id: string; duration_seconds: number; status: string }): void {
  capture('research_completed', props);
}

// ---------------------------------------------------------------------------
// Landing page events
// ---------------------------------------------------------------------------

function landingCtaClicked(props: { cta_type: string; position: string }): void {
  capture('landing_cta_clicked', props);
}

function landingDemoChatStarted(): void {
  capture('landing_demo_chat_started');
}

function landingWaitlistSubmitted(props: { success: boolean }): void {
  capture('landing_waitlist_submitted', props);
}

function landingFaqExpanded(props: { question: string; index: number }): void {
  capture('landing_faq_expanded', props);
}

// ---------------------------------------------------------------------------
// User identification
// ---------------------------------------------------------------------------

function identifyUser(userId: string, properties?: Record<string, unknown>): void {
  if (typeof window === 'undefined') return;
  try {
    posthog.identify(userId, properties);
  } catch {
    // no-op
  }
}

function resetUser(): void {
  if (typeof window === 'undefined') return;
  try {
    posthog.reset();
  } catch {
    // no-op
  }
}

function setUserProperties(properties: Record<string, unknown>): void {
  if (typeof window === 'undefined') return;
  try {
    posthog.people.set(properties);
  } catch {
    // no-op
  }
}

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

function isFeatureEnabled(flag: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return posthog.isFeatureEnabled(flag) ?? false;
  } catch {
    return false;
  }
}

function getFeatureFlag(flag: string): string | boolean | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return posthog.getFeatureFlag(flag);
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export const analytics = {
  capture,

  // Experience demo funnel
  ...experienceAnalytics,

  // Auth
  authSignupStarted,
  authSignupCompleted,
  authSignupFailed,
  authLoginAttempted,
  authLoginCompleted,
  authLoginFailed,
  authLogout,
  authPasswordResetRequested,
  otpSent,
  otpVerified,
  otpFailed,
  otpResent,

  // Onboarding
  onboardingStarted,
  onboardingStepViewed,
  onboardingExtractionStarted,
  onboardingExtractionComplete,
  onboardingExtractionFailed,
  onboardingProfileEdited,
  onboardingPublished,

  // Chat
  chatMessageSent,
  chatMessageReceived,
  chatMessageError,
  chatSuggestedQuestionClicked,
  chatHistoryCleared,

  // Dashboard
  dashboardLoaded,
  dashboardActionClicked,
  dashboardWalkthroughStarted,
  dashboardWalkthroughStepViewed,
  dashboardWalkthroughCompleted,
  dashboardWalkthroughSkipped,

  // Knowledge
  knowledgeSourceUploaded,
  knowledgeSourceDeleted,
  knowledgeViewChanged,

  // Marketplace
  marketplaceSearched,
  marketplaceFilterApplied,
  marketplacePersonaClicked,
  marketplaceChatStarted,

  // Settings
  settingsTabChanged,
  settingsProfileUpdated,
  settingsTwinDeleted,
  notificationPreferencesUpdated,

  // Help / education
  helpArticleViewed,
  helpCtaClicked,

  // Share
  sharePageViewed,
  shareLinkCopied,

  // Booking
  bookingButtonClicked,
  bookingDatesLoaded,
  bookingSlotsLoaded,
  bookingSlotsLoadFailed,
  bookingSlotSelected,
  bookingSubmitted,
  bookingSubmitFailed,

  // Share Studio
  shareStudioOpened,
  shareActionCopied,
  shareActionClicked,
  qrDownloaded,

  // Viral loop
  personaPageCtaClicked,

  // Research
  researchStarted,
  researchCompleted,

  // Landing
  landingCtaClicked,
  landingDemoChatStarted,
  landingWaitlistSubmitted,
  landingFaqExpanded,

  // Identity
  identifyUser,
  resetUser,
  setUserProperties,

  // Feature flags
  isFeatureEnabled,
  getFeatureFlag,
} as const;
