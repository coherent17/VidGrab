@echo off
setlocal enabledelayedexpansion

REM pushd maps \\wsl.localhost\... UNC paths to a temp drive letter (Z: etc.)
pushd "%~dp0" || (
    echo ERROR: Could not enter project directory: %~dp0
    exit /b 1
)

echo === VidGrab - Windows Build ===
echo Project dir: %CD%
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and check "Add to PATH".
    popd
    exit /b 1
)

if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found in %CD%
    echo Do not run this from C:\Windows. Use the project folder.
    popd
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create .venv
        popd
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
if errorlevel 1 goto :fail

pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist "assets\icon.ico" (
    python scripts\generate_icon.py
    if errorlevel 1 goto :fail
)

if not exist "ffmpeg\ffmpeg.exe" (
    echo.
    echo WARNING: ffmpeg\ffmpeg.exe not found.
    echo MP3 downloads and most MP4 merges need ffmpeg.
    echo Download from https://www.gyan.dev/ffmpeg/builds/ ^(ffmpeg-release-essentials.zip^)
    echo and place ffmpeg.exe + ffprobe.exe in the ffmpeg\ folder.
    echo.
)

pyinstaller VidGrab.spec --noconfirm
if errorlevel 1 goto :fail

if not exist "dist\VidGrab.exe" (
    echo ERROR: Build failed — dist\VidGrab.exe was not created.
    goto :fail
)

set "ZIP=dist\VidGrab.zip"
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\VidGrab.exe' -DestinationPath '%ZIP%' -CompressionLevel Optimal"

echo.
echo Build complete:
echo   %CD%\dist\VidGrab.exe   ^(single self-contained exe, ffmpeg embedded^)
echo   %CD%\%ZIP%                     ^(zip to share^)
echo.
popd
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. See errors above.
popd
pause
exit /b 1
