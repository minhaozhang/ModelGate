@echo off
chcp 65001 >nul
cd /d %~dp0

echo Checking if port 8765 is in use...
netstat -ano | findstr ":8765" >nul
if errorlevel 1 (
    echo Port 8765 is free, starting directly...
    goto :start_server
)

echo Port 8765 is in use, killing existing process...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8765 ^| findstr LISTENING') do (
    set PID=%%a
)
if defined PID (
    echo Found PID: %PID%, killing...
    taskkill /F /PID %PID% >nul 2>&1
)

:start_server
echo.
echo Select log level:
echo [1] INFO  (default, timeout in 5s)
echo [2] DEBUG
echo.

choice /c 12 /t 5 /d 1 /n >nul
if errorlevel 2 (
    set LOG_LEVEL=DEBUG
    echo Log level: DEBUG
) else (
    set LOG_LEVEL=INFO
    echo Log level: INFO
)

echo.
echo Starting ModelGate...
echo ========================================
py main.py

if errorlevel 1 (
    echo.
    echo ERROR: Server failed to start
    pause
)
