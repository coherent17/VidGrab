# Build VidGrab on Windows (works from WSL UNC paths in PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== VidGrab - Windows Build ===" -ForegroundColor Cyan
Write-Host "Project dir: $(Get-Location)"
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python not found. Install Python 3.10+ and check 'Add to PATH'." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "requirements.txt")) {
    Write-Host "ERROR: requirements.txt not found. Run this from the project folder." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path "assets\icon.ico")) {
    python scripts\generate_icon.py
}

$winFfmpeg = "ffmpeg\win\ffmpeg.exe"
if (-not (Test-Path $winFfmpeg) -and -not (Test-Path "ffmpeg\ffmpeg.exe")) {
    Write-Host ""
    Write-Host "WARNING: ffmpeg\win\ffmpeg.exe not found." -ForegroundColor Yellow
    Write-Host "The exe will still build, but MP3 and merged MP4 downloads"
    Write-Host "need ffmpeg embedded. Drop ffmpeg.exe + ffprobe.exe into ffmpeg\win\."
    Write-Host ""
}

pyinstaller VidGrab.spec --noconfirm

if (-not (Test-Path "dist\VidGrab.exe")) {
    Write-Host "ERROR: dist\VidGrab.exe was not created." -ForegroundColor Red
    exit 1
}

$zip = "dist\VidGrab.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\VidGrab.exe" -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Green
Write-Host "  $(Join-Path (Get-Location) 'dist\VidGrab.exe')  (single self-contained exe, ffmpeg embedded)"
Write-Host "  $(Join-Path (Get-Location) $zip)  (zip to share)"
