#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "Python is required for migration validation." >&2
    exit 1
  fi
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/supabase-migrate.sh validate
  bash scripts/supabase-migrate.sh list
  bash scripts/supabase-migrate.sh plan
  CONFIRM_SUPABASE_MIGRATE=apply bash scripts/supabase-migrate.sh apply

Environment:
  SUPABASE_DB_URL must be a percent-encoded Postgres connection string for
  list, plan, and apply.

Notes:
  - plan uses `supabase db push --dry-run`.
  - apply never runs unless CONFIRM_SUPABASE_MIGRATE=apply is set.
  - first-time database bootstrap is a separate manual process; see docs.
EOF
}

require_db_url() {
  if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
    echo "SUPABASE_DB_URL is required for this command." >&2
    exit 1
  fi
}

validate() {
  "$PYTHON_BIN" scripts/check_migration_filenames.py
  "$PYTHON_BIN" scripts/lint_migrations.py
}

case "${1:-}" in
  validate)
    validate
    ;;
  list)
    require_db_url
    bunx supabase migration list --db-url "$SUPABASE_DB_URL"
    ;;
  plan)
    require_db_url
    validate
    bunx supabase db push --db-url "$SUPABASE_DB_URL" --dry-run
    ;;
  apply)
    require_db_url
    if [[ "${CONFIRM_SUPABASE_MIGRATE:-}" != "apply" ]]; then
      echo "Refusing to apply. Set CONFIRM_SUPABASE_MIGRATE=apply." >&2
      exit 1
    fi
    validate
    bunx supabase db push --db-url "$SUPABASE_DB_URL" --yes
    ;;
  "" | -h | --help)
    usage
    ;;
  *)
    echo "Unknown command: $1" >&2
    usage >&2
    exit 1
    ;;
esac
