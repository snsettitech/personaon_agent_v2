#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STRICT=false
WEB_URL="${WEB_URL:-http://127.0.0.1:3002}"

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay="${4:-2}"

  printf 'Waiting for %s at %s' "$name" "$url" >&2
  for _ in $(seq 1 "$attempts"); do
    if curl -sS -o /dev/null --max-time 2 "$url" >/dev/null 2>&1; then
      printf ' ok\n' >&2
      return 0
    fi
    printf '.' >&2
    sleep "$delay"
  done
  printf ' failed\n' >&2
  return 1
}

wait_for_url "PersonaOn web" "$WEB_URL"

health_url="$WEB_URL/api/health"
if [[ "$STRICT" == "true" ]]; then
  health_url="$health_url?strict=1"
fi

health_file="$(mktemp)"
status_code="$(curl -sS -o "$health_file" -w "%{http_code}" --max-time 10 "$health_url")"

bun --silent -e '
const fs = require("node:fs");
const file = process.argv[1];
const raw = fs.readFileSync(file, "utf8");
try {
  const health = JSON.parse(raw);
  const checks = Object.fromEntries(
    Object.entries(health.checks ?? {}).map(([name, check]) => [
      name,
      { status: check.status, target: check.target, detail: check.detail, latencyMs: check.latencyMs }
    ])
  );
  console.log(JSON.stringify({
    status: health.status,
    service: health.service,
    correlationId: health.correlationId,
    checks
  }, null, 2));
} catch (error) {
  console.error(raw);
  process.exit(3);
}
' "$health_file"

health_status="$(bun --silent -e 'const fs = require("node:fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).status ?? "unknown")' "$health_file")"
rm -f "$health_file"

if [[ "$status_code" != "200" || "$health_status" != "healthy" ]]; then
  echo "Health check failed: HTTP $status_code, status=$health_status" >&2
  exit 1
fi
