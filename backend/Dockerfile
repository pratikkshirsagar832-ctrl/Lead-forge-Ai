
# ==========================================
# LeadForge AI Backend — Dockerfile
# Multi-stage: Go binary build + Python app
# ==========================================

# ── Stage 1: Build google-maps-scraper from source ──
FROM golang:1.26-bookworm AS go-builder

WORKDIR /build
COPY google-maps-scraper/ .
RUN go mod download && \
    CGO_ENABLED=0 GOOS=linux go build -o /google-maps-scraper .

# ── Stage 2: Python application ──
FROM python:3.12-slim-bookworm

# Install system dependencies for Scrapling (Playwright/Patchright Chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    ca-certificates \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies (includes scrapling[all])
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright system deps and Chromium browser (for Scrapling's StealthyFetcher which uses Patchright)
RUN pip install patchright --upgrade 2>&1 && \
    python -m patchright install chromium --with-deps 2>&1 && \
    echo "Patchright Chromium installed"

# Copy the built Go binary
COPY --from=go-builder /google-maps-scraper /app/google-maps-scraper/google-maps-scraper
RUN chmod +x /app/google-maps-scraper/google-maps-scraper

# Vendor the Playwright driver for google-maps-scraper (pins playwright-go -> driver 1.52.0).
# MS CDN purged all playwright-*-linux.zip builds, but the driver is just the
# playwright-core npm tarball. Place it where playwright-go expects it and use
# the system node binary. Browsers (chromium build 1169) are still on the CDN.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* && \
    mkdir -p /opt/ms-playwright/1.52.0 && cd /opt/ms-playwright/1.52.0 && \
    curl -fsSL https://registry.npmjs.org/playwright-core/-/playwright-core-1.52.0.tgz -o driver.tgz && \
    tar -xzf driver.tgz && rm -f driver.tgz && \
    test -f package/cli.js && echo "DRIVER_OK"

# Create sessions directory for LinkedIn cookies
RUN mkdir -p /app/sessions

# Copy application code
COPY app/ /app/app/

# Set environment defaults
ENV GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
ENV PLAYWRIGHT_DRIVER_PATH=/opt/ms-playwright/1.52.0
ENV PLAYWRIGHT_NODEJS_PATH=/usr/bin/node
ENV ENVIRONMENT=production
ENV PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run with uvicorn — production mode (no --reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "120"]
