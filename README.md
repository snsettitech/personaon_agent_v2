# PersonaOn Agent v2

PersonaOn is a professional-identity platform: a person's approved profile facts power an AI
persona that can chat, publish a public page, and capture leads.

The repository ships without credentials or deployment configuration. To run it locally you
need your own Supabase project and Gemini API key.

## Repository structure

```text
frontend/   Next.js 16 App Router + TypeScript + Tailwind (port 3000)
backend/    FastAPI + Google ADK (Gemini), Python 3.12 (port 8000)
            also hosts the graph_outbox background worker
supabase/   Postgres migrations (schema, RLS, pgvector)
docs/       Architecture notes and auth setup checklists
scripts/    Dev helpers and migration linting
```

## Prerequisites

- Python 3.12, Node 20+, and npm
- A Supabase project (the free tier is fine), or the Supabase CLI for a local stack
- A Gemini API key from https://aistudio.google.com/apikey

## Setup

1. **Database.** Apply the migrations to your own Supabase project:
   ```bash
   supabase link --project-ref <your-project-ref>
   supabase db push
   ```
   Or run `supabase start` for a local stack at `http://127.0.0.1:54321`.

2. **Backend.**
   ```bash
   cd backend
   cp .env.example .env
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```
   The API refuses to start unless these are set in `.env`:

   | Variable | Value |
   |---|---|
   | `SUPABASE_URL`, `SUPABASE_KEY` (anon), `SUPABASE_SERVICE_KEY` | From your Supabase project's API settings |
   | `PGVECTOR_DATABASE_URL` | Your Supabase Postgres connection string, direct port 5432 |
   | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Your Gemini key (same value for both) |
   | `JWT_SECRET` | Any long random string |
   | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Placeholders such as `sk_test_x` and `whsec_x` are fine unless you work on billing |

   Check it with `curl http://localhost:8000/health`, which reports each dependency's status.
   Tests: `pip install pytest pytest-asyncio pytest-xdist pytest-timeout && pytest tests -q -n auto`.
   (`requirements-dev.txt` also pulls in `arize-phoenix`, which doesn't install on Windows. You don't need it.)

3. **Frontend.**
   ```bash
   cd frontend
   cp .env.example .env.local  # fill in NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
   npm ci
   npm run dev
   ```

Open http://localhost:3000. The frontend talks to the backend at `http://localhost:8000` by default.

## Checks

```bash
cd backend && pytest tests -q -n auto
cd frontend && npx tsc --noEmit && npx next build
```

## Coding standards

See [CLAUDE.md](CLAUDE.md) for Python/TypeScript conventions, ownership checks, and the
graph_outbox job pattern.

Optional integrations (ElevenLabs voice, Firecrawl, Recall meeting bots, Stripe, PostHog,
Resend email) stay off unless you add their keys. The core profile and chat flow needs only
Supabase and Gemini.
