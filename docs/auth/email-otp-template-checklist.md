# Email OTP Template Checklist

PersonaOn supports two email sign-in paths:

- one-time PIN entry in the app
- magic-link callback back into the app

Supabase controls which values appear in the email. To keep the Electron login page usable, the email template must include the PIN token and the callback URL.

## Supabase Template Requirements

In Supabase Auth email templates, include:

- `{{ .Token }}` for the one-time PIN shown in PersonaOn.
- `{{ .ConfirmationURL }}` for the magic link fallback.

If the template only includes `{{ .ConfirmationURL }}`, users will only see a magic link and cannot use the PIN field even though the app can verify a PIN.

## Redirect Requirements

Allow these redirect URLs in Supabase Auth URL configuration:

- `personaon://auth/callback`
- `personaon://auth/callback?redirect=%2Fdashboard`
- the configured web auth callback URL for hosted web login

The Electron app passes `emailRedirectTo` when requesting email OTP. If Supabase sends a magic link, it should return to `personaon://auth/callback` and complete sign-in in the desktop app.

## Manual Test

1. Open the Electron sign-in page.
2. Enter an email and click `Send PIN`.
3. Confirm the email contains a visible numeric token rendered from `{{ .Token }}`.
4. Enter the token in PersonaOn and verify sign-in completes.
5. Request another email and click the magic link.
6. Confirm the app opens/focuses and lands on the requested redirect path.
