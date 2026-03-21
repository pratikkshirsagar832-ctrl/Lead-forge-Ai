# ==========================================
# LeadForge AI Backend — Dockerfile
# Multi-stage: Go binary build + Python app
# ==========================================

# ── Stage 1: Build google-maps-scraper from source ──
FROM golang:1.23-bookworm AS go-builder

WORKDIR /build
COPY google-maps-scraper/ .
RUN go mod download && \
    CGO_ENABLED=0 GOOS=linux go build -o /google-maps-scraper .

# ── Stage 2: Python application ──
FROM python:3.12-slim-bookworm

# Install system dependencies for Scrapling and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    gnupg \
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

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Scrapling from the local copy
COPY Scrapling/ /tmp/Scrapling/
RUN pip install --no-cache-dir /tmp/Scrapling/ && rm -rf /tmp/Scrapling/

# Install Playwright browsers (needed by Scrapling)
RUN python -m playwright install chromium --with-deps 2>/dev/null || true

# Copy the built Go binary
COPY --from=go-builder /google-maps-scraper /app/google-maps-scraper/google-maps-scraper
RUN chmod +x /app/google-maps-scraper/google-maps-scraper

# Copy application code
COPY app/ /app/app/

# Set environment defaults
ENV GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
ENV ENVIRONMENT=production
ENV PORT=8000

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run with uvicorn — production mode (no --reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "120"]
