"""Backfill repair for twins whose work_experience was collapsed pre-fix.

WHAT THIS REPAIRS
-----------------
Before the firecrawl_service work-experience audit/repair shipped, some twins were
materialized with a COLLAPSED work history: a multi-year, multi-role tenure at one
company got merged into a single role (often a suspicious single-year span like
2023-2023) and the bio still claimed "~N years" at that company. The deterministic
auditor ``audit_work_experience`` detects these as ``single_year_span`` /
``date_inverted`` / ``understated_tenure``. This script finds already-stored twins
with those artifacts and, with ``--apply``, re-extracts and writes back the
corrected work history.

WHERE THE PROFILE IS STORED (investigated 2026-06-16)
-----------------------------------------------------
The per-twin structured profile lives in the ``twins`` table, in the JSONB column
``settings``, under the nested key ``persona_profile``. There is NO ``twins.profile``
or ``twins.persona_profile`` column and no separate profile table.

  - Canonical write path: ``routers/auto_create.py`` builds ``profile_fields`` from
    the ``extract_profile()`` result (allow-list explicitly includes
    ``work_experience``) and writes
    ``sb.table("twins").update({"settings": {..., "persona_profile": profile_fields}})``
    (auto_create.py:203-243).
  - The persona_profile dict carries the same fields the audit reads:
    ``work_experience`` (list of {company, role, start_year, end_year, ...}),
    ``short_description`` and ``occupation`` (the audit also reads ``bio`` but stored
    profiles use ``short_description``), plus ``name``.
  - The person's display name is the TOP-LEVEL ``twins.name`` column; the handle is
    ``settings.handle``. ``linkedin_url`` is NOT stored on the twin -- it lives on
    ``connected_accounts.profile_snapshot.profile_url`` for the twin's owner, so we
    look it up best-effort to anchor re-extraction.

  A sibling key ``settings.public_profile`` is the user-edited surface that public
  readers merge OVER ``persona_profile``. This script repairs ``persona_profile``
  (the extraction source of truth) only; it deliberately does NOT touch
  ``public_profile`` to avoid clobbering user edits.

SAFETY
------
  - Default is a DRY RUN: nothing is written. ``--apply`` is required to write.
  - Per-twin try/except: one twin's failure logs and continues; never aborts the run.
  - Apply-gate: a re-extraction REPLACES the stored work_experience only when it is
    strictly BETTER -- more entries, OR the same/fewer entries but fewer audit issues.
    Otherwise the original is kept untouched.

USAGE
-----
  python scripts/repair_collapsed_work_experience.py                 # dry run, all twins (limit 50)
  python scripts/repair_collapsed_work_experience.py --handle sai    # one twin by handle
  python scripts/repair_collapsed_work_experience.py --limit 200     # scan more twins
  python scripts/repair_collapsed_work_experience.py --apply         # actually write repairs
"""
import argparse
import logging
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv()

