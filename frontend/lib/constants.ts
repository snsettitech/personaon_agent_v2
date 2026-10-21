/**
 * Centralized API Configuration
 *
 * This is the SINGLE SOURCE OF TRUTH for API configuration.
 * Use getApiBaseUrl() from @/lib/api for the backend URL.
 */

import { resolveApiBaseUrl } from '@/lib/api';

// Default values for Vercel deployments (when env vars not set in dashboard)
const DEFAULT_SUPABASE_URL = 'http://127.0.0.1:54321';
const DEFAULT_SUPABASE_ANON_KEY = '';

function getEnvVar(name: string, defaultValue?: string): string {
  const value = process.env[name] || defaultValue;
  if (!value) {
    console.warn(`[WARN] Missing environment variable: ${name}, using fallback`);
    return '';
  }
  return value.replace(/\/$/, ''); // Remove trailing slash
}

/**
 * The base URL for all API requests.
 * Delegates to resolveApiBaseUrl() for unified resolution (env, localhost, production).
 * @deprecated Prefer getApiBaseUrl() or resolveApiBaseUrl() from @/lib/api for new code.
 */
export const API_BASE_URL = resolveApiBaseUrl();

/**
 * Supabase configuration
 * Uses defaults for Vercel deployments when env vars not set in dashboard
 */
export const SUPABASE_URL = getEnvVar('NEXT_PUBLIC_SUPABASE_URL', DEFAULT_SUPABASE_URL) || DEFAULT_SUPABASE_URL;
export const SUPABASE_ANON_KEY = getEnvVar('NEXT_PUBLIC_SUPABASE_ANON_KEY', DEFAULT_SUPABASE_ANON_KEY) || DEFAULT_SUPABASE_ANON_KEY;

/**
 * Frontend URL (for redirects, sharing, etc.)
 */
export const FRONTEND_URL = process.env.NEXT_PUBLIC_FRONTEND_URL ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000');

/**
 * Public-facing site URL (for share links, metadata, SEO).
 * Unlike FRONTEND_URL (which may be localhost), this is always the production domain.
 */
export const PUBLIC_SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://www.personaon.com';

/**
 * CDN base URL (for widget script, static assets).
 */
export const CDN_BASE_URL = process.env.NEXT_PUBLIC_CDN_URL || 'https://cdn.personaon.com';

/**
 * API endpoint paths (centralized to prevent typos)
 */
export const API_ENDPOINTS = {
  // Health/Version
  HEALTH: '/health',
  VERSION: '/version',
  
  // Twins
  TWINS: '/twins',
  TWIN_DETAIL: (twinId: string) => `/twins/${twinId}`,
  TWIN_SOURCES: (twinId: string) => `/sources/${twinId}`,
  TWIN_SOURCES_GROUPED: (twinId: string) => `/sources/${twinId}/grouped`,
  TWIN_SOURCE_DETAIL: (twinId: string, sourceId: string) => `/sources/${twinId}/${sourceId}`,
  TWIN_SOURCE_CHUNKS: (twinId: string, sourceId: string) => `/sources/${twinId}/${sourceId}/chunks`,
  SOURCE_PATCH: (sourceId: string) => `/sources/${sourceId}`,
  TWIN_KNOWLEDGE_PROFILE: (twinId: string) => `/twins/${twinId}/knowledge-profile`,
  TWIN_GRAPH: (twinId: string) => `/twins/${twinId}/graph`,
  TWIN_GRAPH_STATS: (twinId: string) => `/twins/${twinId}/graph-stats`,
  TWIN_PROFILE_INSIGHTS: (twinId: string) => `/twins/${twinId}/profile-insights`,
  TWIN_LOGS: (twinId: string) => `/twins/${twinId}/logs`,
  TWIN_EXPORT: (twinId: string) => `/twins/${twinId}/export`,
  
  // Chat
  CHAT: (twinId: string) => `/chat/${twinId}`,
  CHAT_WIDGET: (twinId: string) => `/chat-widget/${twinId}`,
  CONVERSATIONS: (twinId: string) => `/conversations/${twinId}`,
  MESSAGES: (conversationId: string) => `/conversations/${conversationId}/messages`,
  
  // Ingestion
  INGEST_FILE: (twinId: string) => `/ingest/file/${twinId}`,
  INGEST_URL: (twinId: string) => `/ingest/url/${twinId}`,
  INGEST_YOUTUBE: (twinId: string) => `/ingest/youtube/${twinId}`,
  INGEST_PODCAST: (twinId: string) => `/ingest/podcast/${twinId}`,
  INGEST_X: (twinId: string) => `/ingest/x/${twinId}`,
  INGEST_EXTRACT_NODES: (sourceId: string) => `/ingest/extract-nodes/${sourceId}`,
  
  // Jobs
  JOBS: '/jobs',
  JOB_DETAIL: (jobId: string) => `/jobs/${jobId}`,
  JOB_LOGS: (jobId: string) => `/jobs/${jobId}/logs`,
  JOB_RETRY: (jobId: string) => `/jobs/${jobId}/retry`,
  
  // Ingestion
  INGESTION_JOBS: '/ingestion-jobs',
  INGESTION_JOB_DETAIL: (jobId: string) => `/ingestion-jobs/${jobId}`,
  INGESTION_JOBS_RETRY: (jobId: string) => `/ingestion-jobs/${jobId}/retry`,
  INGESTION_JOBS_PROCESS_QUEUE: '/ingestion-jobs/process-queue',
  
  // Metrics
  METRICS_DASHBOARD: (twinId: string) => `/metrics/dashboard/${twinId}`,
  METRICS_ACTIVITY: (twinId: string) => `/metrics/activity/${twinId}`,
  METRICS_CONVERSATIONS: (twinId: string) => `/metrics/conversations/${twinId}`,
  METRICS_TOP_QUESTIONS: (twinId: string) => `/metrics/top-questions/${twinId}`,
  
  // Auth
  AUTH_INVITATION: (token: string) => `/auth/invitation/${token}`,
  AUTH_ACCEPT_INVITATION: '/auth/accept-invitation',
  AUTH_CONNECTED_ACCOUNTS: '/auth/connected-accounts',
  
  // Products (Phase 7)
  PRODUCTS: (twinId: string) => `/twins/${twinId}/products`,
  PRODUCT_UPDATE: (productId: string) => `/products/${productId}`,
  PRODUCT_DELETE: (productId: string) => `/products/${productId}`,

  // Feedback
  FEEDBACK: '/feedback',
  FEEDBACK_PUBLIC: '/feedback/public',

  // Account / Profile
  ACCOUNT_DELETE: '/account/delete',
  PROFILE_RESET: '/profile/reset',
  PROFILE_PUBLISH: '/profile/publish',
  PROFILE_PUBLISH_GATE: '/profile/publish-gate',
  METRICS_QUOTA: (tenantId: string) => `/metrics/quota/${tenantId}`,

} as const;
