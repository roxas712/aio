#Requires -RunAsAdministrator
<#
.SYNOPSIS
    AIO Game Terminal deployment script.
    Pulls latest from GitHub and deploys to the installed kiosk location.

.DESCRIPTION
    - Clones or pulls the AIO repo into a staging directory
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
$REPO         = "https://github.com/roxas712/aio.git"
$BRANCH       = "main"
$STAGING_DIR  = "C:\ProgramData\aio\repo"
$INSTALL_DIR  = "C:\Program Files\aio"
$PYTHON_EXE   = "C:\Program Files\Python314\python.exe"

# ── Ensure staging parent exists ───────────────────────────
if (-not (Test-Path "C:\ProgramData\aio")) {
    New-Item -ItemType Directory -Path "C:\ProgramData\aio" -Force | Out-Null
}

# ── Clone or pull the repo ─────────────────────────────────
if (-not (Test-Path "$STAGING_DIR\.git")) {
    Write-Host "[1/6] Cloning repository..." -ForegroundColor Cyan
    git clone --branch $BRANCH --single-branch $REPO $STAGING_DIR
} else {
    Write-Host "[1/6] Pulling latest changes..." -ForegroundColor Cyan
    Push-Location $STAGING_DIR
    git fetch origin
    git reset --hard "origin/$BRANCH"
    Pop-Location
}

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

# ── Deploy files ───────────────────────────────────────────
Write-Host "[3/6] Deploying kiosk files..." -ForegroundColor Cyan

# Kiosk Python scripts
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
    Copy-Item "$imgSrc\*" -Destination $imgDst -Recurse -Force -Exclude ".DS_Store"
    Write-Host "       -> kiosk\img\ (all assets)"
}

# Copy videos
$vidsSrc = "$kioskSrc\vids"
$vidsDst = "$kioskDst\vids"
if (Test-Path $vidsSrc) {
    if (-not (Test-Path $vidsDst)) {
        New-Item -ItemType Directory -Path $vidsDst -Force | Out-Null
    }
    Copy-Item "$vidsSrc\*" -Destination $vidsDst -Recurse -Force -Exclude ".DS_Store"
    Write-Host "       -> kiosk\vids\ (all videos)"
}

Write-Host "[4/6] Deploying agent files..." -ForegroundColor Cyan

$agentDst = "$INSTALL_DIR\agent"
if (-not (Test-Path $agentDst)) {
    New-Item -ItemType Directory -Path $agentDst -Force | Out-Null
}

# Watchdog
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
Write-Host "Repo: $STAGING_DIR"
Write-Host "Install: $INSTALL_DIR"
