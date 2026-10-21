/**
 * Research API Client (Phase 7)
 * 
 * Centralized API client for Deep Research endpoints.
 * All changes are additive and backward compatible.
 */

import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';

// =============================================================================
// Types (aligned with backend contracts)
// =============================================================================

export type ResearchRunStatus = 
  | 'planning'
  | 'queued'
  | 'crawling'
  | 'awaiting_confirmation'
  | 'ready_for_ingestion'
  | 'ingesting'
  | 'ingestion_completed'
  | 'generating_bio'
  | 'bio_generated'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'timed_out';

export type ConfirmationStatus = 
  | 'pending'
  | 'auto_confirmed'
  | 'auto_rejected'
  | 'manual_review'
  | 'confirmed'
  | 'rejected';

export type ContentQuality = 
  | 'high'
  | 'medium'
  | 'low'
  | 'blocked'
  | 'gated'
  | 'partial'
  | 'error';

export interface CreateResearchRunRequest {
  claimed_identity: {
    full_name?: string;
    location?: string;
    submitted_links?: string[];
    [key: string]: unknown;
  };
  /** URLs to crawl; optional when full_name provided (Firecrawl search used) */
  seed_urls?: string[];
  onboarding_session_id?: string;
  metadata?: Record<string, unknown>;
}

export interface CreateResearchRunResponse {
  research_run_id: string;
  twin_id: string;
  status: ResearchRunStatus;
  created_at: string;
}

