#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

get_env_value() {
  local key="$1"
  local default_value="$2"
  local value=""

  if [[ -f ".env" ]]; then
    value="$(grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | sed -E "s/^[[:space:]]*${key}=//" || true)"
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi

  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default_value"
  fi
}

HOST="${HOST:-$(get_env_value HOST 127.0.0.1)}"
PORT="${PORT:-$(get_env_value PORT 8001)}"
API_BASE_URL="${API_BASE_URL:-$(get_env_value API_BASE_URL "http://${HOST}:${PORT}/api/v1")}"
GRADIO_SERVER_NAME="${GRADIO_SERVER_NAME:-$(get_env_value GRADIO_SERVER_NAME 127.0.0.1)}"
GRADIO_SERVER_PORT="${GRADIO_SERVER_PORT:-$(get_env_value GRADIO_SERVER_PORT 7861)}"
GRADIO_SHARE="${GRADIO_SHARE:-$(get_env_value GRADIO_SHARE false)}"
FRONTEND_HOST="${FRONTEND_HOST:-$(get_env_value FRONTEND_HOST 127.0.0.1)}"
FRONTEND_PORT="${FRONTEND_PORT:-$(get_env_value FRONTEND_PORT 5173)}"
ENABLE_GRADIO="${ENABLE_GRADIO:-$(get_env_value ENABLE_GRADIO true)}"
ENABLE_REACT_FRONTEND="${ENABLE_REACT_FRONTEND:-$(get_env_value ENABLE_REACT_FRONTEND true)}"
VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-$(get_env_value VITE_API_PROXY_TARGET "http://${HOST}:${PORT}")}"

export HOST PORT API_BASE_URL GRADIO_SERVER_NAME GRADIO_SERVER_PORT GRADIO_SHARE
export FRONTEND_HOST FRONTEND_PORT ENABLE_GRADIO ENABLE_REACT_FRONTEND VITE_API_PROXY_TARGET
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif [[ -x "agentic_rag_env/bin/python" ]]; then
  PYTHON="agentic_rag_env/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "ERROR: Python not found. Please install Python 3.10+ or create .venv." >&2
  exit 1
fi

if command -v npm >/dev/null 2>&1; then
  NPM="npm"
else
  NPM=""
fi

BACKEND_PID=""
FRONTEND_PID=""
GRADIO_PID=""

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$GRADIO_PID" ]] && kill -0 "$GRADIO_PID" >/dev/null 2>&1; then
    kill "$GRADIO_PID" >/dev/null 2>&1 || true
    wait "$GRADIO_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

mkdir -p logs

wait_for_http() {
  local url="$1"
  local name="$2"
  local retries="${3:-40}"
  local interval="${4:-1}"

  for ((i=1; i<=retries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[OK] ${name} ready: ${url}"
      return 0
    fi
    sleep "$interval"
  done

  echo "[WARN] ${name} not ready after ${retries}s: ${url}"
  return 1
}

echo "=================================================="
echo "Starting AgenticRAG"
echo "Project: $ROOT_DIR"
echo "Python: $PYTHON"
echo "FastAPI: http://${HOST}:${PORT}"
echo "API docs: http://${HOST}:${PORT}/docs"
echo "React Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Gradio: http://${GRADIO_SERVER_NAME}:${GRADIO_SERVER_PORT}"
echo "API_BASE_URL: ${API_BASE_URL}"
echo "ENABLE_REACT_FRONTEND: ${ENABLE_REACT_FRONTEND}"
echo "ENABLE_GRADIO: ${ENABLE_GRADIO}"
echo "=================================================="

"$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "[1/3] FastAPI started, pid=${BACKEND_PID}, log=logs/backend.log"
wait_for_http "http://${HOST}:${PORT}/health" "FastAPI" || true

if [[ "$ENABLE_REACT_FRONTEND" == "true" ]]; then
  if [[ -z "$NPM" ]]; then
    echo "[WARN] npm not found, skip React frontend startup"
  elif [[ ! -d "frontend" ]]; then
    echo "[WARN] frontend/ not found, skip React frontend startup"
  elif [[ ! -d "frontend/node_modules" ]]; then
    echo "[WARN] frontend/node_modules not found. Run: cd frontend && npm install"
  else
    (
      cd frontend
      VITE_API_PROXY_TARGET="$VITE_API_PROXY_TARGET" "$NPM" run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > ../logs/frontend.log 2>&1
    ) &
    FRONTEND_PID=$!
    echo "[2/3] React frontend started, pid=${FRONTEND_PID}, log=logs/frontend.log"
    wait_for_http "http://${FRONTEND_HOST}:${FRONTEND_PORT}/" "React frontend" || true
  fi
fi

if [[ "$ENABLE_GRADIO" == "true" ]]; then
  "$PYTHON" - <<'PY' > logs/gradio.log 2>&1 &
from front.app import create_interface
from front.config import GRADIO_SERVER_NAME, GRADIO_SERVER_PORT, GRADIO_SHARE

demo = create_interface()
demo.launch(
    server_name=GRADIO_SERVER_NAME,
    server_port=GRADIO_SERVER_PORT,
    share=GRADIO_SHARE,
    quiet=False,
)
PY
  GRADIO_PID=$!
  echo "[3/3] Gradio started, pid=${GRADIO_PID}, log=logs/gradio.log"
  wait_for_http "http://${GRADIO_SERVER_NAME}:${GRADIO_SERVER_PORT}/" "Gradio" || true
fi

echo
echo "Services overview"
echo "- FastAPI docs: http://${HOST}:${PORT}/docs"
echo "- React frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
if [[ "$ENABLE_GRADIO" == "true" ]]; then
  echo "- Gradio UI: http://${GRADIO_SERVER_NAME}:${GRADIO_SERVER_PORT}"
fi
echo
echo "Logs:"
echo "- logs/backend.log"
echo "- logs/frontend.log"
echo "- logs/gradio.log"
echo
echo "Press Ctrl+C to stop all services"

wait "$BACKEND_PID"
