"""One-off, idempotent backfill: seed ``settings.public_profile.public_faq``.

Seeds the owner-approved public FAQ block (the AEO surface consumed by
``build_public_profile_pack`` and re-whitelisted by
``redact_public_profile_pack_for_public_response``) for public twins that do not
yet have one.

SAFE-BY-CONSTRUCTION SOURCE
---------------------------
The ONLY source is the ``verified_qna`` table, filtered to rows the owner has
explicitly marked ``visibility='public'`` AND ``is_active=true``. These are
owner-authored, owner-published question/answer pairs — the exact same trust
level the ``public_faq`` field expects.

This script NEVER reads ``public_response_seeds`` / ``response_seeds`` /
``prepared_question_answers`` / ``suggested_questions`` / ``pinned_questions``
or any auto-generated / answerless / already-redacted source. Those are
machine-derived and must never be published as owner-approved FAQ.

Each surviving pair is run through the SAME cleaners the public boundary uses
(``_clean_text`` on the question, ``_strip_inline_source_refs`` on the answer),
so the seeded rows survive the redactor's re-sanitization unchanged and no
inline citation ref can leak to an anonymous visitor.

IDEMPOTENCY / WRITE-GUARD
-------------------------
A twin is only written when ``settings.public_profile.public_faq`` is currently
ABSENT or EMPTY. An owner's existing, non-empty ``public_faq`` is NEVER
overwritten. Re-running the script is a no-op for already-seeded twins.

USAGE
-----
Dry-run (default — prints what WOULD be written, no DB writes)::

    python -m scripts.backfill_public_faq
    python -m scripts.backfill_public_faq --twin-id <uuid>

Apply (actually writes)::

    python -m scripts.backfill_public_faq --apply
    python -m scripts.backfill_public_faq --apply --limit 200

``print()`` is used deliberately: this is a one-off script under
``backend/scripts/`` (allowed per CLAUDE.md).
"""
from __future__ import annotations

import argparse
import logging
import re
from typing import Any

# NOTE: modules.observability.supabase is the SERVICE-role client
# (SUPABASE_SERVICE_KEY) — required to read every tenant's verified_qna and
# write back the merged settings JSON. Same client the sibling backfills use.
from modules.observability import supabase
from modules.public_profile_pack import _clean_text, _strip_inline_source_refs
from modules.share_links import is_publicly_accessible_twin_record

logger = logging.getLogger(__name__)

# Public FAQ blocks are curated and short; cap so a twin with dozens of public
# QnA rows still yields a tight, page-friendly list (mirrors the public seed cap).
MAX_FAQ_ENTRIES = 6

# Only the columns needed to run the public-access gate + read the settings JSON.
# is_publicly_accessible_twin_record needs status + settings; name feeds the
# marketplace-completeness check inside normalize_public_profile.
TWIN_SELECT = "id, name, settings, status"


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _handle_of(twin: dict[str, Any]) -> str:
    settings = twin.get("settings")
    if isinstance(settings, dict):
        return str(settings.get("handle") or "").strip().lower()
    return ""


def _norm_question(question: str) -> str:
    """Normalized dedupe key: lowercased, whitespace-collapsed."""
    return re.sub(r"\s+", " ", question or "").strip().lower()


def _load_twins(*, twin_id: str | None, limit: int) -> list[dict[str, Any]]:
    """Load candidate twins. Single twin when --twin-id is given, else a bounded
    scan (mirrors the full-table scan handles_public.py uses to enumerate public
    twins — no handle/status index exists at current scale)."""
    query = supabase.table("twins").select(TWIN_SELECT)
    if twin_id:
        query = query.eq("id", twin_id)
    else:
        query = query.limit(limit)
    response = query.execute()
    return list(response.data or [])


def _fetch_public_active_qna(twin_id: str) -> list[dict[str, Any]]:
    """Owner-published QnA for a twin: visibility='public' AND is_active=true.

    Mirrors ``verified_qna.list_verified_qna(twin_id, visibility='public')`` but
    stays synchronous for this batch script. select('*') matches the module's own
    fetch helpers and avoids per-column existence assumptions at the Supabase
    boundary. This is the ONLY source of FAQ content — no auto-generated tables.
    """
    def _run(order: bool):
        q = (
            supabase.table("verified_qna")
            .select("*")
            .eq("twin_id", twin_id)
            .eq("visibility", "public")
            .eq("is_active", True)
        )
        if order:
            # Deterministic pick of the first MAX_FAQ_ENTRIES on the initial seed.
            q = q.order("created_at", desc=False)
        return q.execute()

    try:
        response = _run(order=True)
    except Exception as exc:
        # created_at ordering is best-effort; fall back to unordered rather than
        # skip the twin entirely.
        logger.warning(
            "[backfill_public_faq] created_at order failed twin_id=%s falling back exc=%s",
            twin_id,
            exc,
        )
        response = _run(order=False)
    return list(response.data or [])


