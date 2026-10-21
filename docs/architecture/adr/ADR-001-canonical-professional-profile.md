# ADR-001 — Canonical professional profile + presentation projection

| Field | Value |
|-------|-------|
| **Status** | **Accepted** — Approach B (thin stack). Evidence pack [PON7_SCHEMA_DESIGN.md](../../product/PON7_SCHEMA_DESIGN.md). Staging DDL next; prod DDL still gated. |
| **Date** | 2026-09-23 |
| **Updated** | 2026-09-23 — founder approved Approach B |
| **Approved by** | Founder / architectural reviewer (PO-DEC-008) — 2026-09-23 |
| **Deciders** | Architectural reviewer (required) · Founder · Pod A |
| **Supersedes** | July PRD “single JSON profile document as persistent page-content model” as *sole* truth |
| **Jira** | PON-7, PON-8, PON-9, PON-10, PON-11 |
| **Decision** | PO-DEC-006 |

---

## Context

The live product stores much of the public page in `twins.settings.public_profile` (JSON). That model is efficient for themes and shells but is a weak auditable identity store: AI writes and form edits can blur “presentation” vs “truth,” and provenance is uneven.

Rewriting every page shell in Sprint 1 is unnecessary risk. The team needs a **thin vertical slice**: structured claims with review, while existing `/p` themes keep working.

## Decision

1. Introduce a **canonical professional-context** model (see entities below).
2. Keep `settings.public_profile` (or successor) as a **generated projection** during migration.
3. Writes to canonical approved fields refresh the projection.
4. Theme, accent, layout, and selected presentation toggles remain in the presentation document.
5. Stop adding new canonical business facts only into arbitrary JSON.
6. Keep internal DB name `twin` for now; user-facing copy uses profile / Passport / identity.

### Initial entities

| Entity | Role |
|--------|------|
| `professional_profiles` | One owner-controlled professional identity |
| `profile_claims` | Structured facts with state: proposed / approved / rejected / superseded |
| `claim_evidence` | Links claims → sources / excerpts / verification |
| `profile_preferences` | Career/comms preferences with visibility + timestamps |
| `profile_views` | Named scoped projections (public, recruiter, FutureStack, …) |
| `access_grants` | Consumer, scopes, purpose, status, expiry |
| `profile_events` | Correction, publish, access, reuse audit |
| Existing `sources` / chunks | Retained where suitable |

### Claim states

```text
proposed → approved
proposed → rejected
approved → superseded (on correction or replacement)
```

Only **approved** (in-scope) claims may enter a public/link projection.

### Relationship to existing claim stores (added 2026-09-23 review)

- **`profile_claims` is the only canonical, owner-approvable fact store** for the Passport vertical slice.
- `person_claims`, `research_claims`, graph-memory claims, `memory_candidates`, and `owner_memory` are **inputs / evidence**, never canonical truth. They may be mapped into `profile_claims` with state `proposed`; they must not feed the public projection directly.
- **PON-7 decision (2026-09-23):** **(b)** freeze `person_claims` as non-canonical; new writes go to `profile_claims` only — [PON7_SCHEMA_DESIGN.md](../../product/PON7_SCHEMA_DESIGN.md) Approach B approved.
- **New migrations go in `supabase/migrations/` only.** Inventory which files under `backend/database/migrations/` are applied in production during PON-4; do not silently invent a second source of schema truth.
- Writers of `settings.public_profile` that set **factual** fields (onboarding, import_routes, persona_materializer / persona_repository, `update_persona` tool) must route through **proposed claims** by end of Sprint 1. Presentation keys (theme_id, accent, layout, pinned_questions) stay direct-write.
- Until the claims path exists, keep **`AGENT_EDITS_ENABLED=false`** in production (and staging unless deliberately testing Studio edits). Set the Cloud Run env explicitly.

### Retrieval privacy (PON-11)

- Non-owner chat surfaces (`visitor`, `widget_lead`, `public_lead`, and plain public/widget) MUST retrieve only `privacy_level='public'` chunks.
- Owner / assistant surfaces may retrieve all tiers.
- Implemented in `adk_core.services.agent_service` via `_retrieval_tiers_for_surface`.

### Field ownership map (precondition for PON-10)

Draft during PON-4 / PON-7; **required before merging the projection writer**.

| Kind | Examples | Owner system |
|------|----------|--------------|
| Canonical facts | name, headline, education, experience, skills, projects | `profile_claims` (approved) |
| Preferences | job-search intent, location, rate bands | `profile_preferences` |
| Presentation | theme_id, accent, layout, section order, pinned Qs | `settings.public_profile` (direct) |
| Projection output | bio/summary text rendered on `/p` | Generated from approved claims + presentation |

## Consequences

- Pod A owns migrations and adapters; Pod B owns review UX.
- Projection must be idempotent, versioned, and observable.
- Legacy pages keep working; field ownership map is a merge gate for PON-10.
- No mass `twin` → `profile` rename in Sprint 1.
- Public answers may become thinner where content was ingested as private — re-tier or re-ingest as needed.

## Alternatives considered

| Option | Why rejected |
|--------|--------------|
| Rewrite all shells to sections/blocks now | High risk, delays activation proof |
| Keep JSON as sole truth | Fails auditability and FutureStack contracts |
| Full graph-memory redesign first | Too broad for six-person Sprint 1 |
| Sixth claim table alongside `person_claims` without freeze | Guarantees dual sources of truth |

## Rollback

- Feature-flag projection writer; fall back to last known presentation JSON.
- Do not delete claim history on rollback.
- Migrations reversible or have approved recovery plan.
- Retrieval tier filter can be reverted by restoring `allowed_tiers=None` for visitor surfaces (not recommended).

## Follow-ups

- Completeness scoring rules for `core_profile_completed`.
- ~~Confirm production: whether `person_claims` exists; `AGENT_EDITS_ENABLED` value; lead-capture keep vs hide for Sprint 1 IA.~~  
  **Resolved 2026-09-23:** `AGENT_EDITS_ENABLED=false` on prod; lead-capture **hide/flag** (PO-DEC-009); `person_claims` / `profile_claims` not present in connected DB probe — confirm again on prod service-role before PON-7 DDL ([PON4_CAPABILITY_INVENTORY.md](../../product/PON4_CAPABILITY_INVENTORY.md)).
- Schema merge blocked until [SPRINT_1_GATE.md](../../engineering/SPRINT_1_GATE.md) + architectural reviewer (PO-DEC-008).
