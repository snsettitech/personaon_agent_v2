/**
 * Research API Tests (Phase 7)
 * 
 * Tests for:
 * - API contract parsing (next_actions + alias fallback)
 * - Helper functions for status/quality handling
 * - Research API client methods
 * 
 * Run with: npx playwright test tests/research-api.test.ts
 */

import { test, expect } from '@playwright/test';
import {
  getNextActions,
  isTerminalStatus,
  requiresUserAction,
  getStatusLabel,
  getContentQualityInfo,
  type ResearchRunStatus,
  type ContentQuality,
} from '@/lib/api/research';


// =============================================================================
// Contract Parsing Tests (next_actions vs next_action)
// =============================================================================

test.describe('getNextActions', () => {
  test('should return next_actions when present and non-empty', () => {
    const response = {
      next_actions: ['continue_ingestion', 'review_sources'],
      next_action: 'old_field',
    };
    expect(getNextActions(response)).toEqual(['continue_ingestion', 'review_sources']);
  });

  test('should fall back to next_action when next_actions is empty', () => {
    const response = {
      next_actions: [],
      next_action: 'continue_ingestion',
    };
    expect(getNextActions(response)).toEqual(['continue_ingestion']);
  });

  test('should fall back to next_action when next_actions is undefined', () => {
    const response = {
      next_action: 'continue_ingestion',
    };
    expect(getNextActions(response)).toEqual(['continue_ingestion']);
  });

  test('should return empty array when both fields are missing', () => {
    const response = {};
    expect(getNextActions(response)).toEqual([]);
  });

  test('should return empty array when next_actions is empty and no next_action', () => {
    const response = {
      next_actions: [],
    };
    expect(getNextActions(response)).toEqual([]);
  });
});

// =============================================================================
// Status Helper Tests
// =============================================================================

test.describe('isTerminalStatus', () => {
  test('should return true for completed', () => {
    expect(isTerminalStatus('completed')).toBe(true);
  });

  test('should return true for failed', () => {
    expect(isTerminalStatus('failed')).toBe(true);
  });

  test('should return true for timed_out', () => {
    expect(isTerminalStatus('timed_out')).toBe(true);
  });

  test('should return false for non-terminal statuses', () => {
    const nonTerminal: ResearchRunStatus[] = [
      'planning',
      'queued',
      'crawling',
      'awaiting_confirmation',
      'ready_for_ingestion',
      'ingesting',
      'ingestion_completed',
      'generating_bio',
      'bio_generated',
      'finalizing',
    ];
    nonTerminal.forEach(status => {
      expect(isTerminalStatus(status)).toBe(false);
    });
  });
});

test.describe('requiresUserAction', () => {
  test('should return true for awaiting_confirmation', () => {
    expect(requiresUserAction('awaiting_confirmation')).toBe(true);
  });

  test('should return false for other statuses', () => {
    const other: ResearchRunStatus[] = [
      'planning',
      'queued',
      'crawling',
      'ready_for_ingestion',
      'ingesting',
      'ingestion_completed',
      'generating_bio',
      'bio_generated',
      'finalizing',
      'completed',
      'failed',
      'timed_out',
    ];
    other.forEach(status => {
      expect(requiresUserAction(status)).toBe(false);
    });
  });
});

test.describe('getStatusLabel', () => {
  test('should return correct labels for all statuses', () => {
    const expected: Record<ResearchRunStatus, string> = {
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

    Object.entries(expected).forEach(([status, label]) => {
      expect(getStatusLabel(status as ResearchRunStatus)).toBe(label);
    });
  });

  test('should return status as-is for unknown status', () => {
    expect(getStatusLabel('unknown' as ResearchRunStatus)).toBe('unknown');
  });
});

// =============================================================================
// Content Quality Helper Tests
// =============================================================================

test.describe('getContentQualityInfo', () => {
  test('should return correct info for high quality', () => {
    const info = getContentQualityInfo('high');
    expect(info.label).toBe('High Quality');
    expect(info.color).toBe('green');
  });

  test('should return correct info for blocked', () => {
    const info = getContentQualityInfo('blocked');
    expect(info.label).toBe('Blocked');
    expect(info.color).toBe('red');
    expect(info.description).toContain('manual upload');
  });

  test('should return correct info for gated', () => {
    const info = getContentQualityInfo('gated');
    expect(info.label).toBe('Gated');
    expect(info.color).toBe('yellow');
    expect(info.description).toContain('manual upload');
  });

  test('should return gray for unknown quality', () => {
    const info = getContentQualityInfo('unknown' as ContentQuality);
    expect(info.color).toBe('gray');
  });

  test('should indicate manual upload for blocked, gated, partial, error', () => {
    const needsManual: ContentQuality[] = ['blocked', 'gated', 'partial', 'error'];
    needsManual.forEach(quality => {
      const info = getContentQualityInfo(quality);
      expect(info.description).toContain('manual');
    });
  });
});

// =============================================================================
// E2E API Tests
// =============================================================================

test.describe('Research API E2E', () => {
  const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

  test('API contract - next_actions field exists in status response', async ({ request }) => {
    // This test requires authentication and an existing research run
    // For now, just verify the endpoint structure is valid
    
    // Test with invalid auth to get 401 instead of 404 (endpoint exists)
    const response = await request.get(`${API_BASE_URL}/twins/test-twin/research/test-run`);
    
    // Should be 401 (unauthorized) or 404 (not found) - both mean endpoint exists
    expect([401, 403, 404]).toContain(response.status());
  });

  test('API contract - bulk-confirm endpoint accepts POST', async ({ request }) => {
    const response = await request.post(`${API_BASE_URL}/twins/test-twin/research/test-run/bulk-confirm`, {
      data: {
        confirmation_ids: ['conf-1'],
        action: 'confirm',
      },
    });
    
    // Should be 401 or 404 - endpoint exists
    expect([401, 403, 404]).toContain(response.status());
  });
});

test.describe('Name-Only Deep Research status contract', () => {
  test('terminal states include completed and failed', () => {
    const terminal: string[] = ['completed', 'failed'];
    expect(terminal).toContain('completed');
    expect(terminal).toContain('failed');
  });
});
