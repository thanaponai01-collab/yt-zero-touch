@echo off
title YT-DLP Zero-Touch
python "%~dp0app.py"
if errorlevel 1 (
    echo.
    echo  [!] App crashed or Python not found.
    echo  Run install.bat first if you haven't already.
    echo.
    pause
)
