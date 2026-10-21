@echo off
title Install BeacNDiscordLink Auto-Start
cd /d "%~dp0"

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\BeacNDiscordLink.lnk"
set "TARGET_VBS=%~dp0Start-Hidden.vbs"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%TARGET_VBS%\"'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'BeacNDiscordLink Background Sync'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo ====================================================================
    echo  SUCCESS: BeacNDiscordLink will now start automatically with Windows!
    echo  Shortcut created at:
    echo  %SHORTCUT_PATH%
    echo ====================================================================
) else (
    echo [ERROR] Could not create startup shortcut.
)
pause
