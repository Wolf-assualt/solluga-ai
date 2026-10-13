@echo off
rem ==============================================================================
rem  Sollunga AI - Run Bot & Web Dashboard Together (Windows)
rem  Windows equivalent of run.sh
rem
rem  - Starts the FastAPI web dashboard on port 8000 (minimized window)
rem  - Optionally starts a Cloudflare quick tunnel when WhatsApp is configured
rem  - Starts the Telegram bot in its own window
rem  - Press any key in THIS window to stop all services
rem
rem  Note: closing this window (or Ctrl+C) skips cleanup - use the key prompt
rem        to stop all services cleanly.
rem ==============================================================================

chcp 65001 >nul 2>&1
setlocal

rem Change to the project directory wherever this script is called from
cd /d "%~dp0"

rem Check virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [X] Virtual environment .venv not found!
    echo     On Windows run: python -m venv .venv
    echo     Then:           .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem Project-local log folder (relative paths keep quoting simple with spaced dirs)
if not exist "logs" mkdir "logs"

echo ==========================================================
echo  Starting Sollunga AI Services...
echo ==========================================================

rem ---- Web Dashboard on port 8000 -------------------------------------------
echo [Web] Starting Web Dashboard at: http://localhost:8000
echo       (Owner password: check DASHBOARD_PASSWORD in .env)
start "Sollunga Web" /min cmd /c ".venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 8000 > logs\web.log 2>&1"

rem Give the web server a moment to bind the port before the tunnel starts
timeout /t 2 /nobreak >nul

rem ---- Optional: Cloudflare quick tunnel, ONLY if WhatsApp is configured ----
set "WA_OK=1"
findstr /r /b /c:"WHATSAPP_PHONE_NUMBER_ID=." .env >nul 2>&1 || set "WA_OK="
findstr /r /b /c:"WHATSAPP_ACCESS_TOKEN=." .env >nul 2>&1 || set "WA_OK="
if not defined WA_OK goto :no_tunnel
if not exist "bin\cloudflared.exe" goto :no_tunnel

echo [TUN] WhatsApp configured - starting public tunnel for webhook...
start "Sollunga Tunnel" /min cmd /c "bin\cloudflared.exe tunnel --url http://localhost:8000 > logs\tunnel.log 2>&1"

rem Wait for the quick-tunnel URL to appear in the log (up to 15 seconds)
set "TUNNEL_URL="
set /a TRIES=0
:waiturl
if %TRIES% geq 15 goto :tunnel_timeout
timeout /t 1 /nobreak >nul
for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "(Select-String -Path logs\tunnel.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1).Matches.Value"`) do set "TUNNEL_URL=%%u"
if defined TUNNEL_URL goto :tunnel_found
set /a TRIES+=1
goto :waiturl

:tunnel_found
echo [TUN] Public URL ready: %TUNNEL_URL%
goto :summary

:tunnel_timeout
echo [!!]  Tunnel URL not detected within 15s - check logs\tunnel.log
goto :summary

:no_tunnel
echo [i]   WhatsApp not configured (or bin\cloudflared.exe missing) - Telegram-only, no tunnel.

:summary
echo.
echo [OK]  All Sollunga AI services are running!
echo    - Local Web Dashboard: http://localhost:8000
if not defined TUNNEL_URL goto :summary_bot
echo    - Public Webhook URL:  %TUNNEL_URL%/whatsapp/webhook
echo      Paste it in Meta Developer Console - WhatsApp - Configuration - Webhook
:summary_bot
echo    - Telegram Bot:        Active
echo.
echo  Press any key in THIS window to stop all services...
pause >nul

:cleanup
echo.
echo [..]  Stopping all Sollunga AI services...
taskkill /F /T /FI "WINDOWTITLE eq Sollunga Web*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Sollunga Tunnel*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Sollunga Bot*" >nul 2>&1
rem Safety net: free port 8000 and stop any stray cloudflared
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"TCP.*:8000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
taskkill /F /IM cloudflared.exe >nul 2>&1
echo [OK]  All services stopped.
endlocal
exit /b 0