export interface ResearchRunStatusResponse {
  research_run_id: string;
  twin_id: string;
  status: ResearchRunStatus;
  crawl_id?: string;
  checkpoint_data: {
    crawl_progress?: {
      crawl_id?: string;
      crawl_status?: string;
      seed_urls_total?: number;
      pages_found?: number;
      pages_ingested?: number;
      pages_failed?: number;
      pages_unchanged?: number;
      started_at?: string;
      updated_at?: string;
    };
    ingestion?: {
      sources_total?: number;
      sources_ingested?: number;
      pages_eligible?: number;
      pages_ingested?: number;
      chunks_created?: number;
      words_processed?: number;
      questions_answerable_estimate?: number;
      errors?: string[];
    };
    bio_generation?: {
      bio_types_generated?: string[];
      sources_used?: number;
      generation_time_ms?: number;
    };
    mind_score?: {
      score?: number;
      previous_score?: number;
      delta?: number;
      words_processed?: number;
      questions_answerable_estimate?: number;
    };
    readiness?: {
      is_ready?: boolean;
      readiness_score?: number;
      missing_factors?: string[];
    };
    last_transition_at?: string;
    [key: string]: unknown;
  };
  confirmation_summary?: {
    research_run_id: string;
    twin_id: string;
    total: number;
    pending: number;
    auto_confirmed: number;
    auto_rejected: number;
    manual_review: number;
    confirmed: number;
    rejected: number;
    all_resolved: boolean;
    resolution_percent: number;
  };
  /**
   * Canonical plural field - primary field to use
   */
  next_actions: string[];
  /**
   * Backward compatibility alias - falls back to next_actions[0]
   * @deprecated Use next_actions instead
   */
  next_action?: string;
  warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface PendingConfirmationItem {
  confirmation_id: string;
  crawl_page_id: string;
  url: string;
  canonical_url: string;
  title: string;
  snippet: string;
  content_quality: ContentQuality;
  identity_match_tier?: string;
  match_details?: {
    name_match?: boolean;
    email_match?: boolean;
    org_match?: boolean;
    [key: string]: unknown;
  };
  submitted_root_url?: string;
  status: ConfirmationStatus;
  created_at: string;
}

export interface PendingConfirmationsResponse {
  items: PendingConfirmationItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ResolveConfirmationRequest {
  action: 'confirm' | 'reject';
  feedback?: string;
}

export interface ResolveConfirmationResponse {
  confirmation_id: string;
  research_run_id: string;
  previous_status: string;
  new_status: string;
  action: string;
  resolved_at: string;
  user_override: boolean;
  run_status?: string;
  run_transition?: string;
}

export interface BulkResolveRequest {
  confirmation_ids: string[];
  action: 'confirm' | 'reject';
  feedback?: string;
}

export interface BulkResolveResponse {
  research_run_id: string;
  action: string;
  requested: number;
  succeeded: number;
  failed: number;
  errors: string[];
  run_status?: string;
  run_transition?: string;
}

export interface ContinueIngestionResponse {
  research_run_id: string;
  twin_id: string;
  previous_status: string;
  new_status: string;
  ingestion_summary?: {
    sources_total?: number;
    sources_ingested?: number;
    chunks_created?: number;
    errors?: string[];
  };
  transition_reason?: string;
}

export interface ContinueBioResponse {
  research_run_id: string;
  twin_id: string;
  previous_status: string;
  new_status: string;
  bio_generation_summary?: {
    bio_types_generated?: string[];
    sources_used?: number;
    generation_time_ms?: number;
  };
  transition_reason?: string;
}

export interface ContinueFinalizeResponse {
  research_run_id: string;
  twin_id: string;
  previous_status: string;
  new_status: string;
  mind_score_summary?: {
    score?: number;
    previous_score?: number;
    delta?: number;
  };
  readiness_summary?: {
    is_ready?: boolean;
    readiness_score?: number;
    missing_factors?: string[];
  };
  transition_reason?: string;
}

export interface ResearchSource {
  confirmation_id: string;
  crawl_page_id: string;
  url: string;
  title: string;
  canonical_url: string;
  identity_match_tier?: string;
  content_quality: ContentQuality;
  created_at: string;
}

export interface ResearchSummaryResponse {
  twin_id: string;
  research_run_id?: string;
  status?: ResearchRunStatus;
  sources: {
    confirmed: ResearchSource[];
    auto_confirmed: ResearchSource[];
    pending: ResearchSource[];
    manual_review: ResearchSource[];
    rejected: ResearchSource[];
  };
  bio_generation?: {
    bio_types_generated?: string[];
    sources_used?: number;
    generation_time_ms?: number;
  };
  mind_score?: {
    score?: number;
    previous_score?: number;
    delta?: number;
  };
  readiness?: {
    is_ready?: boolean;
    readiness_score?: number;
    missing_factors?: string[];
  };
  /**
   * Canonical plural field - primary field to use
   */
  next_actions: string[];
  /**
   * Backward compatibility alias
   * @deprecated Use next_actions instead
   */
  next_action?: string;
  checkpoint_updated_at?: string;
}

// =============================================================================
// Safe Parsing Helpers (for contract hardening)
// =============================================================================

/**
 * Safely extract next_actions with fallback to next_action alias.
 * This ensures backward compatibility with older backend responses.
 */
export function getNextActions(response: { next_actions?: string[]; next_action?: string }): string[] {
  // Primary: use next_actions if present and non-empty
  if (Array.isArray(response.next_actions) && response.next_actions.length > 0) {
    return response.next_actions;
  }
  
  // Fallback: use next_action alias
  if (response.next_action) {
    return [response.next_action];
  }
  
  return [];
}

/**
 * Check if a status is a terminal state (polling should stop)
 */
export function isTerminalStatus(status: ResearchRunStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'timed_out';
}

/**
 * Check if a status requires user action
 */
export function requiresUserAction(status: ResearchRunStatus): boolean {
  return status === 'awaiting_confirmation';
}

/**
 * Get human-readable status label
 */
export function getStatusLabel(status: ResearchRunStatus): string {
  const labels: Record<ResearchRunStatus, string> = {
    planning: 'Planning',
    queued: 'Queued',
    crawling: 'Crawling',
    awaiting_confirmation: 'Awaiting Confirmation',
    ready_for_ingestion: 'Ready for Ingestion',
    ingesting: 'Ingesting',
    ingestion_completed: 'Ingestion Completed',
    generating_bio: 'Generating Bio',
    bio_generated: 'Bio Generated',
    finalizing: 'Finalizing',
    completed: 'Completed',
    failed: 'Failed',
    timed_out: 'Timed Out',
  };
  return labels[status] || status;
}

/**
 * Get content quality display info
 */
export function getContentQualityInfo(quality: ContentQuality): {
  label: string;
  color: 'green' | 'yellow' | 'red' | 'gray';
  description: string;
} {
  const info: Record<ContentQuality, { label: string; color: 'green' | 'yellow' | 'red' | 'gray'; description: string }> = {
    high: { label: 'High Quality', color: 'green', description: 'Content is clear and relevant' },
    medium: { label: 'Medium Quality', color: 'yellow', description: 'Content may need review' },
    low: { label: 'Low Quality', color: 'red', description: 'Content has issues' },
    blocked: { label: 'Blocked', color: 'red', description: 'Content is blocked - manual upload needed' },
    gated: { label: 'Gated', color: 'yellow', description: 'Content requires authentication - manual upload needed' },
    partial: { label: 'Partial', color: 'yellow', description: 'Partial content retrieved - manual upload recommended' },
    error: { label: 'Error', color: 'red', description: 'Error retrieving content - retry or manual upload' },
  };
  return info[quality] || { label: quality, color: 'gray', description: '' };
}

// =============================================================================
// API Client
// =============================================================================

const BASE_URL = resolveApiBaseUrl();

export const researchApi = {
  /**
   * Create a new research run
   * POST /twins/{twin_id}/research
   */
  async createResearchRun(
    twinId: string,
    request: CreateResearchRunRequest
  ): Promise<CreateResearchRunResponse> {
    const response = await authFetchStandalone(`${BASE_URL}/twins/${twinId}/research`, {
      method: 'POST',
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to create research run: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Get research run status
   * GET /twins/{twin_id}/research/{research_run_id}
   */
  async getResearchRunStatus(
    twinId: string,
    researchRunId: string
  ): Promise<ResearchRunStatusResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}`
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to get research status: ${response.status}`);
    }

    const data = await response.json();
    
    // Normalize next_actions for contract hardening
    return {
      ...data,
      next_actions: getNextActions(data),
    };
  },

