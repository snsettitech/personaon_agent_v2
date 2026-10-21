import { redirect } from 'next/navigation';

// Signup is unified into /auth/login — one page handles both new and
// returning users via OTP (shouldCreateUser:true) or OAuth. Mirrors
// Linear/Vercel/Notion. This page just redirects so any existing
// links to /auth/signup continue to work. Query params (ref, utm_*)
// are forwarded so referral attribution from persona pages survives.
export default async function SignupPage({
    searchParams,
}: {
    searchParams: Promise<Record<string, string | string[] | undefined>>;
}): Promise<never> {
    const params = await searchParams;
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        const v = Array.isArray(value) ? value[0] : value;
        if (typeof v === 'string' && v) qs.set(key, v);
    }
    const suffix = qs.toString();
    redirect(suffix ? `/auth/login?${suffix}` : '/auth/login');
}
