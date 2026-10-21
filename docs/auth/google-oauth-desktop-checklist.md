# Google OAuth Checklist For PersonaOn Desktop

Date: 2026-05-29

## Google Cloud Console

- Authorized redirect URI must include the Supabase callback:
  - `https://rvgcqtcbfaxatcedlezi.supabase.co/auth/v1/callback`

Google should not be configured with the custom desktop protocol directly. Supabase receives the Google callback first, then redirects to PersonaOn.

## Supabase Auth

- Google provider must be enabled.
- Redirect URL allowlist must include:
  - `personaon://auth/callback`
  - local web callback URL, for example `http://localhost:3002/auth/callback`
  - production web callback URL, for example `https://<production-domain>/auth/callback`

## Desktop Flow

1. Electron calls Supabase OAuth with PKCE and `redirect_to=personaon://auth/callback?redirect=/dashboard`.
2. The system browser opens the Supabase authorize URL.
3. Google redirects back to Supabase.
4. Supabase redirects to `personaon://auth/callback` with a code or provider error.
5. Electron exchanges the code for a session, or routes the provider error back into the shared login screen.

## Failure Symptoms

- `redirect_uri_mismatch`: Google Cloud Console is missing the Supabase callback URL.
- Browser returns to Supabase but not Electron: Supabase redirect allowlist is missing `personaon://auth/callback`.
- Electron focuses but remains signed out: inspect the login error message and desktop logs for `[desktop-auth] callback exchange failed`.
