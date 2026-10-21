#!/usr/bin/env bash
# Migration drift check — fails (exit 1) if any object declared in
# supabase/migrations/ is MISSING from the target database.
#
# Usage:
#   DATABASE_URL=postgres://... bash scripts/check_migration_drift.sh
#
# In CI, point DATABASE_URL at the prod pooler (IPv4):
#   postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres
# The direct host db.<ref>.supabase.co is IPv6-only and won't resolve from most
# CI runners — always use the session/transaction pooler host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: set DATABASE_URL (use the Supabase pooler host, not db.<ref>.supabase.co)" >&2
  exit 2
fi

python scripts/migration_drift_audit.py >/dev/null
AUDIT_SQL="scripts/_migration_audit.sql"

ROWS="$(psql "$DATABASE_URL" -P pager=off -t -A -f "$AUDIT_SQL" 2>&1)"
COUNT="$(printf '%s\n' "$ROWS" | grep -c '|' || true)"

if [ "$COUNT" -eq 0 ]; then
  echo "✓ no migration drift — every declared object exists in the target DB"
  exit 0
fi

echo "✗ migration drift detected ($COUNT missing object(s)):"
printf '%s\n' "$ROWS"
echo ""
echo "Apply the missing migrations (see docs/runbooks/migration-drift.md)."
exit 1
