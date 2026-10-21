'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';
import { resolveApiBaseUrl } from '@/lib/api';
import type { AuthChangeEvent, Session } from '@supabase/supabase-js';

// ============================================================================
// Types
// ============================================================================

export type TwinStatus = 'draft' | 'ingesting' | 'claims_ready' | 'clarification_pending' | 'persona_built' | 'active';

export interface Twin {
    id: string;
    name: string;
    owner_id: string;
    tenant_id: string;
    specialization: string;
    status: TwinStatus;
    is_active: boolean;
    settings?: Record<string, unknown>;
    system_instructions?: string;
    created_at: string;
    updated_at: string;
}

export interface UserProfile {
    id: string;
    email: string;
    full_name?: string;
    avatar_url?: string;
    tenant_id?: string;
    onboarding_completed: boolean;
    dashboard_walkthrough_completed_at?: string | null;
    created_at?: string;
    // RBAC role - used for privilege checks (admin views, etc.)
    role?: 'owner' | 'viewer' | string;  // owner = admin, viewer = standard user
}

type SyncStatus = 'idle' | 'syncing' | 'ok' | 'retrying' | 'error' | 'account-deleted';

interface TwinContextType {
    // User state
    user: UserProfile | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    error: string | null;  // NEW: Explicit error state
    syncStatus: SyncStatus;
    syncMessage: string | null;
    syncRetryAt: number | null;

    // Twin state
    twins: Twin[];
    activeTwin: Twin | null;

    // Actions
    setActiveTwin: (twinId: string) => void;
    refreshTwins: (optsOrToken?: { allowEmpty?: boolean } | string, providedToken?: string) => Promise<void>;
    syncUser: () => Promise<UserProfile | null>;
    clearActiveTwin: () => void;
}

const TwinContext = createContext<TwinContextType | undefined>(undefined);

// ============================================================================
// Provider Component
// ============================================================================

