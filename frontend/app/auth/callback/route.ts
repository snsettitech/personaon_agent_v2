import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// OAuth/email confirmation callback handler.
// Exchanges the PKCE code for a session and routes the user through consent,
// onboarding, or dashboard based on backend onboarding status.
const _DEV_HOSTS = process.env.NODE_ENV === 'development'
  ? ['localhost:3001', '127.0.0.1:3001']
  : [];

const ALLOWED_HOSTS = new Set([
  'personaon-web-czlsihxvra-uc.a.run.app',
  'personaon-web-837700257032.us-central1.run.app',
  'personaon.com',
  'www.personaon.com',
  'localhost:3000',
  '127.0.0.1:3000',
  ..._DEV_HOSTS,
].filter(Boolean));

function getPublicOrigin(request: NextRequest): string {
  if (process.env.NEXT_PUBLIC_FRONTEND_URL) return process.env.NEXT_PUBLIC_FRONTEND_URL;
  const forwarded = request.headers.get('x-forwarded-host');
  if (forwarded && ALLOWED_HOSTS.has(forwarded)) {
    const proto = request.headers.get('x-forwarded-proto') || 'https';
    return `${proto}://${forwarded}`;
  }
  return new URL(request.url).origin;
}

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url);
  const publicOrigin = getPublicOrigin(request);
  const code = requestUrl.searchParams.get('code');
  const error = requestUrl.searchParams.get('error');
  const errorDescription = requestUrl.searchParams.get('error_description');
  const rawRedirect = requestUrl.searchParams.get('redirect') || '';
  const redirectParam = rawRedirect && /^\/[^/]/.test(rawRedirect) ? rawRedirect : '/onboarding';

  if (error) {
    console.error('OAuth error:', error, errorDescription);
    const loginUrl = new URL('/auth/login', publicOrigin);
    loginUrl.searchParams.set('error', error);
    if (errorDescription) {
      loginUrl.searchParams.set('error_description', errorDescription);
    }
    if (redirectParam && redirectParam !== '/onboarding') {
      loginUrl.searchParams.set('redirect', redirectParam);
    }
    return NextResponse.redirect(loginUrl);
  }

  if (!code) {
    const loginUrl = new URL('/auth/login', publicOrigin);
    if (redirectParam && redirectParam !== '/onboarding') {
      loginUrl.searchParams.set('redirect', redirectParam);
    }
    return NextResponse.redirect(loginUrl);
  }

  try {
    const cookieStore = await cookies();

    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll();
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          },
        },
      }
    );

    const { data: sessionData, error: exchangeError } =
      await supabase.auth.exchangeCodeForSession(code);

    if (exchangeError) {
      console.error('Session exchange error:', exchangeError);
      const loginUrl = new URL('/auth/login', publicOrigin);
      loginUrl.searchParams.set('error', 'session_exchange_failed');
      loginUrl.searchParams.set('redirect', redirectParam);
      return NextResponse.redirect(loginUrl);
    }

    let finalRedirect = '/onboarding';
    let syncFailed = false;
    const consentGateEnabled = process.env.NEXT_PUBLIC_ENABLE_PENDING_CONSENT === 'true';

    if (sessionData?.session?.access_token) {
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || '';
        if (!backendUrl) {
          console.error('[Callback] NEXT_PUBLIC_BACKEND_URL not set; skipping sync-user');
          syncFailed = true;
        } else {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 15000);
          await fetch(`${backendUrl}/auth/sync-user`, {
            method: 'POST',
            headers: {
              Authorization: `Bearer ${sessionData.session.access_token}`,
              'Content-Type': 'application/json',
            },
            signal: controller.signal,
          });
          clearTimeout(timeoutId);

          const statusController = new AbortController();
          const statusTimeoutId = setTimeout(() => statusController.abort(), 10000);
          const statusRes = await fetch(`${backendUrl}/onboarding/status`, {
            headers: { Authorization: `Bearer ${sessionData.session.access_token}` },
            signal: statusController.signal,
          });
          clearTimeout(statusTimeoutId);

          if (statusRes.ok) {
            const onboardingStatus = await statusRes.json();
            // Only honor consent_required when the env-level gate is on.
            if (consentGateEnabled && onboardingStatus?.consent_required) {
              const nextRoute = onboardingStatus?.has_persona
                ? (redirectParam !== '/onboarding' ? redirectParam : '/dashboard')
                : '/onboarding';
              finalRedirect = `/legal/accept?next=${encodeURIComponent(nextRoute)}`;
            } else if (onboardingStatus?.has_persona) {
              finalRedirect = redirectParam !== '/onboarding' ? redirectParam : '/dashboard';
            } else {
              finalRedirect = '/onboarding';
            }
          } else {
            // Status endpoint returned non-2xx. Don't loop the user silently.
            console.error('[Callback] /onboarding/status returned %d', statusRes.status);
            syncFailed = true;
          }
        }
      } catch (syncError) {
        console.error('[Callback] Error during sync/routing:', syncError);
        syncFailed = true;
      }
    }

    // Surface sync failures to the page so the user sees a banner instead
    // of silently looping through /onboarding which will refire the same call.
    const target = new URL(finalRedirect, publicOrigin);
    if (syncFailed) {
      target.searchParams.set('error', 'status_unavailable');
    }
    return NextResponse.redirect(target);
  } catch (err) {
    console.error('Callback error:', err);
    const loginUrl = new URL('/auth/login', publicOrigin);
    loginUrl.searchParams.set('error', 'callback_error');
    if (redirectParam && redirectParam !== '/onboarding') {
      loginUrl.searchParams.set('redirect', redirectParam);
    }
    return NextResponse.redirect(loginUrl);
  }
}