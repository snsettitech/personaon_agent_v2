-- Admin control center: let a signed-in user read their OWN users row.
--
-- public.users has RLS enabled but shipped with no policies, so any read under a
-- user session (anon key + user JWT) was denied. The admin layout
-- (frontend/app/admin/layout.tsx) reads users.role under the user's session to
-- gate access, so the missing policy made every admin bounce to /dashboard.
-- Backend is unaffected (service-role key bypasses RLS).
--
-- Idempotent: DROP-then-CREATE.

DROP POLICY IF EXISTS users_self_select ON public.users;
CREATE POLICY users_self_select ON public.users
    FOR SELECT USING ((SELECT auth.uid()) = id);
