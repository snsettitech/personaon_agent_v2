const DEFAULT_BACKEND_URL = 'http://localhost:8000';

/**
 * Single source of truth for API base URL.
 * Works in both SSR (no window) and client.
 * Priority: env vars > localhost detection (client only) > production default.
 */
export const resolveApiBaseUrl = (): string => {
  const explicit =
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_BACKEND_API_URL;

  if (explicit) {
    return explicit.replace(/\/$/, '');
  }

  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'http://localhost:8000';
    }
  }

  return DEFAULT_BACKEND_URL;
};

/**
 * Alias for resolveApiBaseUrl - use for components that need a stable reference.
 * Call this at use-time (not module load) so SSR and client resolve correctly.
 */
export const getApiBaseUrl = resolveApiBaseUrl;

export const resolveApiHostLabel = () => {
  const base = resolveApiBaseUrl();
  try {
    return new URL(base).host;
  } catch {
    return base.replace(/^https?:\/\//, '');
  }
};

// ============================================================================
// ISSUE-001: Knowledge Ingestion Jobs API
// Typed API methods for ingestion job management
// ============================================================================

export interface IngestionJob {
  id: string;
  source_id: string;
  twin_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  job_type: string;
  priority: number;
  error_message?: string;
  metadata: Record<string, unknown>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

export interface ProcessQueueResult {
  processed: number;
  failed: number;
  remaining: number;
  message?: string;
}

/**
 * Knowledge Ingestion Jobs API
 * 
 * Manage document ingestion and indexing jobs for AI personas.
 * These endpoints use the clearer "ingestion" terminology (ISSUE-001).
 */
export const ingestionJobsApi = {
  /**
   * List all ingestion jobs for a twin
   */
  list: async (twinId: string): Promise<IngestionJob[]> => {
    const base = resolveApiBaseUrl();
    const res = await fetch(`${base}/ingestion-jobs?twin_id=${twinId}`, {
      headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
    });
    if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.status}`);
    return res.json();
  },

  /**
   * Get a single ingestion job by ID
   */
  get: async (jobId: string): Promise<IngestionJob> => {
    const base = resolveApiBaseUrl();
    const res = await fetch(`${base}/ingestion-jobs/${jobId}`, {
      headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
    });
    if (!res.ok) throw new Error(`Failed to fetch job: ${res.status}`);
    return res.json();
  },

  /**
   * Retry a failed ingestion job
   */
  retry: async (jobId: string): Promise<{ status: string; job_id: string }> => {
    const base = resolveApiBaseUrl();
    const res = await fetch(`${base}/ingestion-jobs/${jobId}/retry`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
    });
    if (!res.ok) throw new Error(`Failed to retry job: ${res.status}`);
    return res.json();
  },

  /**
   * Process the ingestion queue for a twin
   */
  processQueue: async (twinId: string): Promise<ProcessQueueResult> => {
    const base = resolveApiBaseUrl();
    const res = await fetch(`${base}/ingestion-jobs/process-queue?twin_id=${twinId}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
    });
    if (!res.ok) throw new Error(`Failed to process queue: ${res.status}`);
    return res.json();
  }
};

// Helper to get auth token - Supabase session is source of truth
async function getAuthToken(): Promise<string> {
  const token = await getChatAuthToken();
  return token ?? '';
}

/**
 * Get auth token from Supabase session. Use for chat and other authenticated API calls.
 * Returns null if not authenticated.
 */
export async function getChatAuthToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const { getSupabaseClient } = await import('@/lib/supabase/client');
    const { data: { session } } = await getSupabaseClient().auth.getSession();
    return session?.access_token || null;
  } catch {
    return null;
  }
}
