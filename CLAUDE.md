# PersonaOn — Coding Standards

This file defines project-specific standards. These extend the global rules in
`~/.claude/rules/` and take precedence where they conflict.

---

## Stack

- **Backend**: FastAPI + Google ADK + Supabase + pgvector (Python 3.12)
- **Frontend**: Next.js 16 App Router + TypeScript + Tailwind (React 18)
- **Workers**: graph_outbox async job pattern (Supabase → worker poll)
- **AI**: Gemini via Google ADK, Firecrawl for web extraction, ElevenLabs for voice

---

## Python — Backend

### File size limits
- Routers: **300 lines max**. Split by sub-domain into packages:
  - `routers/twins/` not 6 flat `twins_*.py` files
  - `routers/auth/` not one 1400-line `auth.py`
- Modules: **400 lines max**. At the limit, split by responsibility.
- ADK agents: one agent per file, no multi-agent files.

### Logging — never use print()
```python
# WRONG
print(f"[Auth] user {user_id} logged in")

# RIGHT
import logging
logger = logging.getLogger(__name__)
logger.info("[Auth] user logged in user_id=%s", user_id)
```
Every module must have `logger = logging.getLogger(__name__)` at the top.
`print()` is only allowed in one-off scripts under `backend/scripts/`.

### Error handling — never swallow exceptions
```python
# WRONG
except Exception:
    return None

# WRONG
except Exception as exc:
    pass

# RIGHT
except Exception as exc:
    logger.exception("[Module] operation failed context=%s", context)
    raise  # or return structured error

# RIGHT for background jobs (graph_outbox handlers)
except Exception as exc:
    logger.exception("[Worker] job failed job_id=%s", job_id)
    return False  # triggers _mark_job_failed, retries automatically
```

### Type annotations — Pydantic over Dict[str, Any]
```python
# WRONG — at internal service boundaries
def process(data: Dict[str, Any]) -> Dict[str, Any]: ...

# RIGHT — define the shape
class ProcessInput(BaseModel):
    twin_id: str
    profile: ProfileData

def process(data: ProcessInput) -> ProcessResult: ...
```
`Dict[str, Any]` is only allowed at **Supabase raw response boundaries**
(the `.data` coming back from `.execute()`).

### API response shape — consistent envelope
All endpoints return the same shape:
```python
# Success
{"status": "ok", "data": {...}}

# Error — raise HTTPException, never return {"error": "..."}
raise HTTPException(status_code=404, detail="Twin not found")
```
Never return plain dicts, never return `{}` on success without a `data` key.

### Auth — ownership checks are mandatory
Every endpoint that reads or writes twin data must call:
```python
verify_twin_ownership(twin_id, user)   # raises 403 if not owner
# or
verify_owner(user)                     # raises 401 if not authenticated
```
No exceptions. Never access a twin by ID without an ownership check.

### graph_outbox handlers
- Always return `True` (success) or `False` (failure, triggers retry)
- Return `None` only if the handler marks the job itself (e.g. stores result in payload)
- Log before and after with `job_id` and `operation`
- Never let an exception propagate — catch, log, return `False`

**File:** `backend/modules/graph_outbox.py` — `GraphOutbox.submit()` signature:
`submit(tenant_id, twin_id, operation, idempotency_key, payload, priority=0, correlation_id=None, scope_id=None, creator_id=None, next_attempt_after=None) -> str`

**Idempotency:** Submitting with the same `(tenant_id, scope_id|twin_id, idempotency_key)` for a job already in `pending|processing|completed` returns the existing job_id silently — no error, no duplicate.

**Adding a new operation:**
1. Add the enum value to `GraphOperationType` in `backend/modules/graph_outbox.py`
2. Add a new branch to `_dispatch()` in `backend/modules/graph_outbox_worker.py`
3. Add the string to the `graph_outbox_operation_check` CHECK constraint via DROP-then-ADD migration (include the full prior list — see `20260601000100_graph_outbox_ops_link_contacts.sql`)

---

## TypeScript — Frontend

### Design system first — OBSOLETE