  /**
   * Get pending confirmations
   * GET /twins/{twin_id}/research/{research_run_id}/pending-confirmations
   */
  async getPendingConfirmations(
    twinId: string,
    researchRunId: string,
    options?: { limit?: number; offset?: number }
  ): Promise<PendingConfirmationsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const queryString = params.toString();
    const url = `${BASE_URL}/twins/${twinId}/research/${researchRunId}/pending-confirmations${queryString ? `?${queryString}` : ''}`;

    const response = await authFetchStandalone(url);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to get pending confirmations: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Resolve a single confirmation
   * POST /twins/{twin_id}/research/{research_run_id}/confirmations/{confirmation_id}
   */
  async resolveConfirmation(
    twinId: string,
    researchRunId: string,
    confirmationId: string,
    request: ResolveConfirmationRequest
  ): Promise<ResolveConfirmationResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}/confirmations/${confirmationId}`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to resolve confirmation: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Bulk resolve confirmations
   * POST /twins/{twin_id}/research/{research_run_id}/bulk-confirm
   */
  async bulkResolveConfirmations(
    twinId: string,
    researchRunId: string,
    request: BulkResolveRequest
  ): Promise<BulkResolveResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}/bulk-confirm`,
      {
        method: 'POST',
        body: JSON.stringify(request),
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to bulk resolve confirmations: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Continue to ingestion phase
   * POST /twins/{twin_id}/research/{research_run_id}/continue-ingestion
   */
  async continueIngestion(
    twinId: string,
    researchRunId: string
  ): Promise<ContinueIngestionResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}/continue-ingestion`,
      {
        method: 'POST',
      }
    );

    if (!response.ok) {
      // Handle idempotent case: 409 Conflict means already completed
      if (response.status === 409) {
        const data = await response.json().catch(() => null);
        if (data?.new_status === 'ingestion_completed') {
          return data as ContinueIngestionResponse;
        }
      }
      
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to continue ingestion: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Continue to bio generation phase
   * POST /twins/{twin_id}/research/{research_run_id}/continue-bio
   */
  async continueBio(
    twinId: string,
    researchRunId: string
  ): Promise<ContinueBioResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}/continue-bio`,
      {
        method: 'POST',
      }
    );

    if (!response.ok) {
      // Handle idempotent case: 409 Conflict means already completed
      if (response.status === 409) {
        const data = await response.json().catch(() => null);
        if (data?.new_status === 'bio_generated') {
          return data as ContinueBioResponse;
        }
      }
      
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to continue bio generation: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Continue to finalization phase
   * POST /twins/{twin_id}/research/{research_run_id}/continue-finalize
   */
  async continueFinalize(
    twinId: string,
    researchRunId: string
  ): Promise<ContinueFinalizeResponse> {
    const response = await authFetchStandalone(
      `${BASE_URL}/twins/${twinId}/research/${researchRunId}/continue-finalize`,
      {
        method: 'POST',
      }
    );

    if (!response.ok) {
      // Handle idempotent case: 409 Conflict means already completed
      if (response.status === 409) {
        const data = await response.json().catch(() => null);
        if (data?.new_status === 'completed') {
          return data as ContinueFinalizeResponse;
        }
      }
      
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to continue finalization: ${response.status}`);
    }

    return response.json();
  },

  /**
   * Get research summary
   * GET /twins/{twin_id}/research-summary
   */
  async getResearchSummary(twinId: string): Promise<ResearchSummaryResponse> {
    const response = await authFetchStandalone(`${BASE_URL}/twins/${twinId}/research-summary`);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(error.message || `Failed to get research summary: ${response.status}`);
    }

    const data = await response.json();
    
    // Normalize next_actions for contract hardening
    return {
      ...data,
      next_actions: getNextActions(data),
    };
  },
};

export default researchApi;
