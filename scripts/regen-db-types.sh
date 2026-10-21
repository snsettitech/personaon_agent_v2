#!/usr/bin/env bash
# Regenerate frontend/lib/database.types.ts from the Supabase staging schema.
#
# Requires: SUPABASE_ACCESS_TOKEN set (personal access token from the Supabase
# dashboard) and the Supabase CLI available on PATH.
#
# Run this after any migration lands on staging, before merging frontend code
# that consumes the affected tables. The committed database.types.ts is the
# source of truth for DB-backed type shapes; drift between it and the DB is
# exactly what produced the Phase 30 null-crash class.

set -euo pipefail

PROJECT_ID="${SUPABASE_PROJECT_ID:?set SUPABASE_PROJECT_ID}"
OUTPUT="frontend/lib/database.types.ts"

if ! command -v supabase >/dev/null 2>&1; then
  echo "FATAL: supabase CLI not found. Install via https://supabase.com/docs/guides/cli" >&2
  exit 1
fi

if [ -z "${SUPABASE_ACCESS_TOKEN:-}" ]; then
  echo "FATAL: SUPABASE_ACCESS_TOKEN not set. Export a personal access token from the dashboard." >&2
  exit 1
fi

HEADER='// AUTO-GENERATED from Supabase schema via `scripts/regen-db-types.sh`.
// DO NOT EDIT BY HAND — re-run the script after migrations.
//
// Handwritten types for DB-backed shapes proved unreliable (Phase 30 post-mortem:
// three of four production crashes were frontend types lying about nullability).
// Import from this file instead of declaring the shape inline.

/* eslint-disable */

'

{
  printf '%s' "$HEADER"
  supabase gen types typescript --project-id "$PROJECT_ID"
} > "$OUTPUT"

echo "OK: wrote $OUTPUT"
