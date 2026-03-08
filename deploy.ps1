#Requires -RunAsAdministrator
<#
.SYNOPSIS
    AIO Game Terminal deployment script.
    Downloads latest files from GitHub and deploys to the installed kiosk location.

.DESCRIPTION
    - Downloads the repo archive from GitHub using curl (no git required)
    - Stops AIOAgent and AIOWatchdog services
    - Copies kiosk scripts, images, videos, and agent files into place
    - Installs/updates Python dependencies
    - Restarts services

.USAGE
    Run from an elevated PowerShell prompt:
        powershell -ExecutionPolicy Bypass -File C:\ProgramData\aio\deploy.ps1
#>

$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────
$REPO_OWNER   = "roxas712"
$REPO_NAME    = "aio"
$BRANCH       = "main"
$STAGING_DIR  = "C:\ProgramData\aio\repo"
$INSTALL_DIR  = "C:\Program Files\aio"
$PYTHON_EXE   = "C:\Program Files\Python314\python.exe"

$ARCHIVE_URL  = "https://github.com/$REPO_OWNER/$REPO_NAME/archive/refs/heads/$BRANCH.zip"
$ZIP_PATH     = "C:\ProgramData\aio\aio-latest.zip"

# ── Download latest from GitHub ────────────────────────────
Write-Host "[1/6] Downloading latest from GitHub..." -ForegroundColor Cyan

# Ensure parent directory exists
if (-not (Test-Path "C:\ProgramData\aio")) {
    New-Item -ItemType Directory -Path "C:\ProgramData\aio" -Force | Out-Null
}

# Download zip archive using curl.exe (built into Windows 10)
& curl.exe -L -s -o $ZIP_PATH $ARCHIVE_URL
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to download archive from GitHub" -ForegroundColor Red
    exit 1
}
Write-Host "       Downloaded archive"

# Clear old staging and extract
if (Test-Path $STAGING_DIR) {
    Remove-Item $STAGING_DIR -Recurse -Force
}
Expand-Archive -Path $ZIP_PATH -DestinationPath "C:\ProgramData\aio\tmp_extract" -Force

# GitHub zips contain a top-level folder like "aio-main/"
$extracted = Get-ChildItem "C:\ProgramData\aio\tmp_extract" | Select-Object -First 1
Move-Item $extracted.FullName $STAGING_DIR -Force
Remove-Item "C:\ProgramData\aio\tmp_extract" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ZIP_PATH -Force -ErrorAction SilentlyContinue
Write-Host "       Extracted to $STAGING_DIR"

# ── Stop services ─────────────────────────────────────────
Write-Host "[2/6] Stopping services..." -ForegroundColor Cyan
$services = @("AIOWatchdog", "AIOAgent")
foreach ($svc in $services) {
    try {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -eq "Running") {
            Stop-Service -Name $svc -Force
            Write-Host "       Stopped $svc"
        }
    } catch {
        Write-Host "       $svc not found (skipping)" -ForegroundColor Yellow
    }
}

# ── Deploy kiosk files ────────────────────────────────────
Write-Host "[3/6] Deploying kiosk files..." -ForegroundColor Cyan

$kioskSrc = "$STAGING_DIR\client\aio"
$kioskDst = "$INSTALL_DIR\kiosk"

if (-not (Test-Path $kioskDst)) {
    New-Item -ItemType Directory -Path $kioskDst -Force | Out-Null
}

# Copy all .py files
Get-ChildItem -Path $kioskSrc -Filter "*.py" | ForEach-Object {
    Copy-Item $_.FullName -Destination $kioskDst -Force
    Write-Host "       -> kiosk\$($_.Name)"
}

# Copy images
$imgSrc = "$kioskSrc\img"
$imgDst = "$kioskDst\img"
if (Test-Path $imgSrc) {
    if (-not (Test-Path $imgDst)) {
        New-Item -ItemType Directory -Path $imgDst -Force | Out-Null
    }
    Get-ChildItem $imgSrc -Exclude ".DS_Store" | Copy-Item -Destination $imgDst -Recurse -Force
    Write-Host "       -> kiosk\img\ (all assets)"
}

# Copy videos
$vidsSrc = "$kioskSrc\vids"
$vidsDst = "$kioskDst\vids"
if (Test-Path $vidsSrc) {
    if (-not (Test-Path $vidsDst)) {
        New-Item -ItemType Directory -Path $vidsDst -Force | Out-Null
    }
    Get-ChildItem $vidsSrc -Exclude ".DS_Store" | Copy-Item -Destination $vidsDst -Recurse -Force
    Write-Host "       -> kiosk\vids\ (all videos)"
}

# ── Deploy agent files ────────────────────────────────────
Write-Host "[4/6] Deploying agent files..." -ForegroundColor Cyan

$agentDst = "$INSTALL_DIR\agent"
if (-not (Test-Path $agentDst)) {
    New-Item -ItemType Directory -Path $agentDst -Force | Out-Null
}

$watchdogSrc = "$STAGING_DIR\client\watchdog.py"
if (Test-Path $watchdogSrc) {
    Copy-Item $watchdogSrc -Destination $agentDst -Force
    Write-Host "       -> agent\watchdog.py"
}

# ── Update Python dependencies ─────────────────────────────
Write-Host "[5/6] Updating Python dependencies..." -ForegroundColor Cyan
if (Test-Path $PYTHON_EXE) {
    & $PYTHON_EXE -m pip install --upgrade PyQt5 PyQtWebEngine psutil requests websockets --quiet 2>&1 | Out-Null
    Write-Host "       Dependencies up to date"
} else {
    Write-Host "       Python not found at $PYTHON_EXE (skipping)" -ForegroundColor Yellow
}

# ── Restart services ───────────────────────────────────────
Write-Host "[6/6] Restarting services..." -ForegroundColor Cyan
foreach ($svc in @("AIOAgent", "AIOWatchdog")) {
    try {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s) {
            Start-Service -Name $svc
            Write-Host "       Started $svc"
        }
    } catch {
        Write-Host "       Failed to start $svc" -ForegroundColor Yellow
    }
}

# ── Done ───────────────────────────────────────────────────
$version = "unknown"
$versionFile = "$INSTALL_DIR\config\version.json"
if (Test-Path $versionFile) {
    try {
        $v = Get-Content $versionFile -Raw | ConvertFrom-Json
        $version = $v.version
    } catch {}
}

Write-Host ""
Write-Host "AIO deployed successfully (v$version)." -ForegroundColor Green
Write-Host "Install: $INSTALL_DIR"
