/**
 * useJobPoller - Robust job polling hook with visibility handling
 * 
 * Based on best practices from:
 * - https://medium.com/@sfcofc/implementing-polling-in-react
 * - https://github.com/epam/deps-fe-usePolling
 * 
 * Features:
 * - Page visibility awareness (pauses when tab hidden)
 * - Exponential backoff on errors
 * - Cleanup on unmount
 * - AbortController for request cancellation
 */

'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';

export type JobStatus = 'queued' | 'processing' | 'complete' | 'failed' | 'needs_attention';

export interface Job {
  id: string;
  source_id: string;
  twin_id: string;
  status: JobStatus;
  job_type: string;
  priority: number;
  error_message?: string;
  metadata: {
    provider?: string;
    url?: string;
    progress?: number;
    chunks_created?: number;
    [key: string]: any;
  };
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
}

interface UseJobPollerOptions {
  jobId: string | null;
  token: string | null;
  /** Polling interval in ms when job is queued */
  queuedInterval?: number;
  /** Polling interval in ms when job is processing */
  processingInterval?: number;
  /** Max time to poll in ms before giving up (default: 10 minutes) */
  timeout?: number;
  /** Enable debug logging */
  debug?: boolean;
}

interface UseJobPollerReturn {
  job: Job | null;
  isPolling: boolean;
  error: string | null;
  /** Whether the job reached a terminal state (complete/failed) */
  isComplete: boolean;
  /** Whether the job completed successfully */
  isSuccessful: boolean;
  /** Start polling for a job */
  startPolling: (jobId: string) => void;
  /** Stop polling */
  stopPolling: () => void;
  /** Retry a failed job */
  retryJob: () => Promise<boolean>;
}

// Poll intervals based on status (ms)
const DEFAULT_QUEUED_INTERVAL = 3000;    // 3s when queued
const DEFAULT_PROCESSING_INTERVAL = 2000; // 2s when processing
const DEFAULT_TIMEOUT = 10 * 60 * 1000;   // 10 minutes
const MAX_ERROR_BACKOFF = 30000;          // Max 30s between retries on error

