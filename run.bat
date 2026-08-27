@echo off
title YT-DLP Zero-Touch
:: Mirror console output (including ffmpeg's own stderr, which yt-dlp lets
:: inherit the parent console instead of routing through the app's log
:: panel) to app.log, so a crash is diagnosable after this window closes.
powershell -NoProfile -Command "& python '%~dp0app.py' 2>&1 | Tee-Object -FilePath '%~dp0app.log'; exit $LASTEXITCODE"
if errorlevel 1 (
    echo.
    echo  [!] App crashed or Python not found.
    echo  Run install.bat first if you haven't already.
    echo.
    pause
)
