#!/usr/bin/env python3
"""Lint Supabase migration SQL files for common foot-guns.

Fails (exit 1) if any migration in supabase/migrations/*.sql:

  1. Creates a function or procedure (CREATE [OR REPLACE] FUNCTION ...) without
     either:
       * A matching DROP FUNCTION IF EXISTS in the same file, OR
       * A comment line containing the pragma `-- LINT-ALLOW: new-overload`
         on one of the five lines preceding the CREATE.

     Rationale: `CREATE OR REPLACE FUNCTION` only replaces an identical
     signature. Adding a new overload (different arg list) silently coexists
     with the old one and produces AmbiguousFunctionError at query time.
     Phase 30-A's 20260421_search_chunks_tiers.sql shipped exactly this bug
     — we keep that from happening again.

Usage:
    python scripts/lint_migrations.py [--since GIT_REF]

    --since GIT_REF  Lint only migrations changed since GIT_REF (e.g. `main`).
                     Omit to lint every migration in the tree.

Run in CI on PRs touching supabase/migrations/**. Run locally before pushing
migration changes.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

CREATE_FN_PATTERN = re.compile(
    r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(\w+)\s*\("
)
DROP_FN_PATTERN = re.compile(
    r"(?im)^\s*DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(\w+)"
)
PRAGMA_PATTERN = re.compile(r"--\s*LINT-ALLOW:\s*new-overload", re.IGNORECASE)


def lint_file(path: Path) -> list[str]:
    """Return a list of lint violations found in `path`."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    errors: list[str] = []

    for match in CREATE_FN_PATTERN.finditer(text):
        fname = match.group(1)

        # Look at the 400 chars preceding the CREATE for the pragma.
        window_start = max(0, match.start() - 400)
        window = text[window_start : match.start()]
        if PRAGMA_PATTERN.search(window):
            continue

        file_drops = {m.group(1) for m in DROP_FN_PATTERN.finditer(text)}
        if fname not in file_drops:
            errors.append(
                f"{path.name}: CREATE FUNCTION {fname}(...) has no matching "
                f"DROP FUNCTION IF EXISTS {fname}(...) in the same file. "
                f"Add the DROP (drop the superseded overload) or annotate with "
                f"`-- LINT-ALLOW: new-overload` above the CREATE if an old "
                f"overload genuinely needs to survive."
            )

    return errors


def get_changed_migrations(since: str) -> list[Path]:
    """Return Path objects for migration files changed since the given git ref."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{since}...HEAD", "--", "supabase/migrations/"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
    except subprocess.CalledProcessError as exc:
        print(f"git diff failed: {exc.stderr}", file=sys.stderr)
        return []

    return [
        REPO_ROOT / line
        for line in proc.stdout.splitlines()
        if line.endswith(".sql")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=None,
        help="Git ref to diff against. Omit to lint every migration.",
    )
    args = parser.parse_args()

    if args.since:
        files = get_changed_migrations(args.since)
        if not files:
            print("No migration files changed since", args.since)
            return 0
    else:
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    total_errors = 0
    for path in files:
        for err in lint_file(path):
            print(f"ERROR: {err}", file=sys.stderr)
            total_errors += 1

    if total_errors:
        print(
            f"\nFound {total_errors} migration lint error(s). "
            f"Fix before merging.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: linted {len(files)} migration file(s), no issues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
