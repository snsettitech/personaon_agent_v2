#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

START_DEV=true
if [[ "${1:-}" == "--no-start" ]]; then
  START_DEV=false
elif [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  bun run dev:branch
  bun run dev:branch -- --no-start

Creates or reuses a Supabase branch for the current git branch, applies local
migrations, writes app/web/.env, app/desktop/.env, and backend/.env, then starts
the normal dev services.

Optional:
  SUPABASE_BRANCH_NAME=<name> overrides the git-derived branch name.
  SUPABASE_PROJECT_REF=<main-project-ref> overrides the inferred parent project.
  SUPABASE_BRANCH_FLAGS="--persistent" adds flags to branch creation.
EOF
  exit 0
fi

read_env_value() {
  local file="$1"
  local key="$2"
  [[ -f "$file" ]] || return 0
  awk -F= -v key="$key" '
    $1 == key {
      value = substr($0, length(key) + 2)
      gsub(/^["'"'"']|["'"'"']$/, "", value)
      print value
      exit
    }
  ' "$file"
}

project_ref_from_url() {
  local value="$1"
  if [[ "$value" =~ ^https://([a-z0-9-]+)\.supabase\.co/?$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  elif [[ "$value" =~ ^[a-z0-9-]+$ ]]; then
    printf '%s\n' "$value"
  fi
}

project_ref_file=".supabase-project-ref"
infer_project_ref() {
  local value="${SUPABASE_PROJECT_REF:-}"
  if [[ -z "$value" && -f "$project_ref_file" ]]; then
    value="$(<"$project_ref_file")"
  fi
  if [[ -z "$value" ]]; then
    value="$(read_env_value backend/.env SUPABASE_URL)"
  fi
  if [[ -z "$value" ]]; then
    value="$(read_env_value app/web/.env NEXT_PUBLIC_SUPABASE_URL)"
  fi

  local ref
  ref="$(project_ref_from_url "$value")"
  if [[ -z "$ref" ]]; then
    echo "Could not infer Supabase parent project ref." >&2
    echo "Set SUPABASE_PROJECT_REF=<main-project-ref> once, then rerun." >&2
    exit 1
  fi

  printf '%s\n' "$ref" > "$project_ref_file"
  printf '%s\n' "$ref"
}

git_branch_name() {
  git branch --show-current 2>/dev/null || true
}

supabase_branch_name() {
  local raw="${SUPABASE_BRANCH_NAME:-$(git_branch_name)}"
  if [[ -z "$raw" ]]; then
    echo "Could not determine git branch. Set SUPABASE_BRANCH_NAME=<name>." >&2
    exit 1
  fi
  case "$raw" in
    main|master|production|prod)
      echo "Refusing to create/use Supabase branch for protected git branch: $raw" >&2
      exit 1
      ;;
  esac

  echo "$raw" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' \
    | cut -c1-40
}

require_env_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    cp "$file.example" "$file"
  fi
}

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"

  if [[ -f "$file" ]] && grep -qE "^${key}=" "$file"; then
    awk -v key="$key" -v value="$value" '
      BEGIN { replaced = 0 }
      $0 ~ "^" key "=" {
        print key "=" value
        replaced = 1
        next
      }
      { print }
      END {
        if (!replaced) print key "=" value
      }
    ' "$file" > "$tmp"
  else
    [[ -f "$file" ]] && cat "$file" > "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi

  mv "$tmp" "$file"
}

session_pooler_url() {
  local url="$1"
  printf '%s\n' "${url/:6543/:5432}"
}

asyncpg_url() {
  local url="$1"
  url="${url/postgresql:\/\//postgresql+asyncpg:\/\/}"
  if [[ "$url" == *\?* ]]; then
    printf '%s&prepared_statement_cache_size=0\n' "$url"
  else
    printf '%s?prepared_statement_cache_size=0\n' "$url"
  fi
}

get_branch_env() {
  local branch="$1"
  local project_ref="$2"
  bunx supabase branches get "$branch" --project-ref "$project_ref" -o env
}

ensure_branch() {
  local branch="$1"
  local project_ref="$2"

  if get_branch_env "$branch" "$project_ref" >/dev/null 2>&1; then
    echo "Using existing Supabase branch: $branch"
    return
  fi

  echo "Creating Supabase branch: $branch"
  # shellcheck disable=SC2086
  bunx supabase branches create "$branch" --project-ref "$project_ref" ${SUPABASE_BRANCH_FLAGS:-}
}

