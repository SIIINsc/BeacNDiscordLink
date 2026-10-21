@echo off
title BeacNDiscordLink - BEACN Mix Create to Discord Sync
cd /d "%~dp0"

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
