'use client';

import { useCallback } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { API_BASE_URL } from '@/lib/constants';
import { useRequestLogger, generateRequestId } from './useRequestLogger';

/**
 * Custom hook for making authenticated API requests.
 * Automatically adds the Supabase auth token to all requests.
 */
export function useAuthFetch() {
    const supabase = getSupabaseClient();
    const { logRequest, logResponse, logError, isEnabled } = useRequestLogger();

    /**
     * Get the current auth token
     */
    const getAuthToken = useCallback(async (): Promise<string | null> => {
        try {
            const { data: { session } } = await supabase.auth.getSession();
            return session?.access_token || null;
        } catch (error) {
            console.error('Failed to get auth token:', error);
            return null;
        }
    }, [supabase]);

    /**
     * Make an authenticated fetch request
     */
    const authFetch = useCallback(async (
        endpoint: string,
        options: RequestInit = {}
    ): Promise<Response> => {
        const token = await getAuthToken();

        const headers: Record<string, string> = {
            ...(options.headers as Record<string, string> || {}),
        };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        // Add Content-Type for JSON requests if body is present and not FormData
        if (options.body && !(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
        }

        const correlationId = generateRequestId();
        const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
        const method = options.method || 'GET';

        const isDev = process.env.NODE_ENV !== 'production';

        // Log to console for debugging (dev only)
        if (isDev) {
            console.log(`[useAuthFetch] [${correlationId}] ${method} ${url} START (Auth: ${token ? 'Bearer' : 'None'})`);
        }

        // Log to request logger for DebugPanel (if enabled)
        if (isEnabled) {
            logRequest(correlationId, method, url, options.body?.toString(), headers);
        }

        const startTime = Date.now();

        try {
            const response = await fetch(url, {
                ...options,
                headers,
            });
            const duration = Date.now() - startTime;

            if (isDev) {
                console.log(`[useAuthFetch] [${correlationId}] ${method} ${url} END [${response.status}] (${duration}ms)`);
            }

            if (response.status === 401 || response.status === 403) {
                if (isDev) {
                    console.warn(`[useAuthFetch] [${correlationId}] AUTH ERROR ${response.status} on ${url}`);
                }
            }
            
            // Log to request logger
            if (isEnabled) {
                logResponse(correlationId, response);
            }

            return response;
        } catch (error) {
            const duration = Date.now() - startTime;
            console.error(`[useAuthFetch] [${correlationId}] ${url} ERROR after ${duration}ms:`, error);
            
            // Log error to request logger
            if (isEnabled && error instanceof Error) {
                logError(correlationId, error);
            }
            
            throw error;
        }
    }, [getAuthToken, isEnabled, logError, logRequest, logResponse]);

    /**
     * GET request helper
     */
    const get = useCallback(async (endpoint: string): Promise<Response> => {
        return authFetch(endpoint, { method: 'GET' });
    }, [authFetch]);

    /**
     * POST request helper
     */
    const post = useCallback(async (
        endpoint: string,
        body?: any
    ): Promise<Response> => {
        const options: RequestInit = { method: 'POST' };

        if (body instanceof FormData) {
            options.body = body;
        } else if (body) {
            options.body = JSON.stringify(body);
        }

        return authFetch(endpoint, options);
    }, [authFetch]);

    /**
     * PUT request helper
     */
    const put = useCallback(async (
        endpoint: string,
        body?: any
    ): Promise<Response> => {
        return authFetch(endpoint, {
            method: 'PUT',
            body: body ? JSON.stringify(body) : undefined,
        });
    }, [authFetch]);

    /**
     * DELETE request helper
     */
    const del = useCallback(async (endpoint: string): Promise<Response> => {
        return authFetch(endpoint, { method: 'DELETE' });
    }, [authFetch]);

    /**
     * PATCH request helper
     */
    const patch = useCallback(async (
        endpoint: string,
        body?: any
    ): Promise<Response> => {
        return authFetch(endpoint, {
            method: 'PATCH',
            body: body ? JSON.stringify(body) : undefined,
        });
    }, [authFetch]);

    // ========================================================================
    // SCOPE-ENFORCED METHODS
    // Use these for type-safe scope enforcement in React components
    // ========================================================================

    /**
     * ALLOWLIST: Endpoints that may accept ?twin_id= for optional filtering.
     * All other tenant endpoints MUST NOT use twin_id parameter.
     */
    const TWIN_FILTER_ALLOWLIST = [
        '/governance/audit-logs',  // Admin can filter audit logs by twin
    ];

    /**
     * Check if endpoint is in the allowlist for optional twin_id filtering
     */
    const isTwinFilterAllowed = useCallback((endpoint: string): boolean => {
        const basePath = endpoint.split('?')[0];
        return TWIN_FILTER_ALLOWLIST.some(allowed => basePath === allowed || basePath.startsWith(allowed + '?'));
    }, []);

    /**
     * Validate tenant endpoint - blocks /twins/ paths AND twin_id params (except allowlist)
     */
    const validateTenantEndpointHook = useCallback((endpoint: string, method: string): void => {
        // Block /twins/{id}/ path patterns
        if (/\/twins\/[^/]+/.test(endpoint)) {
            console.error(`[SCOPE VIOLATION] Tenant ${method} contains /twins/ path:`, endpoint);
            throw new Error(`Tenant-scoped endpoint cannot use /twins/{id} path: ${endpoint}`);
        }
        // Block twin_id query params unless allowlisted
        if (/[?&]twin_id=/.test(endpoint) && !isTwinFilterAllowed(endpoint)) {
            console.error(`[SCOPE VIOLATION] Tenant ${method} contains twin_id param (not allowlisted):`, endpoint);
            throw new Error(`Tenant-scoped endpoint cannot use twin_id param: ${endpoint}. Allowlisted: ${TWIN_FILTER_ALLOWLIST.join(', ')}`);
        }
    }, [isTwinFilterAllowed]);

    /**
     * Tenant-scoped GET - validates no twin references (except allowlist)
     */
    const getTenant = useCallback(async (endpoint: string): Promise<Response> => {
        validateTenantEndpointHook(endpoint, 'GET');
        return authFetch(endpoint, { method: 'GET' });
    }, [authFetch, validateTenantEndpointHook]);

    /**
     * Tenant-scoped POST - validates no twin references
     */
    const postTenant = useCallback(async (endpoint: string, body?: any): Promise<Response> => {
        validateTenantEndpointHook(endpoint, 'POST');
        const options: RequestInit = { method: 'POST' };
        if (body instanceof FormData) {
            options.body = body;
        } else if (body) {
            options.body = JSON.stringify(body);
        }
        return authFetch(endpoint, options);
    }, [authFetch, validateTenantEndpointHook]);

    /**
     * Tenant-scoped DELETE - validates no twin references
     */
    const delTenant = useCallback(async (endpoint: string): Promise<Response> => {
        validateTenantEndpointHook(endpoint, 'DELETE');
        return authFetch(endpoint, { method: 'DELETE' });
    }, [authFetch, validateTenantEndpointHook]);

    /**
     * Twin-scoped GET - validates twinId present and substitutes template
     */
    const getTwin = useCallback(async (twinId: string, endpointTemplate: string): Promise<Response> => {
        if (!twinId) throw new Error('Twin-scoped fetch requires twinId');
        const endpoint = endpointTemplate.replace('{twinId}', twinId);
        const hasTwin = endpoint.includes(`/twins/${twinId}`) || endpoint.includes(`twin_id=${twinId}`);
        if (!hasTwin) {
            console.error('[SCOPE VIOLATION] Twin GET missing twinId:', endpoint);
            throw new Error(`Twin-scoped endpoint must include twinId: ${endpoint}`);
        }
        return authFetch(endpoint, { method: 'GET' });
    }, [authFetch]);

    /**
     * Twin-scoped POST - validates twinId present and substitutes template
     */
    const postTwin = useCallback(async (twinId: string, endpointTemplate: string, body?: any): Promise<Response> => {
        if (!twinId) throw new Error('Twin-scoped fetch requires twinId');
        const endpoint = endpointTemplate.replace('{twinId}', twinId);
        const hasTwin = endpoint.includes(`/twins/${twinId}`) || endpoint.includes(`twin_id=${twinId}`);
        if (!hasTwin) {
            console.error('[SCOPE VIOLATION] Twin POST missing twinId:', endpoint);
            throw new Error(`Twin-scoped endpoint must include twinId: ${endpoint}`);
        }
        const options: RequestInit = { method: 'POST' };
        if (body instanceof FormData) {
            options.body = body;
        } else if (body) {
            options.body = JSON.stringify(body);
        }
        return authFetch(endpoint, options);
    }, [authFetch]);

    /**
     * Twin-scoped DELETE - validates twinId present and substitutes template
     */
    const delTwin = useCallback(async (twinId: string, endpointTemplate: string): Promise<Response> => {
        if (!twinId) throw new Error('Twin-scoped fetch requires twinId');
        const endpoint = endpointTemplate.replace('{twinId}', twinId);
        const hasTwin = endpoint.includes(`/twins/${twinId}`) || endpoint.includes(`twin_id=${twinId}`);
        if (!hasTwin) {
            console.error('[SCOPE VIOLATION] Twin DELETE missing twinId:', endpoint);
            throw new Error(`Twin-scoped endpoint must include twinId: ${endpoint}`);
        }
        return authFetch(endpoint, { method: 'DELETE' });
    }, [authFetch]);

    return {
        authFetch,
        get,
        post,
        put,
        del,
        patch,
        getAuthToken,
        API_BASE_URL,
        // Scope-enforced methods
        getTenant,
        postTenant,
        delTenant,
        getTwin,
        postTwin,
        delTwin,
    };
}

/**
 * Standalone function to get auth headers (for use outside React components)
 */
export async function getAuthHeaders(): Promise<Record<string, string>> {
    const supabase = getSupabaseClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (session?.access_token) {
        return { 'Authorization': `Bearer ${session.access_token}` };
    }

    return {};
}

/**
 * Standalone authenticated fetch for use outside hooks
 */
export async function authFetchStandalone(
    endpoint: string,
    options: RequestInit = {}
): Promise<Response> {
    const authHeaders = await getAuthHeaders();
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;

    const headers: Record<string, string> = {
        ...authHeaders,
        ...(options.headers as Record<string, string> || {}),
    };

    // Add Content-Type for JSON requests if body is present and not FormData
    if (options.body && !(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    return fetch(url, {
        ...options,
        headers,
    });
}

/**
 * Standalone function to get auth token (for use outside React hooks, e.g., streaming)
 */
export async function getAuthToken(): Promise<string | null> {
    const supabase = getSupabaseClient();
    try {
        const { data: { session } } = await supabase.auth.getSession();
        return session?.access_token || null;
    } catch (error) {
        console.error('Failed to get auth token:', error);
        return null;
    }
}

// ============================================================================
// SCOPE ENFORCEMENT PRIMITIVES
// These functions enforce correct twin-scoped vs tenant-scoped behavior.
// Use these instead of raw authFetch to prevent cross-scope data leakage.
// ============================================================================

/**
 * ALLOWLIST: Endpoints that may accept ?twin_id= for optional filtering.
 * All other tenant endpoints MUST NOT use twin_id parameter.
 */
const TWIN_FILTER_ALLOWLIST_STANDALONE = [
    '/governance/audit-logs',  // Admin can filter audit logs by twin
];

/**
 * Check if endpoint is in the allowlist for optional twin_id filtering
 */
function isTwinFilterAllowedStandalone(endpoint: string): boolean {
    const basePath = endpoint.split('?')[0];
    return TWIN_FILTER_ALLOWLIST_STANDALONE.some(allowed => basePath === allowed);
}

/**
 * Validates that an endpoint is tenant-scoped:
 * - Blocks /twins/{id}/ paths
 * - Blocks ?twin_id= params EXCEPT for allowlisted endpoints
 */
function validateTenantEndpoint(endpoint: string): void {
    // Block /twins/{id}/ path patterns
    if (/\/twins\/[^/]+/.test(endpoint)) {
        console.error('[SCOPE VIOLATION] Tenant endpoint contains /twins/ path:', endpoint);
        throw new Error(`Tenant-scoped endpoint cannot use /twins/{id} path: ${endpoint}`);
    }
    // Block twin_id query params unless allowlisted
    if (/[?&]twin_id=/.test(endpoint) && !isTwinFilterAllowedStandalone(endpoint)) {
        console.error('[SCOPE VIOLATION] Tenant endpoint contains twin_id param (not allowlisted):', endpoint);
        throw new Error(`Tenant-scoped endpoint cannot use twin_id param: ${endpoint}. Allowlisted: ${TWIN_FILTER_ALLOWLIST_STANDALONE.join(', ')}`);
    }
}

/**
 * Validates that an endpoint is twin-scoped (requires twin reference)
 */
function validateTwinEndpoint(endpoint: string, twinId: string): void {
    if (!twinId) {
        throw new Error('Twin-scoped fetch requires twinId');
    }

    // Endpoint must contain the twinId in path or as a template placeholder
    const hasTwinInPath = endpoint.includes(`/twins/${twinId}`) ||
        endpoint.includes(`twin_id=${twinId}`) ||
        endpoint.includes('{twinId}');

    if (!hasTwinInPath) {
        console.error('[SCOPE VIOLATION] Twin endpoint missing twinId:', endpoint);
        throw new Error(`Twin-scoped endpoint must include twinId: ${endpoint}`);
    }
}

/**
 * Standalone tenant-scoped fetch - NEVER includes twinId
 * Use for: /api-keys, /access-groups, /governance/policies, /connectors
 */
export async function authFetchTenant(
    endpoint: string,
    options: RequestInit = {}
): Promise<Response> {
    validateTenantEndpoint(endpoint);
    return authFetchStandalone(endpoint, options);
}

/**
 * Standalone twin-scoped fetch - REQUIRES twinId in endpoint
 * Supports {twinId} template replacement
 * Use for: /twins/{twinId}/..., /metrics/dashboard/{twinId}, etc.
 */
export async function authFetchTwin(
    twinId: string,
    endpointTemplate: string,
    options: RequestInit = {}
): Promise<Response> {
    // Replace {twinId} template placeholder if present
    const endpoint = endpointTemplate.replace('{twinId}', twinId);
    validateTwinEndpoint(endpoint, twinId);
    return authFetchStandalone(endpoint, options);
}

export { API_BASE_URL };  // Re-export for backward compatibility
