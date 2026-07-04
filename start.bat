@echo off
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8
title Vendor Risk Assessor  Launcher
color 0B

echo.
echo   +------------------------------------------------------+
echo   ^|      Automated Vendor Risk Assessor - Launcher       ^|
echo   +------------------------------------------------------+
echo.

:: -- Load .env to read the two models -------------------------------
::    AGENT_MODEL      -> CLI (local Ollama)
::    WEB_AGENT_MODEL  -> Web dashboard (Gemini)
set "AGENT_MODEL="
set "WEB_AGENT_MODEL="
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" (
            if "%%A"=="AGENT_MODEL" set "AGENT_MODEL=%%B"
            if "%%A"=="WEB_AGENT_MODEL" set "WEB_AGENT_MODEL=%%B"
        )
    )
)
if "%AGENT_MODEL%"=="" set "AGENT_MODEL=ollama_chat/llama3.1"
if "%WEB_AGENT_MODEL%"=="" set "WEB_AGENT_MODEL=gemini-2.0-flash-lite"

echo   [*] CLI model (Ollama) : %AGENT_MODEL%
echo   [*] Web model (Gemini) : %WEB_AGENT_MODEL%
echo.

:: -- Detect whether the CLI model is an Ollama model ----------------
::    Matches both "ollama/" and "ollama_chat/" prefixes.
set "IS_OLLAMA="
echo %AGENT_MODEL% | findstr /i "ollama" >nul 2>&1 && set "IS_OLLAMA=1"
if defined IS_OLLAMA (
    set "OLLAMA_MODEL=%AGENT_MODEL%"
    set "OLLAMA_MODEL=!OLLAMA_MODEL:ollama_chat/=!"
    set "OLLAMA_MODEL=!OLLAMA_MODEL:ollama/=!"
)

:: -- Check Python venv ----------------------------------------------
if exist "venv\Scripts\activate.bat" (
    echo   [OK] Virtual environment found
    call venv\Scripts\activate.bat
) else (
    echo   [!] No venv found. Using system Python.
)

echo.
echo   ---------------------------------------------------------
echo.

:: -- Menu -----------------------------------------------------------
echo   How would you like to run?
echo.
echo     [1] WEB    Dashboard   (Gemini)  http://localhost:8000
echo     [2] WEB    Dashboard   (Ollama)  http://localhost:8000  local, no API key
echo     [3] CLI    Assessment  (Ollama)  enter vendor names
echo     [4] TEST   Quick Test  (Ollama)  assess "Microsoft"
echo     [5] DOCTOR Health Check (Ollama + Gemini + NVD + search)
echo     [6] EXIT
echo.
set /p choice="   Select [1-6]: "

if "%choice%"=="1" goto :web
if "%choice%"=="2" goto :webollama
if "%choice%"=="3" goto :cli
if "%choice%"=="4" goto :test
if "%choice%"=="5" goto :doctor
if "%choice%"=="6" goto :exit

echo   Invalid choice. Please try again.
pause
goto :exit

:: -- Web Dashboard (Gemini — no Ollama needed) ----------------------
:web
echo.
echo   [*] Starting Web Dashboard (uses Gemini via GOOGLE_API_KEY)...
echo   [*] Open http://localhost:8000 in your browser
echo   [*] Press Ctrl+C to stop
echo.
python run.py
goto :exit

:: -- Web Dashboard on local Ollama (no API key / no quota) -----------
:webollama
if not defined IS_OLLAMA goto :webollama_notollama
call :ensure_ollama
if errorlevel 1 goto :exit
:: Point the web interface at the local Ollama model for this run only.
set "WEB_AGENT_MODEL=%AGENT_MODEL%"
echo.
echo   [*] Starting Web Dashboard on local Ollama (%WEB_AGENT_MODEL%)...
echo   [*] No API key or quota needed. Open http://localhost:8000
echo   [*] Note: reports may be scored deterministically if the local
echo       model can't emit clean JSON. Press Ctrl+C to stop.
echo.
python run.py
goto :exit

:webollama_notollama
echo.
echo   [!] AGENT_MODEL is not an Ollama model: %AGENT_MODEL%
echo       Set AGENT_MODEL=ollama_chat/llama3.1 in .env to use this option.
pause
goto :exit

:: -- CLI Assessment -------------------------------------------------
:cli
call :ensure_ollama
if errorlevel 1 goto :exit
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

:: -- Quick Test -----------------------------------------------------
:test
call :ensure_ollama
if errorlevel 1 goto :exit
echo.
echo   [*] Running quick test assessment for "Microsoft"...
echo.
python cli.py assess "Microsoft"
echo.
pause
goto :exit

:: -- Doctor (health check) ------------------------------------------
:doctor
echo.
echo   [*] Running system health check...
echo.
python cli.py doctor
echo.
pause
goto :exit

:: -- Subroutine: make sure Ollama is up and the model is pulled -----
:ensure_ollama
if not defined IS_OLLAMA exit /b 0

curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [FAIL] Ollama is NOT running!
    echo       Start it first:  ollama serve   -- or open the Ollama app
    echo.
    pause
    exit /b 1
)
echo   [OK] Ollama server is running

:: Locate ollama.exe (not always on PATH)
set "OLLAMA_EXE="
where ollama >nul 2>&1 && set "OLLAMA_EXE=ollama"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

if defined OLLAMA_EXE (
    "!OLLAMA_EXE!" list 2>nul | findstr /i "!OLLAMA_MODEL!" >nul 2>&1
    if errorlevel 1 (
        echo   [!] Model "!OLLAMA_MODEL!" not found locally. Pulling now...
        echo.
        "!OLLAMA_EXE!" pull !OLLAMA_MODEL!
        if errorlevel 1 (
            echo   [FAIL] Failed to pull model. Check the name and retry.
            pause
            exit /b 1
        )
    )
    echo   [OK] Model "!OLLAMA_MODEL!" is available
)
exit /b 0

:: -- Exit -----------------------------------------------------------
:exit
echo.
echo   Goodbye!
endlocal
