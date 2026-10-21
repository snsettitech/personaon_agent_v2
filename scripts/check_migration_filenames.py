#!/usr/bin/env python3
"""Validate Supabase migration filenames.

Historical date-only filenames are grandfathered in
supabase/migration-history-allowlist.txt. New migrations should use unique
timestamp versions, usually YYYYMMDDHHMMSS_name.sql.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
ALLOWLIST_PATH = REPO_ROOT / "supabase" / "migration-history-allowlist.txt"
FILENAME_PATTERN = re.compile(r"^(\d+)_([a-z0-9_]+)\.sql$")


def load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def main() -> int:
    allowlist = load_allowlist()
    errors: list[str] = []
    warnings: list[str] = []
    versions: dict[str, list[str]] = defaultdict(list)

    files = sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    for filename in files:
        match = FILENAME_PATTERN.match(filename)
        if not match:
            errors.append(f"{filename}: expected <numeric-version>_<name>.sql")
            continue

        version = match.group(1)
        versions[version].append(filename)

        if len(version) < 14 and filename not in allowlist:
            errors.append(
                f"{filename}: new migrations must use a timestamp version "
                f"(YYYYMMDDHHMMSS), or be explicitly grandfathered."
            )
        elif len(version) < 14:
            warnings.append(f"{filename}: historical date-only migration allowed")

    for version, filenames in sorted(versions.items()):
        if len(filenames) <= 1:
            continue
        unexpected = [filename for filename in filenames if filename not in allowlist]
        if unexpected:
            errors.append(
                f"version {version} is duplicated by {', '.join(filenames)}. "
                f"Only historical allowlisted duplicates are permitted."
            )
        else:
            warnings.append(f"version {version}: historical duplicate version allowed")

    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        print(f"\nFound {len(errors)} migration filename error(s).", file=sys.stderr)
        return 1

    print(f"OK: validated {len(files)} migration filename(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
