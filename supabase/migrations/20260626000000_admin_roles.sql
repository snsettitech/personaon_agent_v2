-- Admin Control Center: widen users.role to support staff roles.
--
-- The base schema (20260101_base_schema.sql) allowed only ('owner','viewer'),
-- but require_admin() in auth_guard.py already authorizes 'admin'/'support'.
-- That latent mismatch meant those roles could never actually be granted.
-- This closes it. Idempotent: DROP-then-ADD the CHECK constraint.

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_role_check;

ALTER TABLE public.users
    ADD CONSTRAINT users_role_check
        CHECK (role IN ('owner', 'admin', 'support', 'viewer'));
