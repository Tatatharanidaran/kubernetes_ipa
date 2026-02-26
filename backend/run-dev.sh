#!/usr/bin/env bash
set -euo pipefail

DEFAULT_PORT=8000
FALLBACK_PORT=8100
PORT="$DEFAULT_PORT"

run_uvicorn() {
  if [ -x ".venv/bin/python" ]; then
    if .venv/bin/python -c "import uvicorn" >/dev/null 2>&1; then
      exec .venv/bin/python -m uvicorn app.main:app --reload --port "$PORT"
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import uvicorn" >/dev/null 2>&1; then
      exec python3 -m uvicorn app.main:app --reload --port "$PORT"
    fi
  fi

  printf "[ERROR] Python/uvicorn not found. Create and install backend venv dependencies first.\n" >&2
  exit 1
}

is_port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  ss -ltn 2>/dev/null | grep -q ":$port "
}

if is_port_in_use "$DEFAULT_PORT"; then
  PORT="$FALLBACK_PORT"
  printf "[WARN] Port %s is already in use. Starting backend on %s.\n" "$DEFAULT_PORT" "$PORT"
else
  printf "[INFO] Starting backend on %s.\n" "$PORT"
fi

run_uvicorn
