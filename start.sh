#!/usr/bin/env bash
# =============================================================================
# RepoLens AI — one-command start script (bash / Git Bash on Windows)
# Starts backend (FastAPI/uvicorn on :8000) and frontend (Vite on :5173).
#
# Usage:
#   ./start.sh            # start both servers
#   ./start.sh --clean    # also stop anything already on :8000 / :5173 first
# =============================================================================
set -u

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

say()  { printf "${GREEN}[start]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[start]${NC} %s\n" "$1"; }
err()  { printf "${RED}[start]${NC} %s\n" "$1"; }

kill_port() {
  local port="$1"
  local pids
  pids=$(netstat -ano 2>/dev/null | grep ":$port" | grep LISTENING | awk '{print $NF}' | sort -u)
  for pid in $pids; do
    warn "killing stale process $pid on :$port"
    taskkill //F //PID "$pid" >/dev/null 2>&1
  done
}

# --- optional cleanup of stale servers ---------------------------------------
if [ "${1:-}" = "--clean" ]; then
  kill_port 8000
  kill_port 5173
  sleep 1
fi

# --- preflight checks ---------------------------------------------------------
command -v python >/dev/null 2>&1 || { err "python not found in PATH"; exit 1; }
command -v npm    >/dev/null 2>&1 || { err "npm not found in PATH"; exit 1; }
[ -f "$BACKEND_DIR/.env" ] || warn "backend/.env missing — copy .env.example and set JWT_SECRET + ENCRYPTION_KEY"
[ -d "$FRONTEND_DIR/node_modules" ] || { say "installing frontend dependencies (first run)..."; (cd "$FRONTEND_DIR" && npm install) || { err "npm install failed"; exit 1; } }

# --- start backend (always from backend/ so relative paths resolve correctly) --
say "starting backend: uvicorn on http://127.0.0.1:8000 (logs: logs/backend.log)"
(
  cd "$BACKEND_DIR" || exit 1
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# --- start frontend ------------------------------------------------------------
say "starting frontend: vite on http://localhost:5173 (logs: logs/frontend.log)"
(
  cd "$FRONTEND_DIR" || exit 1
  npm run dev
) > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

# --- wait for the backend to become healthy ------------------------------------
say "waiting for backend health check"
HEALTHY=0
for _ in $(seq 1 45); do
  if curl -sf -m 2 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  sleep 1
done

if [ "$HEALTHY" = "1" ]; then
  say "backend is healthy: $(curl -s -m 3 http://127.0.0.1:8000/api/v1/health)"
else
  err "backend did not become healthy within 45s — check logs/backend.log"
  err "common cause: missing JWT_SECRET / ENCRYPTION_KEY in backend/.env"
fi

echo ""
say "RepoLens AI is starting up:"
echo "    Frontend : http://localhost:5173"
echo "    Backend  : http://127.0.0.1:8000/api/v1/health"
echo "    Logs     : logs/backend.log, logs/frontend.log"
echo ""
echo "    Stop with: ./stop.sh   (or close this terminal)"
echo ""

# Keep the script in the foreground so Ctrl+C stops both children.
wait $BACKEND_PID $FRONTEND_PID