(This entire section governed UI composition in `app/web` + `app/desktop` via `@personaon/design-system` — archived 2026-07-03, see tag `archive/app-web-desktop-2026-07-03`. It never applied to `frontend/`, which has zero dependency on `packages/design-system` and uses raw Tailwind/HTML directly — that remains true and unaffected. `scripts/lint-ui-boundaries.mjs` and the `lint:ui-boundaries` npm script were deleted in a follow-up cleanup commit (`d4261bf0`) — they no longer exist. However, `scripts/lint-ui-boundaries.sh` (a pre-existing, still-tracked duplicate from before the `.mjs` version, commit `e41429e2`) was **not** touched by that cleanup: it still runs `rg ... app/web app/desktop` directly and is now dead/broken the same way the `.mjs` was, since those directories no longer exist. It is not wired into any script or CI job today, but if anyone adds it to one, it will fail to find its target paths. Delete it in a future cleanup pass rather than assuming it still works.)

### Web and desktop app runtime — OBSOLETE

(app/web + app/desktop archived 2026-07-03 — this was a pre-pivot Granola-style meeting-notes product, unrelated to PersonaOn's three-pillar product definition; see tag archive/app-web-desktop-2026-07-03 for the removed code. This guidance no longer applies.)

### Desktop app — API routing — OBSOLETE

(app/web + app/desktop archived 2026-07-03 — this was a pre-pivot Granola-style meeting-notes product, unrelated to PersonaOn's three-pillar product definition; see tag archive/app-web-desktop-2026-07-03 for the removed code. This guidance no longer applies.)

### No `any` types
```typescript
// WRONG
const data: any = await res.json();
function process(input: any): any { ... }

// RIGHT
const data: TwinResponse = await res.json();
function process(input: ProcessInput): ProcessResult { ... }
```
`as unknown as T` is allowed only at raw fetch boundaries with a comment explaining why.

### No console.log in production paths
```typescript
// WRONG — anywhere in app/, lib/, components/
console.log("twin loaded", twin);

// RIGHT — use analytics for events, remove debug logs before commit
analytics.capture("twin_loaded", { twin_id: twin.id });
```
`console.error()` is allowed for genuine error logging.
`console.log()` only in `scripts/` or behind `process.env.NODE_ENV === "development"`.

### File size limits
- Page files (`app/**/page.tsx`): **400 lines max**
  - Extract each screen/step into its own component under `components/`
  - State that belongs to a sub-screen lives in that component
- Components: **200 lines max**
- Hooks: **150 lines max** — split by concern if larger

### Error handling in async functions
```typescript
// WRONG — swallowed
try {
  await doThing();
} catch { /* */ }

// RIGHT — log or surface to user
try {
  await doThing();
} catch (err) {
  const msg = err instanceof Error ? err.message : "Unknown error";
  showToast(msg, "error");  // or logger, or analytics
}
```

### Auth fetch
- **`frontend/`** (the live product): use `authFetchStandalone()` from `@/lib/hooks/useAuthFetch`. Never construct `Authorization` headers manually. (This bullet was previously mislabeled "app/web" — the file lives in and matters for `frontend/`, the actual live app; unrelated to today's archive.)
- ~~Desktop renderer (`app/desktop/src/renderer`): use `adapter.api.request()` from the `RuntimeAdapter`~~ — OBSOLETE, `app/desktop` archived 2026-07-03, see tag `archive/app-web-desktop-2026-07-03`.

---

## Migrations & Schema

- Migrations live in `supabase/migrations/`. **Do not** edit `supabase/_migrations_HOLD/` — that's a local-state workaround; never `git add -A` it.
- New tables must include: `id uuid PRIMARY KEY DEFAULT gen_random_uuid()`, `tenant_id uuid NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.
- **RLS pattern (single-tenant convention):** `tenant_id` stores the Supabase Auth UID directly. Policies use:
  ```sql
  USING ((SELECT auth.uid()) = tenant_id)
  ```
  The `(SELECT ...)` wrapper avoids per-row re-evaluation. Also add a service-role policy: `USING (auth.role() = 'service_role')`.
- **Index naming:** `idx_{table_abbrev}_{column}` where the abbrev is 2-4 chars. Two new tables with colliding abbrevs (e.g. `meeting_commitments` + `memory_candidates`) must use different prefixes (`mcommit`, `mcand`).
- **Function overloads:** Always `DROP FUNCTION IF EXISTS ... CASCADE` before `CREATE OR REPLACE` — the lint catches this (`scripts/lint_migrations.py`).

---

## Testing

### Backend
Canonical mock pattern: import from `backend/tests/_supabase_mock.py`. Do not duplicate the `_fluent()` / `_result()` helpers in new tests.

### Frontend — OBSOLETE

(Canonical pattern was `packages/app-shell/src/api/recordings.share.test.tsx`, mocking the `RuntimeAdapter` per-test — that abstraction belonged to `app/web`/`packages/app-shell`, archived 2026-07-03, see tag `archive/app-web-desktop-2026-07-03`. `frontend/` has its own `bun:test` test files — e.g. `frontend/lib/persona-themes/__tests__/*.test.ts` — but no documented canonical mocking pattern yet; this needs writing fresh, not inherited from the archived one.)

---

## Feature Flags — OBSOLETE

(This entire section — `packages/core/src/flags/index.ts`'s `FlagName`/`FLAG_DEFAULTS`, `useFlag`/`useResolvedFlag`, and all 4 example flags `commitments_v1`/`memory_review_v1`/`command_palette_v1`/`preview_mode_v1` — described `app/web`'s flag system, archived 2026-07-03, see tag `archive/app-web-desktop-2026-07-03`. `frontend/` has its own, different, unrelated feature-flag mechanism — `frontend/lib/features/FeatureFlags.tsx` + `runtimeFlags.ts`, a React-context-based system — not yet documented here.)

---

## OpenAPI — OBSOLETE

(`bun run gen:api` generated `packages/core/src/types/api.generated.ts` from a committed `openapi.json` snapshot, verified fresh by the `bun-workspace-typecheck` CI job — both the package and that CI job are gone as of the 2026-07-03 archive, see tag `archive/app-web-desktop-2026-07-03`. `frontend/` has no generated OpenAPI client at all — it calls the backend with hand-written fetch calls and manually maintained types. Investigation during the archive decision also found this generated client had drifted ~35 days / ~109 endpoints behind the live backend before removal, with no CI guardrail able to catch that kind of drift — worth keeping in mind if a generated-client approach is ever reintroduced for `frontend/`.)

---

## Security — Non-Negotiables

These are checked before every commit:

- [ ] No hardcoded API keys, tokens, or passwords in source code
- [ ] All user inputs validated (Pydantic on backend, Zod on frontend)
- [ ] Every twin/source/conversation endpoint has ownership check
- [ ] No `eval()`, `exec()`, or dynamic SQL strings
- [ ] File upload endpoints enforce size and MIME type limits
- [ ] Error messages do not leak internal paths, user IDs, or stack traces to clients

---

## Git Workflow

Commit types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

```
feat: add background Firecrawl extraction during onboarding

<body explaining why, not what>
```

- One concern per commit
- Never commit `.env`, `*.db`, `*.key`, or credentials
- Branch naming: `feat/short-description`, `fix/short-description`

---

## Linting & Type Checking

### Backend (run before committing)
```bash
cd backend
ruff check .          # style + unused imports + bare except
mypy . --ignore-missing-imports  # type errors
pytest tests/ -x -q   # fail fast on first broken test
```

### Frontend (run before committing)
```bash
cd frontend
tsc --noEmit          # type errors
eslint .              # console.log, any types, hooks rules
```

CI enforces these — a failing lint blocks merge.

---

## What NOT to Do

- Do not add `# type: ignore` without a comment explaining why
- Do not add `eslint-disable` without a comment explaining why
- Do not use `asyncio.create_task()` on Cloud Run (use graph_outbox instead)
- Do not call Gemini/ADK directly from a request handler — use workers for long operations
- Do not add backwards-compatibility shims for removed code — delete cleanly
- Do not use `FunctionCallingConfig(mode="ANY")` in ADK agents — causes infinite loops
- ~~Do not set `VITE_API_ORIGIN` to a FastAPI port... / Do not add `fetch()` calls with hardcoded backend URLs in `app/desktop/src/renderer/`...~~ — OBSOLETE (app/web + app/desktop archived 2026-07-03 — this was a pre-pivot Granola-style meeting-notes product, unrelated to PersonaOn's three-pillar product definition; see tag archive/app-web-desktop-2026-07-03 for the removed code. This guidance no longer applies.)

---

## Architecture Reference (merged from CODEBASE.md, 2026-07-03)

CODEBASE.md (last verified 2026-04-05) was folded into this file and deleted per repo-hygiene cleanup.
Its router list, page list, module/component status tables ("ACTIVE/USEFUL-WAITING/DEAD"), and deletion
history were dropped as stale — spot-checked against the current tree: the backend now has ~57 router
files (not the 28 listed), and the ADK core no longer has a `pinecone_service.py` (confirms the vector
store section below). Only the parts re-verified against current code are kept here.

### System shape (verify — may be stale on specific Cloud Run service names/URLs)

```text
Next.js App Router frontend (frontend/ — app/web archived 2026-07-03, see tag archive/app-web-desktop-2026-07-03)
        │ HTTPS / SSE
FastAPI backend (backend/) — routers/ + adk_core/ (Google ADK agents)
        │            │             │
   Supabase      pgvector      Firecrawl API
   (Postgres,   (vector search,  (web research /
   RLS, auth)    see below)      profile extraction)
        │
Worker (graph_outbox pattern — Supabase table poll, see graph_outbox section above)
```

LLM providers: Gemini via Google ADK (chat, interview, enrichment), Firecrawl for extraction,
ElevenLabs for voice. OpenAI usage for auxiliary tasks noted in the old doc is unverified — treat as
**(verify — may be stale)**.

### Vector store — CORRECTED, not carried from CODEBASE.md as-is

CODEBASE.md described a Pinecone-backed vector store (`digitalminds` index, 1024d integrated embeddings,
namespace `twin_{twin_id}`). That is **no longer accurate**: `adk_core/services/pinecone_service.py` is
gone, replaced by `adk_core/services/vector_store.py` (functions `search`, `search_global`,
`search_meetings`, `upsert_text_chunks`, `upsert_faq` — same call shape, different backend), and there is
a migration (`backend/database/migrations/migration_cleanup_legacy_pinecone_verified_vectors.sql`) that
cleans up legacy Pinecone-era vectors. Current vector storage is **pgvector inside Supabase**, not
Pinecone (consistent with prior session memory `feedback_pgvector_not_pinecone.md`). Do not reintroduce
Pinecone-specific assumptions (index name, integrated-embedding namespace scheme) without checking
`vector_store.py` first.

### `twins` table shape — re-verified against `supabase/migrations/20260101_base_schema.sql`

```text
twins:
  - id, tenant_id (FK → tenants, NOT NULL), creator_id, status, settings JSONB
  - status has a CHECK constraint (values evolve — check the migration for the current list,
    do not assume the 2026-04 list of draft|ingesting|claims_ready|persona_built|active|archived still holds)
  - settings JSONB default '{}' — historically holds persona_profile, public_profile,
    auto_create_state, identity_verified, identity_source (verify — may be stale on exact key names,
    this branch has had Persona Studio / Home v1 / public lead capture work since April that may have
    added or renamed settings keys)
  - unique index on (tenant_id, settings->>'owner_user_id') where not deleted
  - index on (tenant_id, status, created_at DESC)
```

### Security hardening applied (verify — may be stale, but these were real fixes as of 2026-04 and unlikely reverted)

| Area | Fix |
| ---- | --- |
| Firecrawl prompt | Sanitize user inputs before injecting into extraction prompts (strip newlines, cap length) |
| Chat `mode_override` | Validated against an explicit allowlist, not passed through raw |
| ADK Runner cache | Never mutated — per-request context passed as a Content part, not baked into the cached runner |
| Supabase auth | Anon key only for public auth calls; service key never falls through to client-facing paths |
| JWT expiry | `verify_exp=True` only — no separate incorrect `iat` age check |
| Error messages | Supabase errors logged server-side; generic message returned to client |
| Logging | No bare `print()` in auth/guard code — `logging` module used throughout (this is now also a hard project rule, see Python section above) |

---

<!-- gitnexus:start -->
