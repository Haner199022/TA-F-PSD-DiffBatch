@echo off
REM TA-F PSD DiffBatch — Windows one-click build
REM Requires: Python 3.10+ on PATH; pip
REM Optional: Inno Setup 6 (for the installer step)
REM
REM Run from this folder by double-clicking, or:  build.bat
REM
REM Output:
REM   dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe   (portable folder build)
REM   dist\installer\TA-F-PSD-DiffBatch-Setup-1.4.exe   (after Inno Setup compile)

setlocal enabledelayedexpansion

echo.
echo ========================================
echo   TA-F PSD DiffBatch 1.4 - Windows Build
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found on PATH.
    echo        Install Python 3.10+ from https://www.python.org/downloads/windows/
    echo        IMPORTANT: tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

echo [1/5] Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo     done.

echo.
echo [2/5] Installing build dependencies (pyinstaller + project requirements)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Check the requirements.txt errors above.
    pause
    exit /b 1
)

echo.
echo [3/5] Building with PyInstaller ("TA-F PSD DiffBatch.spec")...
python -m PyInstaller "TA-F PSD DiffBatch.spec" --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See log above.
    pause
    exit /b 1
)

echo.
echo [4/5] Verifying output...
if exist "dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe" (
    echo     dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe  ^(OK^)
) else (
    echo ERROR: TA-F PSD DiffBatch.exe was not produced. See PyInstaller log above.
    pause
    exit /b 1
)

echo.
echo [5/5] Done.
echo ========================================
echo   Build complete.
echo ========================================
echo.
echo   Portable distribution: zip the entire folder
echo       dist\TA-F PSD DiffBatch\
echo   and send it to your user. They double-click "TA-F PSD DiffBatch.exe".
echo.
echo   Optional installer (single .exe): open installer.iss in Inno Setup 6
echo       (https://jrsoftware.org/isdl.php) and press F9 to compile.
echo       Output: dist\installer\TA-F-PSD-DiffBatch-Setup-1.4.exe
echo.

endlocal
pause