from modules.observability import supabase  # noqa: E402  (after load_dotenv)
from adk_core.services.firecrawl_service import (  # noqa: E402
    audit_work_experience,
    extract_profile,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50


def _persona_profile(settings: dict) -> dict:
    """Return the stored persona_profile dict (or empty) from a twin's settings."""
    if not isinstance(settings, dict):
        return {}
    profile = settings.get("persona_profile")
    return profile if isinstance(profile, dict) else {}


def _lookup_linkedin_url(sb, tenant_id: str | None) -> str | None:
    """Best-effort LinkedIn URL for re-extraction anchoring (may be None)."""
    if not tenant_id:
        return None
    try:
        resp = (
            sb.table("connected_accounts")
            .select("profile_snapshot, provider")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        for row in resp.data or []:
            snap = row.get("profile_snapshot") or {}
            url = snap.get("profile_url") if isinstance(snap, dict) else None
            if url:
                return url
    except Exception:
        logger.warning("[repair] linkedin lookup failed tenant_id=%s", tenant_id, exc_info=True)
    return None


def _build_context(profile: dict) -> str | None:
    """Short disambiguation context for extract_profile, from stored fields."""
    parts = [profile.get("occupation"), profile.get("short_description")]
    text = " - ".join(p for p in parts if isinstance(p, str) and p.strip())
    return text[:500] if text else None


def _is_better(original_work: list, repaired_work: list, profile: dict) -> bool:
    """Apply-gate: True only when the repaired work history is strictly better.

    Better = MORE entries, OR (not fewer entries AND fewer audit issues).
    """
    orig_count = len(original_work) if isinstance(original_work, list) else 0
    new_count = len(repaired_work) if isinstance(repaired_work, list) else 0
    if new_count > orig_count:
        return True
    if new_count < orig_count:
        return False
    # Same count: only better if it resolves audit issues.
    orig_issues = len(audit_work_experience(profile))
    candidate = {**profile, "work_experience": repaired_work}
    new_issues = len(audit_work_experience(candidate))
    return new_issues < orig_issues


def _select_twins(sb, handle: str | None, limit: int) -> list[dict]:
    """Read candidate twins (id, name, tenant_id, settings)."""
    query = sb.table("twins").select("id, name, tenant_id, settings")
    resp = query.limit(limit).execute()
    rows = resp.data or []
    if handle:
        wanted = handle.strip().lower()
        rows = [
            r
            for r in rows
            if (((r.get("settings") or {}).get("handle") or "").strip().lower() == wanted)
        ]
    return rows


def _repair_one(sb, twin: dict, apply: bool) -> str:
    """Process a single twin. Returns one of: clean | flagged | repaired | skipped."""
    twin_id = twin.get("id")
    name = (twin.get("name") or "").strip()
    tenant_id = twin.get("tenant_id")
    settings = twin.get("settings") or {}
    profile = _persona_profile(settings)
    handle = (settings.get("handle") or "").strip() or "(no-handle)"

    if not profile:
        return "skipped"

    issues = audit_work_experience(profile)
    if not issues:
        return "clean"

    print(f"\n[FLAGGED] {handle}  name={name!r}  twin={twin_id}")
    for issue in issues:
        print(f"    - {issue}")

    if not name:
        print("    -> cannot re-extract: twin has no name; skipping")
        return "skipped"

    if not apply:
        print("    -> would re-extract (dry run, nothing written)")
        return "flagged"

    # --- APPLY path: re-extract and write back only if strictly better ---
    linkedin_url = _lookup_linkedin_url(sb, tenant_id)
    context = _build_context(profile)
    original_work = profile.get("work_experience") or []

    try:
        fresh = extract_profile(
            name,
            context=context,
            linkedin_url=linkedin_url,
            repair=True,
        )
    except Exception:
        logger.exception("[repair] re-extraction failed twin_id=%s name=%s", twin_id, name)
        print("    -> re-extraction FAILED (logged); keeping original")
        return "skipped"

    repaired_work = fresh.get("work_experience") if isinstance(fresh, dict) else None
    if not isinstance(repaired_work, list) or not repaired_work:
        print("    -> re-extraction returned no usable work_experience; keeping original")
        return "skipped"

    if not _is_better(original_work, repaired_work, profile):
        print(
            f"    -> re-extraction not better "
            f"({len(original_work)} -> {len(repaired_work)} entries); keeping original"
        )
        return "skipped"

    new_persona = {**profile, "work_experience": repaired_work}
    review = fresh.get("extraction_review")
    if review:
        new_persona["extraction_review"] = review
    else:
        new_persona.pop("extraction_review", None)

    # Fail-safe: never write a twin row without a tenant scope. A NULL tenant_id
    # would scope the update by id alone — refuse rather than risk an unscoped write.
    if not tenant_id:
        logger.warning("[repair] skipping write twin_id=%s: missing tenant_id (fail-safe)", twin_id)
        print("    -> skipping write: twin has no tenant_id (fail-safe)")
        return "skipped"

    new_settings = {**settings, "persona_profile": new_persona}
    try:
        q = (
            sb.table("twins")
            .update({"settings": new_settings})
            .eq("id", twin_id)
            .eq("tenant_id", tenant_id)
        )
        q.execute()
    except Exception:
        logger.exception("[repair] write-back failed twin_id=%s", twin_id)
        print("    -> write-back FAILED (logged); original left intact")
        return "skipped"

    print(
        f"    -> REPAIRED: work_experience {len(original_work)} -> {len(repaired_work)} entries; "
        f"wrote twins.settings.persona_profile"
    )
    return "repaired"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair twins with collapsed work_experience (dry run unless --apply)."
    )
    parser.add_argument("--apply", action="store_true", help="Write repairs (default: dry run).")
    parser.add_argument("--handle", default=None, help="Only process the twin with this handle.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max twins to scan (default {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit no-op flag; dry run is already the default.",
    )
    args = parser.parse_args()

    apply = bool(args.apply)
    mode = "APPLY" if apply else "DRY-RUN"
    sb = supabase

    print(f"=== repair_collapsed_work_experience ({mode}) ===")
    print(f"  handle={args.handle or '(all)'}  limit={args.limit}")
    if apply and not args.handle and args.limit < 200:
        print(
            f"  WARNING: --apply with a low --limit ({args.limit}) only scans the first "
            f"{args.limit} twins — raise --limit to cover the full table before relying on this run."
        )

    try:
        twins = _select_twins(sb, args.handle, args.limit)
    except Exception:
        logger.exception("[repair] failed to load twins")
        print("FATAL: could not load twins (see logs).")
        sys.exit(1)

    print(f"  loaded {len(twins)} twin(s)")

    counts = {"clean": 0, "flagged": 0, "repaired": 0, "skipped": 0}
    for twin in twins:
        try:
            outcome = _repair_one(sb, twin, apply)
        except Exception:
            logger.exception("[repair] unexpected error twin_id=%s", twin.get("id"))
            outcome = "skipped"
        counts[outcome] = counts.get(outcome, 0) + 1

    flagged_total = counts["flagged"] + counts["repaired"]
    print("\n=== SUMMARY ===")
    print(f"  scanned : {len(twins)}")
    print(f"  clean   : {counts['clean']}")
    print(f"  flagged : {flagged_total}  (candidates with audit issues)")
    print(f"  repaired: {counts['repaired']}")
    print(f"  skipped : {counts['skipped']}")
    if not apply and flagged_total:
        print("\n  Dry run. Re-run with --apply to re-extract and write repairs.")


if __name__ == "__main__":
    main()