def _build_faq_entries(qna_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map public QnA rows to the leak-safe ``{question, answer}`` FAQ shape.

    Applies the SAME cleaners as the public boundary's ``_sanitize_public_faq``:
      - ``_clean_text`` on the question,
      - ``_strip_inline_source_refs`` on the answer (drops inline ``[<uuid>]`` refs),
      - drop any row whose question OR answer is blank after cleaning,
      - dedupe by normalized (lowercased, whitespace-collapsed) question,
      - cap at MAX_FAQ_ENTRIES.
    """
    faq: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in qna_rows:
        if not isinstance(row, dict):
            continue
        question = _clean_text(row.get("question"))
        answer = _strip_inline_source_refs(row.get("answer"))
        if not question or not answer:
            continue
        key = _norm_question(question)
        if not key or key in seen:
            continue
        seen.add(key)
        faq.append({"question": question, "answer": answer})
        if len(faq) >= MAX_FAQ_ENTRIES:
            break
    return faq


def _public_faq_slot_is_empty(settings: dict[str, Any]) -> bool:
    """Write-guard: True only when it is SAFE to seed.

    Safe means ``settings.public_profile.public_faq`` is absent, None, or an
    empty list/string. A non-empty existing value (an owner's real FAQ) returns
    False so it is NEVER overwritten — this is what makes the script idempotent.
    """
    public_profile = _safe_dict(settings.get("public_profile"))
    if "public_faq" not in public_profile:
        return True
    existing = public_profile.get("public_faq")
    return existing in (None, [], "")


def _seed_twin(twin_id: str, faq: list[dict[str, str]]) -> bool:
    """Read-modify-write the twin settings JSON, merging public_faq into
    public_profile WITHOUT clobbering other public_profile keys.

    Mirrors the pp_updates merge in routers/profile.py: re-fetch fresh settings,
    re-check the write-guard (concurrency safety), then
    ``{**current_public_profile, "public_faq": faq}``. Returns True on write.
    """
    fresh = (
        supabase.table("twins")
        .select("settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    fresh_settings = _safe_dict((fresh.data or {}).get("settings"))

    # Re-check on fresh data: never overwrite a value that appeared since scan.
    if not _public_faq_slot_is_empty(fresh_settings):
        logger.info(
            "[backfill_public_faq] skip on re-check, public_faq now present twin_id=%s",
            twin_id,
        )
        return False

    current_public_profile = _safe_dict(fresh_settings.get("public_profile"))
    # Immutable merge — new dicts, never mutate the fetched objects.
    updated_public_profile = {**current_public_profile, "public_faq": faq}
    updated_settings = {**fresh_settings, "public_profile": updated_public_profile}

    supabase.table("twins").update({"settings": updated_settings}).eq("id", twin_id).execute()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed settings.public_profile.public_faq for public twins from their "
            "owner-published verified_qna (visibility='public', is_active=true). "
            "Idempotent; never overwrites an existing public_faq."
        )
    )
    parser.add_argument("--twin-id", help="Backfill a single twin by id")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max twins to scan when --twin-id is not set (default 1000)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. WITHOUT this flag the script is a DRY-RUN (default).",
    )
    args = parser.parse_args()

    apply = bool(args.apply)
    twins = _load_twins(twin_id=args.twin_id, limit=max(1, int(args.limit or 1000)))
    if not twins:
        print("[backfill_public_faq] no twins found")
        return 0

    scanned = 0
    eligible = 0  # passed the public-access gate
    seeded = 0  # would-seed (dry-run) or wrote (apply)
    written = 0  # actual DB writes (apply only)
    skip_not_public = 0
    skip_existing_faq = 0
    skip_no_qna = 0

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[backfill_public_faq] mode={mode} scanning {len(twins)} twin(s)")

    for twin in twins:
        scanned += 1
        twin_id = str(twin.get("id") or "")
        handle = _handle_of(twin) or "(no-handle)"

        if not is_publicly_accessible_twin_record(twin):
            skip_not_public += 1
            continue
        eligible += 1

        settings = _safe_dict(twin.get("settings"))
        if not _public_faq_slot_is_empty(settings):
            skip_existing_faq += 1
            print(f"[backfill_public_faq] skip handle={handle} reason=existing_public_faq")
            continue

        faq = _build_faq_entries(_fetch_public_active_qna(twin_id))
        if not faq:
            skip_no_qna += 1
            print(f"[backfill_public_faq] skip handle={handle} reason=no_public_qna")
            continue

        seeded += 1
        print(
            f"[backfill_public_faq] {'seed' if apply else 'would-seed'} "
            f"handle={handle} twin_id={twin_id} public_faq_count={len(faq)}"
        )

        if not apply:
            continue

        try:
            if _seed_twin(twin_id, faq):
                written += 1
        except Exception as exc:
            logger.exception(
                "[backfill_public_faq] write failed twin_id=%s handle=%s", twin_id, handle
            )
            print(f"[backfill_public_faq] ERROR handle={handle} twin_id={twin_id} exc={exc}")

    skipped = skip_not_public + skip_existing_faq + skip_no_qna
    print(
        "[backfill_public_faq] done "
        f"mode={mode} scanned={scanned} eligible={eligible} "
        f"seeded={seeded} written={written} skipped={skipped} "
        f"(not_public={skip_not_public} existing_faq={skip_existing_faq} no_public_qna={skip_no_qna})"
    )
    if not apply and seeded:
        print("[backfill_public_faq] DRY-RUN — re-run with --apply to write the changes above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