export function TwinProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<UserProfile | null>(null);
    const [twins, setTwins] = useState<Twin[]>([]);
    const [activeTwin, setActiveTwinState] = useState<Twin | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [syncStatus, setSyncStatus] = useState<SyncStatus>('idle');
    const [syncMessage, setSyncMessage] = useState<string | null>(null);
    const [syncRetryAt, setSyncRetryAt] = useState<number | null>(null);
    const [mountId] = useState(() => Math.random().toString(36).substring(7));

    // ========================================================================
    // StrictMode + Race Protection Refs
    // ========================================================================
    const initRef = useRef(false);           // Prevents duplicate initialization in StrictMode
    const requestIdRef = useRef(0);          // Race protection: ignore stale responses
    const mountedRef = useRef(true);         // Track mounted state
    const isHydratedRef = useRef(false);     // Track first successful twin load (prevents transient wipe)
    const tokenRef = useRef<string | null>(null); // In-memory token cache to prevent getSession race
    const syncInFlightRef = useRef<Promise<UserProfile | null> | null>(null);
    const syncAttemptRef = useRef(0);
    const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastGoodUserRef = useRef<UserProfile | null>(null);
    const syncTimelineRef = useRef<Array<{ ts: string; event: string; detail?: Record<string, unknown> }>>([]);
    const syncExternalInFlightRef = useRef(false);
    const syncChannelRef = useRef<BroadcastChannel | null>(null);
    const sessionUserIdRef = useRef<string | null>(null);

    const supabase = getSupabaseClient();
    const API_URL = resolveApiBaseUrl();
    const isE2EBypass =
        process.env.NODE_ENV !== 'production' &&
        process.env.NEXT_PUBLIC_E2E_BYPASS_AUTH === '1';
    const SYNC_TIMEOUT_MS = 8000;
    const SYNC_RETRY_BASE_MS = 1000;
    const SYNC_RETRY_MAX_MS = 30000;
    const SYNC_RETRY_MAX_ATTEMPTS = 5;
    const SYNC_CACHE_KEY = 'cachedUserProfile';

    // ========================================================================
    // Stable localStorage helpers
    // ========================================================================
    const getPersistedTwinId = useCallback((): string | null => {
        try {
            return typeof window !== 'undefined' ? localStorage.getItem('activeTwinId') : null;
        } catch {
            return null; // localStorage unavailable (SSR, private browsing)
        }
    }, []);

    const persistTwinId = useCallback((twinId: string) => {
        try {
            if (typeof window !== 'undefined') {
                localStorage.setItem('activeTwinId', twinId);
                console.log('[TwinContext] Persisted activeTwinId:', twinId);
            }
        } catch {
            // localStorage unavailable
        }
    }, []);

    const logSyncEvent = useCallback((event: string, detail?: Record<string, unknown>) => {
        const entry = { ts: new Date().toISOString(), event, detail };
        syncTimelineRef.current.push(entry);
        if (syncTimelineRef.current.length > 50) {
            syncTimelineRef.current.shift();
        }
        try {
            if (typeof window !== 'undefined') {
                (window as any).__SYNC_USER_TIMELINE__ = syncTimelineRef.current;
            }
        } catch {
            // ignore
        }
        console.log(`[TwinContext][${mountId}] syncUser ${event}`, detail || {});
    }, [mountId]);

    const loadCachedUser = useCallback((sessionUserId?: string): UserProfile | null => {
        try {
            if (typeof window === 'undefined') return null;
            const raw = localStorage.getItem(SYNC_CACHE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw) as UserProfile | null;
            if (!parsed?.id) return null;
            if (sessionUserId && parsed.id !== sessionUserId) return null;
            return parsed;
        } catch {
            return null;
        }
    }, []);

    const persistCachedUser = useCallback((profile: UserProfile | null) => {
        try {
            if (typeof window === 'undefined') return;
            if (!profile) {
                localStorage.removeItem(SYNC_CACHE_KEY);
                return;
            }
            localStorage.setItem(SYNC_CACHE_KEY, JSON.stringify(profile));
        } catch {
            // ignore
        }
    }, []);

    // Get auth token (with timeout and retry logic)
    const getToken = useCallback(async (): Promise<string | null> => {
        // Priority 1: In-memory cache (prevents race condition after TOKEN_REFRESHED)
        if (tokenRef.current) {
            console.log('[TwinContext] Using token from in-memory cache');
            return tokenRef.current;
        }

        const maxRetries = 3;
        const baseTimeout = 5000;

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                console.log(`[TwinContext] getToken attempt ${attempt}/${maxRetries}`);
                const timeoutPromise = new Promise<null>((resolve) => {
                    setTimeout(() => resolve(null), baseTimeout * attempt);
                });

                const result = await Promise.race([
                    supabase.auth.getSession(),
                    timeoutPromise
                ]) as any;

                const token = result?.data?.session?.access_token || null;
                if (token) {
                    console.log('[TwinContext] Token obtained successfully');
                    return token;
                }

                console.warn(`[TwinContext] No token on attempt ${attempt}`);
            } catch (e) {
                console.warn(`[TwinContext] getToken attempt ${attempt} failed:`, e);
            }
        }

        console.error('[TwinContext] All token retrieval attempts failed');
        return null;
    }, [supabase]);

    // Sync user with backend
    const scheduleSyncRetry = useCallback((reason: string, token: string | undefined, retryFn: (token?: string) => void) => {
        if (syncAttemptRef.current >= SYNC_RETRY_MAX_ATTEMPTS) {
            setSyncStatus('error');
            setSyncMessage('Sync paused. Please check your connection.');
            setSyncRetryAt(null);
            logSyncEvent('retry_exhausted', { reason });
            return;
        }

        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            setSyncStatus('retrying');
            setSyncMessage('You are offline. Sync will resume when you reconnect.');
            setSyncRetryAt(null);
            logSyncEvent('retry_offline', { reason });
            return;
        }

        syncAttemptRef.current += 1;
        const attempt = syncAttemptRef.current;
        const baseDelay = Math.min(SYNC_RETRY_MAX_MS, SYNC_RETRY_BASE_MS * 2 ** (attempt - 1));
        const jitter = Math.floor(Math.random() * 250);
        const delay = baseDelay + jitter;
        const retryAt = Date.now() + delay;

        setSyncStatus('retrying');
        setSyncMessage(`Sync temporarily unavailable. Retrying in ${Math.ceil(delay / 1000)}s.`);
        setSyncRetryAt(retryAt);
        logSyncEvent('retry_scheduled', { reason, attempt, delay });

        if (syncTimerRef.current) {
            clearTimeout(syncTimerRef.current);
        }
        syncTimerRef.current = setTimeout(() => {
            retryFn(token);
        }, delay);
    }, [logSyncEvent]);

    const syncUser = useCallback(async (providedToken?: string): Promise<UserProfile | null> => {
        if (syncExternalInFlightRef.current) {
            logSyncEvent('sync_skipped_external_inflight');
            return lastGoodUserRef.current;
        }
        if (syncInFlightRef.current) {
            logSyncEvent('sync_deduped');
            return syncInFlightRef.current;
        }

        const runSync = (async () => {
            const token = providedToken || await getToken();
            if (!token) {
                logSyncEvent('sync_no_token');
                setSyncStatus('error');
                setSyncMessage('Authentication required. Please sign in again.');
                return null;
            }

            // Sync token cache if we were provided one
            if (providedToken) tokenRef.current = providedToken;

            const url = `${API_URL}/auth/sync-user`;
            const correlationId = Math.random().toString(36).substring(7);
            const attempt = syncAttemptRef.current + 1;
            setSyncStatus(attempt > 1 ? 'retrying' : 'syncing');
            setSyncMessage(attempt > 1 ? `Sync retry ${attempt}...` : null);
            logSyncEvent('sync_start', { correlationId, attempt });
            syncChannelRef.current?.postMessage({ type: 'sync-start', correlationId, ts: Date.now() });

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), SYNC_TIMEOUT_MS);

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                        'X-Correlation-Id': correlationId,
                        'X-Client-Time': new Date().toISOString()
                    },
                    signal: controller.signal
                });

                clearTimeout(timeoutId);
                logSyncEvent('sync_response', { correlationId, status: response.status });

                if (response.status === 401) {
                    const errorText = await response.text();
                    if (errorText.toLowerCase().includes('account has been deleted')) {
                        setSyncStatus('account-deleted');
                        setSyncMessage('Account deleted. Redirecting...');
                        logSyncEvent('account_deleted', { correlationId });
                        try {
                            await supabase.auth.signOut();
                        } catch {
                            // ignore
                        }
                        if (mountedRef.current) {
                            setUser(null);
                            setTwins([]);
                            setActiveTwinState(null);
                            persistCachedUser(null);
                            try { localStorage.removeItem('activeTwinId'); } catch { }
                        }
                        try {
                            if (typeof window !== 'undefined') {
                                window.location.assign('/auth/login?reason=account_deleted');
                            }
                        } catch {
                            // ignore
                        }
                        syncChannelRef.current?.postMessage({ type: 'sync-end', correlationId, ts: Date.now() });
                        return null;
                    }

                    setSyncStatus('error');
                    setSyncMessage('Session expired. Please sign in again.');
                    logSyncEvent('sync_auth_error', { correlationId, detail: errorText.slice(0, 200) });
                    syncChannelRef.current?.postMessage({ type: 'sync-end', correlationId, ts: Date.now() });
                    return null;
                }

                if (!response.ok) {
                    const errorText = await response.text();
                    logSyncEvent('sync_http_error', { correlationId, status: response.status, detail: errorText.slice(0, 200) });
                    scheduleSyncRetry(`HTTP ${response.status}`, token, syncUser);
                    syncChannelRef.current?.postMessage({ type: 'sync-end', correlationId, ts: Date.now() });
                    return lastGoodUserRef.current;
                }

                const data = await response.json();
                const nextUser: UserProfile | null = data?.user && data.user.id ? data.user : null;
                if (nextUser && mountedRef.current) {
                    setUser(nextUser);
                    lastGoodUserRef.current = nextUser;
                    persistCachedUser(nextUser);
                }
                if (nextUser) {
                    syncChannelRef.current?.postMessage({ type: 'sync-success', correlationId, ts: Date.now(), user: nextUser });
                }

                setSyncStatus('ok');
                setSyncMessage(null);
                setSyncRetryAt(null);
                syncAttemptRef.current = 0;
                logSyncEvent('sync_success', { correlationId });
                syncChannelRef.current?.postMessage({ type: 'sync-end', correlationId, ts: Date.now() });
                return nextUser || lastGoodUserRef.current;
            } catch (error: any) {
                clearTimeout(timeoutId);
                const isAbort = error?.name === 'AbortError';
                logSyncEvent('sync_error', { correlationId, isAbort, message: error?.message || 'unknown' });
                scheduleSyncRetry(isAbort ? 'timeout' : 'network', token || undefined, syncUser);
                syncChannelRef.current?.postMessage({ type: 'sync-end', correlationId, ts: Date.now() });
                return lastGoodUserRef.current;
            }
        })();

        syncInFlightRef.current = runSync;
        try {
            return await runSync;
        } finally {
            syncInFlightRef.current = null;
        }
    }, [API_URL, getToken, logSyncEvent, persistCachedUser, scheduleSyncRetry, supabase]);

    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (typeof BroadcastChannel === 'undefined') return;

        const channel = new BroadcastChannel('sync-user');
        syncChannelRef.current = channel;

        channel.onmessage = (event) => {
            const data = event.data || {};
            if (data.type === 'sync-start') {
                syncExternalInFlightRef.current = true;
                return;
            }
            if (data.type === 'sync-end') {
                syncExternalInFlightRef.current = false;
                return;
            }
            if (data.type === 'sync-success' && data.user?.id && sessionUserIdRef.current === data.user.id) {
                setUser(data.user);
                lastGoodUserRef.current = data.user;
                persistCachedUser(data.user);
                setSyncStatus('ok');
                setSyncMessage(null);
                setSyncRetryAt(null);
            }
        };

        return () => {
            channel.close();
            syncChannelRef.current = null;
        };
    }, [persistCachedUser]);

    useEffect(() => {
        if (typeof window === 'undefined') return;
        const handleOnline = () => {
            logSyncEvent('online');
            syncUser(tokenRef.current || undefined);
        };
        window.addEventListener('online', handleOnline);
        return () => window.removeEventListener('online', handleOnline);
    }, [logSyncEvent, syncUser]);

    // ========================================================================
    // Stable Selection Algorithm
    // ========================================================================
    const selectActiveTwin = useCallback((
        twinsList: Twin[],
        currentActiveTwinId: string | null
    ): Twin | null => {
        if (twinsList.length === 0) {
            console.log('[TwinContext] selectActiveTwin: No twins available');
            return null;
        }

        const persistedId = getPersistedTwinId();

        // Priority 1: localStorage (if exists in new list)
        // This allows explicit redirects (onboarding/profile/chat) to switch the
        // active twin deterministically by writing activeTwinId first.
        if (persistedId) {
            const found = twinsList.find(t => t.id === persistedId);
            if (found) {
                console.log('[TwinContext] selectActiveTwin: Using localStorage:', persistedId);
                return found;
            }
        }

        // Priority 2: Current activeTwin state (if exists in new list)
        if (currentActiveTwinId) {
            const found = twinsList.find(t => t.id === currentActiveTwinId);
            if (found) {
                console.log('[TwinContext] selectActiveTwin: Keeping current state:', currentActiveTwinId);
                return found;
            }
        }

        // Priority 3: Deterministic default (first in ordered list)
        const defaultTwin = twinsList[0];
        console.log('[TwinContext] selectActiveTwin: Using default (first):', defaultTwin.id);
        return defaultTwin;
    }, [getPersistedTwinId]);

    // ========================================================================
    // refreshTwins with Race Protection
    // ========================================================================
    const refreshTwins = useCallback(async (optsOrToken?: { allowEmpty?: boolean } | string, providedToken?: string) => {
        // Race protection: increment request ID
        const thisRequestId = ++requestIdRef.current;
        console.log('[TwinContext] refreshTwins called, requestId:', thisRequestId);
        setError(null);

        const options = (typeof optsOrToken === 'object' && optsOrToken !== null ? optsOrToken : {}) as { allowEmpty?: boolean };
        const tokenArg = typeof optsOrToken === 'string' ? optsOrToken : providedToken;

        try {
            const token = tokenArg || await getToken();

            // Sync token cache if we were provided one
            if (tokenArg) tokenRef.current = tokenArg;

            // Race check after async
            if (thisRequestId !== requestIdRef.current) {
                console.log('[TwinContext] refreshTwins: Stale request, ignoring');
                return;
            }

            if (!token) {
                console.error('[TwinContext] No auth token available');
                if (mountedRef.current) setError('Authentication required. Please sign in.');
                return;
            }

            const url = `${API_URL}/auth/my-twins`;
            const correlationId = Math.random().toString(36).substring(7);
            console.log(`[TwinContext][${mountId}] refreshTwins [${correlationId}] fetching:`, url);

            const response = await fetch(url, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            // Race check after fetch
            if (thisRequestId !== requestIdRef.current) {
                console.log('[TwinContext] refreshTwins: Stale after fetch, ignoring');
                return;
            }

            if (!response.ok) {
                const errorText = await response.text();
                console.error(`[TwinContext] API error ${response.status}: ${errorText}`);
                if (mountedRef.current) setError(`Failed to fetch twins: ${response.status}`);
                return;
            }

            const data = await response.json();
            const twinsList: Twin[] = Array.isArray(data) ? data : (data.twins || []);
            console.log('[TwinContext] refreshTwins received:', twinsList.length, 'twins');

            // Final race check before state update
            if (thisRequestId !== requestIdRef.current || !mountedRef.current) {
                console.log('[TwinContext] refreshTwins: Stale before setState, ignoring');
                return;
            }

            // CRITICAL: Only wipe twins if we have NOT hydrated yet (first load)
            // OR if we genuinely get an empty list after a successful prior load.
            // This prevents transient failures from wiping existing state.
            if (twinsList.length === 0 && isHydratedRef.current && !options.allowEmpty) {
                // We already have twins, got empty response - could be transient. 
                // Keep existing state and log warning.
                console.warn(`[TwinContext][${mountId}] refreshTwins: Empty response but already hydrated. Keeping existing twins.`);
                return; // DO NOT wipe state
            }

            // Mark as hydrated on first successful response (even if empty)
            if (!isHydratedRef.current) {
                isHydratedRef.current = true;
                console.log(`[TwinContext][${mountId}] First hydration complete.`);
            }

            setTwins(twinsList);

            // Use stable selection algorithm
            setActiveTwinState(prevActiveTwin => {
                const selected = selectActiveTwin(twinsList, prevActiveTwin?.id || null);
                if (selected) {
                    persistTwinId(selected.id);
                } else if (options.allowEmpty || twinsList.length === 0) {
                    try { localStorage.removeItem('activeTwinId'); } catch { }
                }
                console.log(`[TwinContext][${mountId}] refreshTwins complete. Active:`, selected?.id, 'Total:', twinsList.length);
                return selected;
            });

        } catch (err) {
            if (thisRequestId === requestIdRef.current && mountedRef.current) {
                console.error('[TwinContext] Error fetching twins:', err);
                // DO NOT set error or wipe state on transient failures
                // setError('Network error fetching twins'); // REMOVED
                console.warn(`[TwinContext][${mountId}] Transient error - keeping existing twins state.`);
            }
        }
    }, [API_URL, getToken, selectActiveTwin, persistTwinId, mountId]);

    // ========================================================================
    // Set active twin (user action)
    // ========================================================================
    const setActiveTwin = useCallback((twinId: string) => {
        const twin = twins.find(t => t.id === twinId);
        if (twin) {
            setActiveTwinState(twin);
            persistTwinId(twinId);
            console.log('[TwinContext] User selected twin:', twinId);
        } else {
            console.warn('[TwinContext] setActiveTwin: Twin not found in list:', twinId);
        }
    }, [twins, persistTwinId]);

    const clearActiveTwin = useCallback(() => {
        setActiveTwinState(null);
        try { localStorage.removeItem('activeTwinId'); } catch { }
    }, []);

    // ========================================================================
    // Initialization (StrictMode-safe)
    // ========================================================================
    useEffect(() => {
        console.log(`[TwinContext][${mountId}] MOUNTED`);
        mountedRef.current = true;

        if (isE2EBypass) {
            const fakeTwin: Twin = {
                id: 'e2e-twin',
                name: 'E2E Twin',
                owner_id: 'e2e-user',
                tenant_id: 'e2e-tenant',
                specialization: 'digital-persona',
                status: 'active',
                is_active: true,
                settings: {
                    handle: 'e2e-persona',
                },
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString()
            };
            const fakeUser: UserProfile = {
                id: 'e2e-user',
                email: 'e2e@local',
                onboarding_completed: true,
                tenant_id: 'e2e-tenant',
                role: 'owner'
            };
            setUser(fakeUser);
            setTwins([fakeTwin]);
            setActiveTwinState(fakeTwin);
            setIsLoading(false);
            return () => {
                mountedRef.current = false;
            };
        }

        const initialize = async () => {
            if (initRef.current) {
                console.log(`[TwinContext][${mountId}] Already initialized, skipping`);
                return;
            }
            initRef.current = true;

            console.log(`[TwinContext][${mountId}] Starting initialization...`);
            setIsLoading(true);

            try {
                const { data: { session } } = await supabase.auth.getSession();
                console.log(`[TwinContext][${mountId}] Initial session:`, session ? `exists (expires: ${new Date(session.expires_at! * 1000).toISOString()})` : 'null');
                sessionUserIdRef.current = session?.user?.id || null;

                if (!mountedRef.current) return;

                if (session?.access_token) {
                    tokenRef.current = session.access_token;
                    const cachedUser = loadCachedUser(session.user.id);
                    if (cachedUser && mountedRef.current) {
                        setUser(cachedUser);
                        lastGoodUserRef.current = cachedUser;
                    }
                    syncUser(session.access_token);
                    await refreshTwins(session.access_token);
                } else {
                    console.log(`[TwinContext][${mountId}] No session - prompting sign in`);
                    setError('Please sign in to continue');
                }
            } catch (error) {
                console.error(`[TwinContext][${mountId}] Initialization error:`, error);
            } finally {
                if (mountedRef.current) {
                    console.log(`[TwinContext][${mountId}] Initialization complete`);
                    setIsLoading(false);
                }
            }
        };

        initialize();

        const { data: { subscription } } = supabase.auth.onAuthStateChange(
            async (event: AuthChangeEvent, session: Session | null) => {
                console.log(`[TwinContext][${mountId}] Auth event:`, event, 'Session:', session ? 'exists' : 'null');

                if ((event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') && session && mountedRef.current) {
                    console.log(`[TwinContext][${mountId}] Syncing for event: ${event}`);
                    // Update cache immediately to prevent raciness
                    tokenRef.current = session.access_token;
                    sessionUserIdRef.current = session.user?.id || null;

                    // Only block the UI with a loading spinner on the very first sign-in.
                    // If already hydrated (twins loaded at least once), refresh silently in the background.
                    const showLoading = event === 'SIGNED_IN' && !isHydratedRef.current;
                    if (showLoading) {
                        setIsLoading(true);
                    }
                    syncUser(session.access_token);
                    await refreshTwins(session.access_token);
                    if (mountedRef.current && showLoading) {
                        setIsLoading(false);
                    }
                } else if (event === 'SIGNED_OUT' && mountedRef.current) {
                    console.warn(`[TwinContext][${mountId}] SIGNED_OUT detected - clearing state`);
                    tokenRef.current = null; // Clear cache
                    sessionUserIdRef.current = null;
                    setUser(null);
                    setTwins([]);
                    setActiveTwinState(null);
                    setSyncStatus('idle');
                    setSyncMessage(null);
                    setSyncRetryAt(null);
                    persistCachedUser(null);
                    try { localStorage.removeItem('activeTwinId'); } catch { }
                    initRef.current = false;
                    isHydratedRef.current = false; // Reset hydration on signout
                }
            }
        );

        return () => {
            console.log(`[TwinContext][${mountId}] UNMOUNTING`);
            mountedRef.current = false;
            subscription.unsubscribe();
            if (syncTimerRef.current) {
                clearTimeout(syncTimerRef.current);
                syncTimerRef.current = null;
            }
        };
    }, [supabase, syncUser, refreshTwins, API_URL, mountId, loadCachedUser, persistCachedUser, isE2EBypass]);

    const value: TwinContextType = {
        user,
        isAuthenticated: !!user,
        isLoading,
        error,
        syncStatus,
        syncMessage,
        syncRetryAt,
        twins,
        activeTwin,
        setActiveTwin,
        refreshTwins,
        syncUser,
        clearActiveTwin
    };

    return (
        <TwinContext.Provider value={value}>
            {children}
        </TwinContext.Provider>
    );
}

// ============================================================================
// Hook
// ============================================================================

export function useTwin(): TwinContextType {
    const context = useContext(TwinContext);
    if (context === undefined) {
        throw new Error('useTwin must be used within a TwinProvider');
    }
    return context;
}

// Convenience hooks
export function useActiveTwin(): Twin | null {
    const { activeTwin } = useTwin();
    return activeTwin;
}

export function useUser(): UserProfile | null {
    const { user } = useTwin();
    return user;
}

/**
 * Check if a twin can be chatted with (status === 'active')
 */
export function useCanChat(twin?: Twin | null): boolean {
    const { activeTwin } = useTwin();
    const targetTwin = twin || activeTwin;
    return targetTwin?.status === 'active' || targetTwin?.is_active === true;
}

/**
 * Get the onboarding resume URL for a non-active twin
 */
export function getOnboardingResumeUrl(twinId: string): string {
    return `/onboarding?twinId=${encodeURIComponent(twinId)}`;
}
