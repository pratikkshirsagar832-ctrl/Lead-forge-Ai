#!/bin/bash
# ===========================================
# LeadForge AI — Production API Startup Script
# ===========================================
# Usage: ./scripts/run-api.sh
# Run from backend/ directory or set BACKEND_DIR

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/.."
cd "$BACKEND_DIR"

echo "=================================="
echo "  LeadForge AI — Backend Server"
echo "=================================="

# Load .env if it exists
if [ -f ".env" ]; then
    echo "[*] Loading .env file..."
    set -a
    source .env
    set +a
else
    echo "[!] No .env file found. Ensure environment variables are set."
fi

# Activate virtualenv if it exists
for venv in venv .venv env; do
    if [ -f "$venv/bin/activate" ]; then
        echo "[*] Activating virtualenv: $venv"
        source "$venv/bin/activate"
        break
    fi
done

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "[*] Starting uvicorn on ${HOST}:${PORT} (workers=${WORKERS})..."
echo "[*] Health: http://${HOST}:${PORT}/api/health"
echo ""

exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --timeout-keep-alive 120 \
    --log-level info
