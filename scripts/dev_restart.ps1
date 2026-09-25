# ModelGate local dev instance restart (PID-file based).
# NEVER use `Stop-Process -Name python` or `taskkill /F /IM python.exe` on this
# machine — other python services (quant_platform etc.) run here and will die.
#
# Usage:
#   powershell -File scripts\dev_restart.ps1              # stop old + start new
#   powershell -File scripts\dev_restart.ps1 -StopOnly    # stop only
#
# Env override: DATABASE_URL (defaults to the local repro DB).

param(
    [switch]$StopOnly,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $env:TEMP 'modelgate_dev.pid'
$LogFile = Join-Path $env:TEMP 'modelgate_dev.log'
$ErrFile = Join-Path $env:TEMP 'modelgate_dev.err'

function Stop-DevInstance {
    # 1) PID file
    if (Test-Path $PidFile) {
        $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($oldPid -match '^\d+$') {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
            if ($proc -and $proc.CommandLine -like '*app.main*') {
                Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
                Write-Host "Stopped dev instance PID $oldPid (pidfile)"
            }
        }
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }

    # 2) Fallback: anything LISTENING on our port, verified to be this project
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $listeners) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -like '*app.main*') {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped dev instance PID $($conn.OwningProcess) (port $Port)"
        } elseif ($proc) {
            Write-Warning "Port $Port is held by PID $($conn.OwningProcess) ($($proc.Name)) which is NOT this project — left alone."
        }
    }
}

Stop-DevInstance
if ($StopOnly) { return }

if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = 'postgresql+asyncpg://postgres:Zaq1%403edc@10.100.2.148:5432/modelgate_repro'
}

# The dev instance must use the project venv (distinct path, never a name-kill target)
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }

$proc = Start-Process -FilePath $Python `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile `
    -WindowStyle Hidden -PassThru
Set-Content -Path $PidFile -Value $proc.Id
Write-Host "Started dev instance PID $($proc.Id) on port $Port (pidfile: $PidFile)"
