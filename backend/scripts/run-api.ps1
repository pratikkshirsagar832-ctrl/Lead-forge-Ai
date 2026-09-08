# LeadForge AI — Run API Server
# PowerShell script for local development

$ErrorActionPreference = "Stop"

# Move to backend directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
Set-Location $BackendDir

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "  LeadForge AI — Backend Server" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Check for .env file
if (-not (Test-Path ".env")) {
    Write-Host "[!] No .env file found. Copy .env.example to .env and fill in your values." -ForegroundColor Red
    Write-Host "    cp .env.example .env" -ForegroundColor Yellow
    exit 1
}

# Try to activate virtual environment
$VenvPaths = @("venv\Scripts\Activate.ps1", ".venv\Scripts\Activate.ps1", "env\Scripts\Activate.ps1")
$VenvFound = $false

foreach ($venv in $VenvPaths) {
    if (Test-Path $venv) {
        Write-Host "[*] Activating virtual environment: $venv" -ForegroundColor Green
        & $venv
        $VenvFound = $true
        break
    }
}

if (-not $VenvFound) {
    Write-Host "[!] No virtual environment found. Running with system Python." -ForegroundColor Yellow
    Write-Host "    Create one with: python -m venv venv" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[*] Starting uvicorn server..." -ForegroundColor Green
Write-Host "[*] API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "[*] Health:   http://localhost:8000/api/health" -ForegroundColor Cyan
Write-Host ""

# Run uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
