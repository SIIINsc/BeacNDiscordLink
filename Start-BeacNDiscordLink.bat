@echo off
title BeacNDiscordLink - BEACN Mix Create to Discord Sync
cd /d "%~dp0"

:: Check for Administrator privileges (needed to read BEACN.exe live hardware state)
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges to read live BEACN Mix Create state...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    python beacn_discord_link.py %*
    goto :end
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 beacn_discord_link.py %*
    goto :end
)

echo [ERROR] Python 3 was not found on your PATH.
echo Please install Python 3 from https://www.python.org/downloads/ and check "Add Python to PATH".
pause

:end
if %errorlevel% neq 0 pause
