#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

dev_host="${QUIREBASE_DEV_HOST:-127.0.0.1}"
dev_port="${QUIREBASE_DEV_PORT:-9060}"
dev_frontend_port="${QUIREBASE_DEV_FRONTEND_PORT:-5173}"
dev_username="${QUIREBASE_DEV_USERNAME:-admin}"
dev_password="${QUIREBASE_DEV_PASSWORD:-quirebase-dev}"

if [[ "${QUIREBASE_DEV_SKIP_SETUP:-0}" != "1" ]]; then
  uv sync
  bun install --cwd frontend --frozen-lockfile
fi

export FASTAPI_ENV="development"
export QUIREBASE_DEV_API_ORIGIN="http://$dev_host:$dev_port"
export QUIREBASE_EXTERNAL_ORIGIN="${QUIREBASE_EXTERNAL_ORIGIN:-http://$dev_host:$dev_frontend_port}"

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
server_pid=""
frontend_pid=""
cleanup() {
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
    wait "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  if [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

printf 'Quirebase: http://%s:%s\n' "$dev_host" "$dev_frontend_port"
printf 'FastAPI: http://%s:%s\n' "$dev_host" "$dev_port"
if [[ "$admin_created" == "1" ]]; then
  printf 'Development login: %s / %s\n' "$dev_username" "$dev_password"
else
  printf 'Account %s already exists; its password was not changed.\n' "$dev_username"
fi
printf 'Press Ctrl-C to stop Vite, FastAPI, and the worker.\n'

uv run quirebase worker &
worker_pid=$!
uv run quirebase serve --host "$dev_host" --port "$dev_port" --reload &
server_pid=$!
bun run --cwd frontend dev -- --host "$dev_host" --port "$dev_frontend_port" &
frontend_pid=$!
wait "$frontend_pid"
