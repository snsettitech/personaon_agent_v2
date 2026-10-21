# PersonaOn API — Backend

FastAPI + Google ADK backend for PersonaOn professional identity (Passport), ingestion, grounded chat, and workers.


## Services

| Service | Cloud Run (typical) | Entry |
|---------|---------------------|-------|
| API | `personaon-api` | `main.py` |
| Worker | `personaon-worker` | worker entry (`worker.py` / graph_outbox poller) |

## Architecture notes

- **Routers:** many modules under `routers/` (auth, onboarding, chat, profile, public profile, imports, sources, knowledge, meetings, voice, leads, analytics, …). Sprint 1 inventory (PON-4) should publish the live list — do not trust older “12 routers” counts.
- **Retrieval:** **pgvector in Supabase** via `adk_core/services/vector_store.py`. Pinecone is legacy; do not reintroduce Pinecone assumptions.
- **Jobs:** `modules/graph_outbox.py` + worker dispatch — preferred for long work (not `asyncio.create_task` on Cloud Run).
- **Auth:** ownership checks on twin/profile paths (`verify_twin_ownership` / `verify_owner`).
- **Identity migration:** new canonical claims model projects into existing public profile JSON — [ADR-001](../docs/architecture/adr/ADR-001-canonical-professional-profile.md).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill values
uvicorn main:app --reload --port 8000
```

## Required env (representative)

```text
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
GOOGLE_API_KEY=...
# Embeddings / vector: per current vector_store + Supabase config
# Do not require PINECONE_* for new work
```

See `.env.example` for the full set used in staging/production.

## Testing & lint

```bash
ruff check .
mypy . --ignore-missing-imports
pytest tests/ -x -q
```

## Deployment

Push to `main` triggers GitHub Actions → GCP Cloud Run.  
Migrations live in `supabase/migrations/`.

## Coding standards

[CLAUDE.md](../CLAUDE.md) — logging (no `print`), Pydantic envelopes, ownership checks, graph_outbox handler contracts.
