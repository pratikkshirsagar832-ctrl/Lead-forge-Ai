#!/bin/bash
# ===========================================
# LeadForge AI — Build google-maps-scraper binary
# ===========================================
# Requirements: Go 1.23+ installed on the VM
# Run from backend/ directory

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/.."
SCRAPER_DIR="${BACKEND_DIR}/google-maps-scraper"

echo "[*] Building google-maps-scraper..."

if [ ! -d "$SCRAPER_DIR" ]; then
    echo "[!] google-maps-scraper directory not found at: $SCRAPER_DIR"
    echo "    Clone it first: git clone https://github.com/gosom/google-maps-scraper.git"
    exit 1
fi

cd "$SCRAPER_DIR"

# Check Go is installed
if ! command -v go &> /dev/null; then
    echo "[!] Go is not installed. Install Go 1.23+:"
    echo "    sudo snap install go --classic"
    exit 1
fi

echo "[*] Go version: $(go version)"
echo "[*] Downloading dependencies..."
go mod download

echo "[*] Building binary..."
CGO_ENABLED=0 go build -o google-maps-scraper .

echo "[✓] Built successfully: ${SCRAPER_DIR}/google-maps-scraper"
echo "[*] Make sure GMAPS_SCRAPER_PATH in .env points to this binary."
