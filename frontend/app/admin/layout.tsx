import { redirect } from 'next/navigation';
import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { AdminNav } from './AdminNav';

// Admin access: a @personaon.com email (employees), OR an explicitly-granted
// admin/support role (for non-domain staff). The broad 'owner' role does NOT
// grant admin access. Keep in sync with backend modules/auth_guard.py.
const ADMIN_EMAIL_DOMAIN = 'personaon.com';
const STAFF_ROLES = new Set(['admin', 'support']);

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // setAll called from a Server Component — safe to ignore
          }
        },
      },
    }
  );

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    redirect('/auth/login?redirect=/admin');
  }

  // ── Admin access check ────────────────────────────────────────────────
  // A @personaon.com email is admin (no DB read needed). Otherwise fall back
  // to an explicit admin/support role from the users table (RLS lets a user
  // read their own row).
  const email = (session.user.email || '').toLowerCase();
  let isStaff = email.endsWith('@' + ADMIN_EMAIL_DOMAIN);

  if (!isStaff) {
    const { data: userRow } = await supabase
      .from('users')
      .select('role')
      .eq('id', session.user.id)
      .maybeSingle();
    isStaff = STAFF_ROLES.has(userRow?.role || 'viewer');
  }

  if (!isStaff) {
    redirect('/dashboard');
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">PersonaOn Admin</h1>
            <p className="mt-1 text-sm text-slate-500">
              Platform analytics, user activity, and conversation monitoring
            </p>
          </div>
          <a href="/dashboard" className="text-sm text-slate-500 hover:text-slate-900">
            Back to App
          </a>
        </div>
        <AdminNav />
      </header>
      <main className="mx-auto max-w-7xl p-6">{children}</main>
    </div>
  );
}
