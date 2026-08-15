#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

dev_host="${QUIREBASE_DEV_HOST:-127.0.0.1}"
dev_port="${QUIREBASE_DEV_PORT:-9060}"
dev_username="${QUIREBASE_DEV_USERNAME:-admin}"
dev_password="${QUIREBASE_DEV_PASSWORD:-quirebase-dev}"

if [[ "${QUIREBASE_DEV_SKIP_SETUP:-0}" != "1" ]]; then
  uv sync
  bun install --frozen-lockfile
  bun run build
fi

uv run quirebase init-db

admin_created=0
if admin_output="$(
  uv run quirebase create-admin \
    --username "$dev_username" \
    --password "$dev_password" 2>&1
)"; then
  admin_created=1
elif [[ "$admin_output" != *"username already exists"* ]]; then
  printf '%s\n' "$admin_output" >&2
  exit 1
fi

worker_pid=""
cleanup() {
  if [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

printf 'Quirebase: http://%s:%s\n' "$dev_host" "$dev_port"
if [[ "$admin_created" == "1" ]]; then
  printf 'Development login: %s / %s\n' "$dev_username" "$dev_password"
else
  printf 'Account %s already exists; its password was not changed.\n' "$dev_username"
fi
printf 'Press Ctrl-C to stop the web server and worker.\n'

uv run quirebase worker &
worker_pid=$!
uv run quirebase serve --host "$dev_host" --port "$dev_port" --reload
