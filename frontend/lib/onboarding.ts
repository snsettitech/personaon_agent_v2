import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';

export interface ConsentState {
  accepted: boolean;
  terms_version?: string | null;
  privacy_version?: string | null;
  accepted_at?: string | null;
}

export interface PersonaSummary {
  twin_id: string;
  handle?: string | null;
  public_url?: string | null;
  persona_quality: string;
  enrichment_status: string;
}

export interface OnboardingStatus {
  consent_required: boolean;
  consent: ConsentState;
  has_persona: boolean;
  persona: PersonaSummary | null;
  next_route: string;
}

export interface CreatePersonaPayload {
  full_name: string;
  headline: string;
  short_intro?: string;
  linkedin_url?: string;
  website_url?: string;
  avatar_url?: string;
}

export interface CreatePersonaResponse {
  twin_id: string;
  handle: string;
  public_url: string;
  persona_quality: string;
  enrichment_status: string;
}

export interface IdentityStatus {
  verified: boolean;
  provider?: string | null;
  display_name?: string;
  headline?: string;
  profile_url?: string;
  image_url?: string;
}

export interface SessionInitResponse {
  consent_required: boolean;
  has_persona: boolean;
  next_route: string;
  display_name: string | null;
  email: string | null;
  avatar_url: string | null;
  identity: IdentityStatus;
  /** Actual Supabase auth provider (google/linkedin_oidc/email) — NOT identity.provider,
   *  which only reflects a verified LinkedIn profile used for form pre-fill. */
  auth_provider: string | null;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    // authFetchStandalone returns 401 when there's no session token. Surface
    // a stable error string so callers can route to /auth/login.
    throw new Error('Authentication required.');
  }
  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`;
    try {
      const body = await response.json();
      // Backend uses {error, message} for some failures and detail string for others.
      message = body?.detail?.message ?? body?.message ?? body?.detail ?? message;
      if (typeof message !== 'string') {
        message = `Request failed with status ${response.status}.`;
      }
    } catch {
      // Keep status-based message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

/**
 * Backend returns `status: "created"` for first-ever sync (new signup) and
 * `status: "exists"` for returning users (see SyncUserResponse in
 * backend/routers/auth.py). Surfaced so callers can tell
 * auth_signup_completed from auth_login_completed without a second signal.
 */
export interface SyncUserResult {
  status: 'created' | 'exists';
}

export async function syncAuthenticatedUser(): Promise<SyncUserResult | null> {
  const response = await authFetchStandalone('/auth/sync-user', { method: 'POST' });
  if (response.status === 401) {
    throw new Error('Authentication required.');
  }
  if (!response.ok) {
    throw new Error('Unable to prepare your account. Please try again.');
  }
  try {
    const body = await response.json();
    const status = body?.status === 'created' ? 'created' : 'exists';
    return { status };
  } catch {
    // Sync still succeeded, but the response wasn't JSON — caller can't
    // tell new vs. returning and should fall back to a neutral signal.
    return null;
  }
}

export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  const response = await authFetchStandalone('/onboarding/status');
  return parseResponse<OnboardingStatus>(response);
}

export async function acceptOnboardingConsent(): Promise<ConsentState> {
  const response = await authFetchStandalone('/onboarding/consent', {
    method: 'POST',
    body: JSON.stringify({ accepted: true }),
  });
  return parseResponse<ConsentState>(response);
}

export async function createOnboardingPersona(payload: CreatePersonaPayload): Promise<CreatePersonaResponse> {
  const response = await authFetchStandalone('/onboarding/persona', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return parseResponse<CreatePersonaResponse>(response);
}

export async function getIdentityStatus(): Promise<IdentityStatus> {
  const response = await authFetchStandalone('/auth/identity-status');
  return parseResponse<IdentityStatus>(response);
}
export async function sessionInit(): Promise<SessionInitResponse> {
  const response = await authFetchStandalone('/auth/session-init', { method: 'POST' });
  return parseResponse<SessionInitResponse>(response);
}

/**
 * Result of post-auth routing. Includes whether the just-authenticated user
 * is brand new (from the sync-user response) alongside the destination, so
 * callers can fire the correct signup-vs-login analytics event without a
 * second network round-trip or an unreliable route-string heuristic — see
 * the note on resolvePostAuthRoute below for why that matters.
 */
export interface PostAuthResolution {
  route: string;
  /** 'created' = first-ever sync (signup), 'exists' = returning user, null = sync failed. */
  syncStatus: 'created' | 'exists' | null;
}

/**
 * Decide where to send the user after a successful sign-in.
 *
 * Calls /onboarding/status and routes directly to the right destination
 * instead of always bouncing through /legal/accept (which then re-redirects).
 * Avoids a flash + extra round-trip for users who have already accepted
 * consent, or for whom the consent gate is disabled at the env level.
 *
 * @param desiredRedirect The path the user originally tried to reach (or '/dashboard').
 * @returns The route AND the sync status behind it — never infer new-vs-
 *   returning from the route string alone. `/onboarding` is reachable by a
 *   returning user who never finished onboarding, one who deleted their
 *   persona, or the network-failure fallback below — none of them signups.
 */
export async function resolvePostAuthRouteWithStatus(desiredRedirect: string): Promise<PostAuthResolution> {
  const safeRedirect =
    desiredRedirect && desiredRedirect.startsWith('/') && !desiredRedirect.startsWith('//')
      ? desiredRedirect
      : '/dashboard';

  try {
    const sync = await syncAuthenticatedUser();
    const status = await getOnboardingStatus();
    const syncStatus = sync?.status ?? null;

    if (status.consent_required) {
      const next = status.has_persona ? safeRedirect : '/onboarding';
      return { route: `/legal/accept?next=${encodeURIComponent(next)}`, syncStatus };
    }
    if (status.has_persona) {
      return { route: safeRedirect, syncStatus };
    }
    return { route: '/onboarding', syncStatus };
  } catch {
    // Status check failed (network/backend issue). Don't silently fall back
    // to the requested redirect — a brand-new user without a persona could
    // land on /dashboard and see a half-empty UI thinking everything's fine.
    // Route to /onboarding with a banner-trigger query param so the user can
    // retry the status fetch and see what went wrong. syncStatus is null —
    // deliberately unknown, not a signup — since the failure could hit any user.
    return { route: '/onboarding?error=status_unavailable', syncStatus: null };
  }
}

/** Route-only convenience wrapper for callers that don't need syncStatus (e.g. invitation accept). */
export async function resolvePostAuthRoute(desiredRedirect: string): Promise<string> {
  const { route } = await resolvePostAuthRouteWithStatus(desiredRedirect);
  return route;
}
