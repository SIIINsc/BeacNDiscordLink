@echo off
title Uninstall BeacNDiscordLink Auto-Start
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\BeacNDiscordLink.lnk"

if exist "%SHORTCUT_PATH%" (
    del /f /q "%SHORTCUT_PATH%"
    echo Removed BeacNDiscordLink from Windows Startup.
) else (
    echo BeacNDiscordLink was not found in Windows Startup.
)
pause
