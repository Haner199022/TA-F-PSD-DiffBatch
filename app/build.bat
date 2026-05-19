@echo off
REM =====================================================================
REM TA-F PSD DiffBatch — One-click Windows build pipeline (v1.5.0+)
REM
REM Run from this folder:  build.bat
REM
REM Pipeline:
REM   [1/8] Clean  build\ dist\
REM   [2/8] Install pinned deps from requirements.lock.txt
REM   [3/8] Lint   (ruff)
REM   [4/8] Test   (pytest)
REM   [5/8] Render version_info.txt from app/_version.py
REM   [6/8] PyInstaller
REM   [7/8] Inno Setup compile
REM   [8/8] Smoke test the produced .exe
REM
REM Any step failing aborts the run. The shell stays open (pause) so the
REM error is visible — don't close until you've read it.
REM
REM Output:
REM   dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe   (portable folder)
REM   dist\installer\TA-F-PSD-DiffBatch-Setup-<VER>.exe (single installer)
REM =====================================================================

setlocal enabledelayedexpansion

echo.
echo ========================================
echo   TA-F PSD DiffBatch - Windows build
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

REM ---------------------------------------------------------------------
echo [1/8] Cleaning build/ dist/...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo     done.

REM ---------------------------------------------------------------------
echo.
echo [2/8] Installing pinned deps (requirements.lock.txt)...
python -m pip install --upgrade pip >nul
if not exist requirements.lock.txt (
    echo ERROR: requirements.lock.txt missing.
    echo        Regenerate: pip install -r requirements.txt ^&^& pip freeze ^> requirements.lock.txt
    pause
    exit /b 1
)
python -m pip install -r requirements.lock.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Check the errors above.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo [3/8] Lint (ruff)...
python -m ruff check .
if errorlevel 1 (
    echo ERROR: lint failed. Fix the issues above or run `python -m ruff check --fix .`
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo [4/8] Test (pytest)...
python -m pytest tests/ -q
if errorlevel 1 (
    echo ERROR: tests failed. A red build must not ship.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo [5/8] Rendering version_info.txt from _version.py...
python ..\tools\render_version.py
if errorlevel 1 (
    echo ERROR: version render failed.
    pause
    exit /b 1
)
REM Capture the version so Inno Setup's GetEnv("APP_VERSION") can find it.
for /f "delims=" %%v in ('python -c "from _version import __version__; print(__version__)"') do set APP_VERSION=%%v
echo     APP_VERSION=!APP_VERSION!

REM ---------------------------------------------------------------------
echo.
echo [6/8] PyInstaller...
python -m PyInstaller "TA-F PSD DiffBatch.spec" --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See log above.
    pause
    exit /b 1
)
if not exist "dist\TA-F PSD DiffBatch\TA-F PSD DiffBatch.exe" (
    echo ERROR: PyInstaller reported success but exe is missing.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo [7/8] Inno Setup compile (ISCC)...
set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if "!ISCC!"=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" if exist "D:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=D:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    echo ERROR: ISCC.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php
    echo        Default install path: "C:\Program Files (x86)\Inno Setup 6\"
    pause
    exit /b 1
)
"!ISCC!" /Qp installer.iss
if errorlevel 1 (
    echo ERROR: ISCC failed. See output above.
    pause
    exit /b 1
)
if not exist "dist\installer\TA-F-PSD-DiffBatch-Setup-!APP_VERSION!.exe" (
    echo ERROR: ISCC reported success but installer .exe is missing.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo [8/8] Smoke test (launch exe for 3s)...
python ..\tools\smoke_test_exe.py
if errorlevel 1 (
    echo ERROR: smoke test failed. The .exe was produced but won't start.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------
echo.
echo ========================================
echo   Build OK - v!APP_VERSION!
echo ========================================
echo.
echo   Portable folder:
echo     dist\TA-F PSD DiffBatch\
echo.
echo   Installer:
echo     dist\installer\TA-F-PSD-DiffBatch-Setup-!APP_VERSION!.exe
echo.
echo   Next steps:
echo     1. Manual smoke: double-click the installer on a clean VM.
echo     2. Upload installer to \\nas\TA-F\PS-BATCH\releases\
echo     3. Update \\nas\TA-F\PS-BATCH\latest.json (version + sha256 + changelog)
echo.

endlocal
pause
