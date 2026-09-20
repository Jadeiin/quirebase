#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/quirebase-e2e.XXXXXX")"
worker_pid=""
server_pid=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  if [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null; then
    kill "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
  fi
  rm -rf -- "$runtime_dir"
}
trap cleanup EXIT INT TERM

export QUIREBASE_DATABASE_URL="sqlite:///$runtime_dir/quirebase.db"
export QUIREBASE_DATA_DIR="$runtime_dir/data"
export QUIREBASE_EXTERNAL_ORIGIN="http://127.0.0.1:9060"
export QUIREBASE_ALLOWED_HOSTS="127.0.0.1,localhost"
export QUIREBASE_WORKFLOW_EXECUTOR_ID="fullstack-e2e-$$"
export QUIREBASE_LOG_LEVEL="WARNING"
export UV_CACHE_DIR="$runtime_dir/uv-cache"

cd "$project_dir"
uv run quirebase init-db
uv run quirebase create-admin --username admin --password quirebase-e2e

uv run quirebase worker &
worker_pid=$!
uv run quirebase serve --host 127.0.0.1 --port 9060 &
server_pid=$!
wait "$server_pid"
