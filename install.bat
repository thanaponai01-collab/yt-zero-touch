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
echo  [1/6] Checking Python...
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
echo  [2/6] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo    Done.

:: ── 3. Install Python packages ───────────────────────────────────────────────
echo.
echo  [3/6] Installing Python packages (yt-dlp, playwright)...
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
echo  [4/6] Installing Playwright Chromium browser (~200 MB)...
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

:: ── 5. Set up the YouTube PO Token provider ──────────────────────────────────
:: Without this, YouTube's anti-bot check (the "GVS PO Token" 403 / login wall)
:: forces a fresh cookies.txt export every time it flags the session. This
:: builds the local token generator once so downloads never need cookies for it.
echo.
echo  [5/6] Setting up YouTube PO Token provider (avoids repeat login walls)...
set "POT_DIR=%USERPROFILE%\bgutil-ytdlp-pot-provider"
where git >nul 2>&1
if errorlevel 1 (
    echo    [SKIPPED] git not found — install git, then re-run install.bat.
    echo    Without this, YouTube may repeatedly demand fresh cookies.txt exports.
    goto :ffmpeg
)
where node >nul 2>&1
if errorlevel 1 (
    echo    [SKIPPED] Node.js not found — install from https://nodejs.org, then re-run install.bat.
    echo    Without this, YouTube may repeatedly demand fresh cookies.txt exports.
    goto :ffmpeg
)
if exist "%POT_DIR%\server\build\generate_once.js" (
    echo    Already set up.
    goto :ffmpeg
)
if not exist "%POT_DIR%" (
    git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "%POT_DIR%" >nul 2>&1
)
pushd "%POT_DIR%\server"
call npm install >nul 2>&1
call npx tsc
popd
if exist "%POT_DIR%\server\build\generate_once.js" (
    echo    Done.
) else (
    echo    [WARNING] Build did not produce generate_once.js — see %POT_DIR%\server\README.md
    echo    Without this, YouTube may repeatedly demand fresh cookies.txt exports.
)

:ffmpeg
:: ── 6. Check FFmpeg ──────────────────────────────────────────────────────────
echo.
echo  [6/6] Checking FFmpeg...
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
