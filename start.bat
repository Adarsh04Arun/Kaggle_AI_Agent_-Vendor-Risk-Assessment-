@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Vendor Risk Assessor — Launcher
color 0B

echo.
echo   ╔══════════════════════════════════════════════════════╗
echo   ║     🛡️  Automated Vendor Risk Assessor — Launcher    ║
echo   ╚══════════════════════════════════════════════════════╝
echo.

:: ── Load .env to read AGENT_MODEL ──────────────────────────────────
set "AGENT_MODEL="
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" (
            if "%%A"=="AGENT_MODEL" set "AGENT_MODEL=%%B"
        )
    )
)
if "%AGENT_MODEL%"=="" set "AGENT_MODEL=gemini-2.0-flash-lite"

echo   [*] Configured model: %AGENT_MODEL%
echo.

:: ── Check Python venv ──────────────────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo   [✓] Virtual environment found
    call venv\Scripts\activate.bat
) else (
    echo   [!] No venv found. Using system Python.
)

:: ── Check if using Ollama ──────────────────────────────────────────
echo %AGENT_MODEL% | findstr /i "ollama/" >nul 2>&1
if %errorlevel%==0 (
    echo   [*] Ollama model detected — checking Ollama server...

    :: Locate ollama.exe (not always in PATH on Windows)
    set "OLLAMA_EXE="
    where ollama >nul 2>&1 && set "OLLAMA_EXE=ollama"
    if "!OLLAMA_EXE!"=="" (
        if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
            set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
        )
    )
    if "!OLLAMA_EXE!"=="" (
        echo   [!] ollama.exe not found. Checking if server is running anyway...
    )

    :: Check if Ollama is running
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo   [✗] Ollama is NOT running!
        echo       Please start Ollama first:
        echo         - Open the Ollama app, or
        echo         - Run: ollama serve
        echo.
        pause
        exit /b 1
    )
    echo   [✓] Ollama server is running

    :: Extract model name (strip "ollama/" prefix)
    set "OLLAMA_MODEL=%AGENT_MODEL:ollama/=%"

    :: Check if model is pulled (only if we found ollama.exe)
    if not "!OLLAMA_EXE!"=="" (
        "!OLLAMA_EXE!" list 2>nul | findstr /i "!OLLAMA_MODEL!" >nul 2>&1
        if !errorlevel! neq 0 (
            echo   [!] Model "!OLLAMA_MODEL!" not found locally. Pulling now...
            echo.
            "!OLLAMA_EXE!" pull !OLLAMA_MODEL!
            if !errorlevel! neq 0 (
                echo.
                echo   [✗] Failed to pull model. Check the model name and try again.
                pause
                exit /b 1
            )
        )
        echo   [✓] Model "!OLLAMA_MODEL!" is available
    )
) else (
    echo   [*] Using cloud model: %AGENT_MODEL%
)

echo.
echo   ─────────────────────────────────────────────────────────
echo.

:: ── Menu ───────────────────────────────────────────────────────────
echo   How would you like to run?
echo.
echo     [1] 🌐  Web Dashboard  (http://localhost:8000)
echo     [2] ⌨️   CLI Assessment (enter vendor names)
echo     [3] 🧪  Quick Test     (assess "Microsoft" as a demo)
echo     [4] ❌  Exit
echo.
set /p choice="   Select [1-4]: "

if "%choice%"=="1" goto :web
if "%choice%"=="2" goto :cli
if "%choice%"=="3" goto :test
if "%choice%"=="4" goto :exit

echo   Invalid choice. Please try again.
pause
goto :exit

:: ── Web Dashboard ──────────────────────────────────────────────────
:web
echo.
echo   [*] Starting Web Dashboard...
echo   [*] Open http://localhost:8000 in your browser
echo   [*] Press Ctrl+C to stop
echo.
python run.py
goto :exit

:: ── CLI Assessment ─────────────────────────────────────────────────
:cli
echo.
set /p vendors="   Enter vendor names (comma-separated): "
if "%vendors%"=="" (
    echo   [!] No vendors entered. Exiting.
    goto :exit
)

:: Replace commas with spaces and wrap each in quotes
set "cmd_vendors="
for %%V in (%vendors%) do (
    set "v=%%V"
    :: Trim leading spaces
    for /f "tokens=* delims= " %%a in ("!v!") do set "v=%%a"
    set "cmd_vendors=!cmd_vendors! "!v!""
)

echo.
echo   [*] Assessing:%cmd_vendors%
echo.
python cli.py assess %cmd_vendors%
echo.
pause
goto :exit

:: ── Quick Test ─────────────────────────────────────────────────────
:test
echo.
echo   [*] Running quick test assessment for "Microsoft"...
echo.
python cli.py assess "Microsoft"
echo.
pause
goto :exit

:: ── Exit ───────────────────────────────────────────────────────────
:exit
echo.
echo   Goodbye!
endlocal