wait_for_branch_env() {
  local branch="$1"
  local project_ref="$2"
  local timeout_seconds=900
  local deadline=$((SECONDS + timeout_seconds))

  while true; do
    if get_branch_env "$branch" "$project_ref" >/tmp/personaon-supabase-branch.env 2>/tmp/personaon-supabase-branch.err; then
      cat /tmp/personaon-supabase-branch.env
      rm -f /tmp/personaon-supabase-branch.env /tmp/personaon-supabase-branch.err
      return 0
    fi

    echo "Waiting for Supabase branch credentials for $branch..." >&2
    if (( SECONDS >= deadline )); then
      cat /tmp/personaon-supabase-branch.err >&2 || true
      echo "Timed out waiting for Supabase branch $branch." >&2
      exit 1
    fi
    sleep 10
  done
}

wait_for_database() {
  local db_url="$1"
  local timeout_seconds=900
  local deadline=$((SECONDS + timeout_seconds))

  while true; do
    if bunx supabase migration list --db-url "$db_url" >/tmp/personaon-supabase-db-ready.out 2>/tmp/personaon-supabase-db-ready.err; then
      rm -f /tmp/personaon-supabase-db-ready.out /tmp/personaon-supabase-db-ready.err
      return 0
    fi

    echo "Waiting for Supabase database/pooler to accept connections..." >&2
    if (( SECONDS >= deadline )); then
      cat /tmp/personaon-supabase-db-ready.err >&2 || true
      echo "Timed out waiting for Supabase database connection." >&2
      exit 1
    fi
    sleep 10
  done
}

write_service_envs() {
  local session_url="$1"
  local async_session_url="$2"

  require_env_file app/web/.env
  require_env_file app/desktop/.env
  require_env_file backend/.env

  set_env_value app/web/.env NEXT_PUBLIC_SUPABASE_URL "$SUPABASE_URL"
  set_env_value app/web/.env NEXT_PUBLIC_SUPABASE_ANON_KEY "$SUPABASE_ANON_KEY"
  set_env_value app/web/.env NEXT_PUBLIC_BACKEND_URL "http://127.0.0.1:8006"
  set_env_value app/web/.env BACKEND_URL "http://127.0.0.1:8006"

  set_env_value app/desktop/.env VITE_SUPABASE_URL "$SUPABASE_URL"
  set_env_value app/desktop/.env VITE_SUPABASE_ANON_KEY "$SUPABASE_ANON_KEY"
  set_env_value app/desktop/.env VITE_WEB_ORIGIN "http://localhost:3002"
  set_env_value app/desktop/.env VITE_CALENDAR_API_ORIGIN "http://localhost:3002"
  set_env_value app/desktop/.env VITE_API_ORIGIN "http://localhost:3002/api/backend"
  set_env_value app/desktop/.env BACKEND_URL "http://127.0.0.1:8006"

  set_env_value backend/.env SUPABASE_URL "$SUPABASE_URL"
  set_env_value backend/.env SUPABASE_KEY "$SUPABASE_ANON_KEY"
  set_env_value backend/.env SUPABASE_SERVICE_KEY "$SUPABASE_SERVICE_ROLE_KEY"
  set_env_value backend/.env SUPABASE_JWT_SECRET "$SUPABASE_JWT_SECRET"
  set_env_value backend/.env JWT_SECRET "$SUPABASE_JWT_SECRET"
  set_env_value backend/.env JWT_ALGORITHM "HS256"
  set_env_value backend/.env PGVECTOR_DATABASE_URL "$session_url"
  set_env_value backend/.env DATABASE_URL "$session_url"
  set_env_value backend/.env ADK_SESSION_DB_URL "$async_session_url"
}

PROJECT_REF="$(infer_project_ref)"
BRANCH_NAME="$(supabase_branch_name)"
if [[ -z "$BRANCH_NAME" ]]; then
  echo "Supabase branch name resolved to empty. Set SUPABASE_BRANCH_NAME=<name>." >&2
  exit 1
fi

ensure_branch "$BRANCH_NAME" "$PROJECT_REF"
eval "$(wait_for_branch_env "$BRANCH_NAME" "$PROJECT_REF")"

SESSION_URL="$(session_pooler_url "$POSTGRES_URL")"
ASYNC_SESSION_URL="$(asyncpg_url "$SESSION_URL")"

wait_for_database "$SESSION_URL"

echo "Applying migrations to Supabase branch: $BRANCH_NAME"
CONFIRM_SUPABASE_MIGRATE=apply SUPABASE_DB_URL="$SESSION_URL" bash scripts/supabase-migrate.sh apply

write_service_envs "$SESSION_URL" "$ASYNC_SESSION_URL"

echo "Supabase branch ready: $BRANCH_NAME"
echo "Service envs updated: app/web/.env, app/desktop/.env, backend/.env"

if [[ "$START_DEV" == "true" ]]; then
  exec bun run dev
fi
