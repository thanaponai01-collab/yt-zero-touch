@echo off
setlocal enabledelayedexpansion
title YT-DLP Zero-Touch — Installer
color 0A

echo.
echo  ============================================================
echo    YT-DLP Zero-Touch  —  First-Time Setup
echo  ============================================================
echo.

:: ── 1. Check Python ─────────────────────────────────────────────────────────
echo  [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found!
    echo  Please install Python 3.10+ from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo    Found: %%i

:: ── 2. Upgrade pip ───────────────────────────────────────────────────────────
echo.
echo  [2/5] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo    Done.

:: ── 3. Install Python packages ───────────────────────────────────────────────
echo.
echo  [3/5] Installing Python packages (yt-dlp, playwright)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo    Done.

:: ── 4. Install Playwright Chromium browser ───────────────────────────────────
echo.
echo  [4/5] Installing Playwright Chromium browser (~200 MB)...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  [WARNING] Playwright browser install failed.
    echo  Headless browser features (Outseta/Mux sites) will not work.
    echo  You can retry later with:  python -m playwright install chromium
    echo.
) else (
    echo    Done.
)

:: ── 5. Check FFmpeg ──────────────────────────────────────────────────────────
echo.
echo  [5/5] Checking FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [WARNING] FFmpeg not found!
    echo  FFmpeg is required for merging video+audio and embedding thumbnails.
    echo.
    echo  Install options:
    echo    Option A — winget (Windows 10/11 built-in):
    echo      winget install --id Gyan.FFmpeg -s winget
    echo.
    echo    Option B — Chocolatey:
    echo      choco install ffmpeg
    echo.
    echo    Option C — Manual: https://ffmpeg.org/download.html
    echo      Extract and add the bin/ folder to your PATH.
    echo.
    echo  After installing FFmpeg, re-run this installer to verify.
) else (
    for /f "tokens=1-3" %%a in ('ffmpeg -version 2^>^&1 ^| findstr /i "ffmpeg version"') do (
        echo    Found: %%a %%b %%c
    )
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo  ============================================================
echo    Setup complete!  Run the app with:  run.bat
echo  ============================================================
echo.
pause
