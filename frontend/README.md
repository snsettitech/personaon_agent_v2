# PersonaOn Frontend

Next.js 16 App Router app for PersonaOn — onboarding, owner dashboard, public professional pages (`/p/{handle}`), and related surfaces.

**This is the live web app.** There is no active `app/web` or `packages/core` workspace in this repository (archived 2026-07-03).


## Local run

```bash
cd frontend
npm ci
copy .env.example .env.local   # Windows
npm run dev
```

## Important paths

- `app/` — routes (onboarding, dashboard, `/p`, auth, admin, …)
- `lib/` — API helpers, auth (`authFetchStandalone`), feature flags
- `components/` — UI
- `tests/` — unit / e2e where present

## Near-term product focus

Sprint 1–2 prioritize: import → claim review → projection → share.  
Meetings, leads, marketplace, voice: hide or feature-flag per surface classification — not primary IA for early-career Passport users.

## Lint / types

```bash
npx tsc --noEmit
npx eslint .
```
