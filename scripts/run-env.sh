#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-}"
SEPARATOR="${2:-}"

if [[ -z "$ENV_FILE" || "$SEPARATOR" != "--" || "$#" -lt 3 ]]; then
  echo "Usage: bash scripts/run-env.sh <env-file> -- <command...>" >&2
  exit 2
fi

shift 2

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  if [[ -f "$ENV_FILE.example" ]]; then
    echo "Create it with: cp $ENV_FILE.example $ENV_FILE" >&2
  fi
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

exec "$@"