export function useJobPoller({
  jobId: initialJobId,
  token,
  queuedInterval = DEFAULT_QUEUED_INTERVAL,
  processingInterval = DEFAULT_PROCESSING_INTERVAL,
  timeout = DEFAULT_TIMEOUT,
  debug = false,
}: UseJobPollerOptions): UseJobPollerReturn {
  const [job, setJob] = useState<Job | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const jobIdRef = useRef<string | null>(initialJobId);
  const abortControllerRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const errorCountRef = useRef(0);
  const startTimeRef = useRef<number>(0);
  const isVisibleRef = useRef(true);
  const endpointKindRef = useRef<'auto' | 'ingestion' | 'training' | 'jobs'>('auto');
  
  const log = useCallback((...args: any[]) => {
    if (debug) console.log('[useJobPoller]', ...args);
  }, [debug]);

  // Track page visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      isVisibleRef.current = !document.hidden;
      log('Visibility changed:', isVisibleRef.current ? 'visible' : 'hidden');
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [log]);

  // Cleanup function
  const cleanup = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsPolling(false);
    log('Cleanup complete');
  }, [log]);

  const jobDetailPath = useCallback((jobId: string, kind: 'ingestion' | 'training' | 'jobs'): string => {
    if (kind === 'ingestion') return API_ENDPOINTS.INGESTION_JOB_DETAIL(jobId);
    if (kind === 'training') return `/training-jobs/${jobId}`;
    return API_ENDPOINTS.JOB_DETAIL(jobId);
  }, []);

  const jobRetryPath = useCallback((jobId: string, kind: 'ingestion' | 'training' | 'jobs'): string => {
    if (kind === 'ingestion') return API_ENDPOINTS.INGESTION_JOBS_RETRY(jobId);
    if (kind === 'training') return `/training-jobs/${jobId}/retry`;
    return API_ENDPOINTS.JOB_RETRY(jobId);
  }, []);

  // Main polling function
  const poll = useCallback(async () => {
    const currentJobId = jobIdRef.current;
    if (!currentJobId || !token) {
      log('No jobId or token, stopping');
      cleanup();
      return;
    }

    // Don't poll if page is hidden
    if (!isVisibleRef.current) {
      log('Page hidden, scheduling next poll');
      timeoutRef.current = setTimeout(poll, 1000);
      return;
    }

    // Check timeout
    if (Date.now() - startTimeRef.current > timeout) {
      log('Polling timeout reached');
      setError('Job processing timed out. Please check status manually.');
      cleanup();
      return;
    }

    // Cancel any in-flight request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      log('Polling job:', currentJobId);
      const requestOptions: RequestInit = {
        headers: { Authorization: `Bearer ${token}` },
        signal: abortControllerRef.current.signal,
      };

      let response: Response | null = null;
      let resolvedKind: 'ingestion' | 'training' | 'jobs' | null = null;

      if (endpointKindRef.current === 'auto') {
        const candidates: Array<'ingestion' | 'training' | 'jobs'> = ['ingestion', 'training', 'jobs'];
        for (const kind of candidates) {
          const candidateResponse = await fetch(
            `${API_BASE_URL}${jobDetailPath(currentJobId, kind)}`,
            requestOptions
          );
          if (candidateResponse.status === 404) continue;
          response = candidateResponse;
          resolvedKind = kind;
          break;
        }
      } else {
        const kind = endpointKindRef.current;
        const candidateResponse = await fetch(
          `${API_BASE_URL}${jobDetailPath(currentJobId, kind)}`,
          requestOptions
        );
        // If the remembered endpoint is no longer valid, re-run auto detection.
        if (candidateResponse.status === 404) {
          endpointKindRef.current = 'auto';
          const candidates: Array<'ingestion' | 'training' | 'jobs'> = ['ingestion', 'training', 'jobs'];
          for (const candidate of candidates) {
            const retryResponse = await fetch(
              `${API_BASE_URL}${jobDetailPath(currentJobId, candidate)}`,
              requestOptions
            );
            if (retryResponse.status === 404) continue;
            response = retryResponse;
            resolvedKind = candidate;
            break;
          }
        } else {
          response = candidateResponse;
          resolvedKind = kind;
        }
      }

      if (!response) {
        throw new Error('HTTP 404: Job not found in ingestion-jobs, training-jobs, or jobs');
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      if (resolvedKind) {
        endpointKindRef.current = resolvedKind;
      }

      const data: Job = await response.json();
      log('Job status:', data.status);
      
      setJob(data);
      errorCountRef.current = 0; // Reset error count on success

      // Check if terminal state
      if (data.status === 'complete' || data.status === 'failed') {
        log('Job reached terminal state:', data.status);
        cleanup();
        return;
      }

      // Schedule next poll based on status
      const nextInterval = data.status === 'processing' 
        ? processingInterval 
        : queuedInterval;
      
      log('Scheduling next poll in', nextInterval, 'ms');
      timeoutRef.current = setTimeout(poll, nextInterval);
      
    } catch (err: any) {
      if (err.name === 'AbortError') {
        log('Request aborted');
        return;
      }

      errorCountRef.current++;
      const errorMsg = err instanceof Error ? err.message : 'Failed to fetch job status';
      log('Poll error:', errorMsg, '(count:', errorCountRef.current + ')');
      setError(errorMsg);

      // Exponential backoff on errors
      const backoffMs = Math.min(
        1000 * Math.pow(2, errorCountRef.current - 1),
        MAX_ERROR_BACKOFF
      );
      
      log('Retrying after error backoff:', backoffMs, 'ms');
      timeoutRef.current = setTimeout(poll, backoffMs);
    }
  }, [token, queuedInterval, processingInterval, timeout, cleanup, log]);

  // Start polling
  const startPolling = useCallback((newJobId: string) => {
    log('Starting polling for job:', newJobId);
    jobIdRef.current = newJobId;
    endpointKindRef.current = 'auto';
    startTimeRef.current = Date.now();
    errorCountRef.current = 0;
    setError(null);
    setIsPolling(true);
    poll();
  }, [poll, log]);

  // Stop polling
  const stopPolling = useCallback(() => {
    log('Stopping polling');
    cleanup();
    jobIdRef.current = null;
  }, [cleanup, log]);

  // Retry a failed job
  const retryJob = useCallback(async (): Promise<boolean> => {
    const currentJobId = jobIdRef.current;
    if (!currentJobId || !token) return false;

    try {
      log('Retrying job:', currentJobId);
      const requestOptions: RequestInit = {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      };

      let response: Response | null = null;

      if (endpointKindRef.current === 'auto') {
        const candidates: Array<'ingestion' | 'training' | 'jobs'> = ['ingestion', 'training', 'jobs'];
        for (const kind of candidates) {
          const candidateResponse = await fetch(
            `${API_BASE_URL}${jobRetryPath(currentJobId, kind)}`,
            requestOptions
          );
          if (candidateResponse.status === 404) continue;
          response = candidateResponse;
          endpointKindRef.current = kind;
          break;
        }
      } else {
        response = await fetch(
          `${API_BASE_URL}${jobRetryPath(currentJobId, endpointKindRef.current)}`,
          requestOptions
        );
      }

      if (response?.ok) {
        // Restart polling
        startPolling(currentJobId);
        return true;
      }
      return false;
    } catch (err) {
      log('Retry failed:', err);
      return false;
    }
  }, [token, startPolling, log]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  // Start polling if initialJobId provided
  useEffect(() => {
    if (initialJobId && !jobIdRef.current) {
      startPolling(initialJobId);
    }
  }, [initialJobId, startPolling]);

  const isComplete = job?.status === 'complete' || job?.status === 'failed';
  const isSuccessful = job?.status === 'complete';

  return {
    job,
    isPolling,
    error,
    isComplete,
    isSuccessful,
    startPolling,
    stopPolling,
    retryJob,
  };
}

export default useJobPoller;
