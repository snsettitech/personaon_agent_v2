import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

const ALLOWED_HOSTS = new Set([
  'personaon-web-czlsihxvra-uc.a.run.app',
  'personaon-web-837700257032.us-central1.run.app',
  'personaon.ai',
  'www.personaon.ai',
  'personaon.com',
  'www.personaon.com',
  'localhost:3000',
  '127.0.0.1:3000',
].filter(Boolean));

function getPublicOrigin(request: NextRequest): string {
  // Prefer explicit env var — always safe
  if (process.env.NEXT_PUBLIC_FRONTEND_URL) return process.env.NEXT_PUBLIC_FRONTEND_URL;
  // Only trust x-forwarded-host if it's in our allowlist
  const forwarded = request.headers.get('x-forwarded-host');
  if (forwarded && ALLOWED_HOSTS.has(forwarded)) {
    const proto = request.headers.get('x-forwarded-proto') || 'https';
    return `${proto}://${forwarded}`;
  }
  return new URL(request.url).origin;
}

// Next.js middleware — runs on every matched request.
// Refreshes Supabase session by calling getClaims() (NOT getSession()).
//
// CRITICAL: Use getClaims(), not getSession().
// getSession() reads the local JWT without server validation.
// getClaims() sends the JWT to Supabase for validation and rotation.
// Source: https://supabase.com/docs/guides/auth/server-side/nextjs
export async function proxy(request: NextRequest) {
  // Create a response object that we can mutate with Set-Cookie headers
  let supabaseResponse = NextResponse.next({ request });

  // E2E test bypass: allows Playwright tests to skip auth in non-production
  if (process.env.NODE_ENV !== 'production' && process.env.E2E_BYPASS_AUTH === '1') {
    return supabaseResponse;
  }

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          // Write cookies to both the request (for downstream server reads)
          // and the response (so the browser receives updated tokens)
          cookiesToSet.forEach(({ name, value }) => {
            request.cookies.set(name, value);
          });
          // Recreate response to carry all updated cookies
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) => {
            supabaseResponse.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  // Validate and refresh the session token.
  // getClaims() revalidates the JWT server-side — required for security.
  // Do NOT use getSession() here (does not revalidate token).
  const { data: claimsData } = await supabase.auth.getClaims();
  const isAuthenticated = !!claimsData?.claims;

  const { pathname } = request.nextUrl;

  const isAuthPage = pathname.startsWith('/auth');
  const isCallbackPage = pathname === '/auth/callback';
  const isLoginPage = pathname === '/auth/login';
  const isPublicPage = pathname === '/' || pathname.startsWith('/share/') || pathname.startsWith('/widget');
  const isDashboard = pathname.startsWith('/dashboard');
  const isOnboarding = pathname.startsWith('/onboarding');

  const publicOrigin = getPublicOrigin(request);

  // Unauthenticated user trying to access protected route → login
  if (!isAuthenticated && (isDashboard || isOnboarding)) {
    const redirectUrl = new URL('/auth/login', publicOrigin);
    redirectUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(redirectUrl);
  }

  // Authenticated user on auth pages (except callback and login) → dashboard
  // Callback must complete the PKCE flow; login allows error display.
  const hasErrorParam = request.nextUrl.searchParams.has('error');
  if (isAuthenticated && isAuthPage && !isCallbackPage && !isLoginPage && !hasErrorParam) {
    return NextResponse.redirect(new URL('/dashboard', publicOrigin));
  }

  // Authenticated user on landing page → dashboard
  if (isAuthenticated && pathname === '/') {
    return NextResponse.redirect(new URL('/dashboard', publicOrigin));
  }

  // Allow widget pages to be embedded in iframes on any domain
  if (pathname.startsWith('/widget')) {
    supabaseResponse.headers.set('Content-Security-Policy', 'frame-ancestors *');
    supabaseResponse.headers.delete('X-Frame-Options');
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder (images, icons, etc.)
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
