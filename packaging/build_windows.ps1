# Build Antidetect for Windows - the same script CI runs: release\Antidetect-<version>-windows-x64.exe
# Usage: powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [--no-smoke] [--qt-platform offscreen]
$ErrorActionPreference = "Stop"
$ROOT = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
$PY = if ($env:PYBIN) { $env:PYBIN } else { "python" }

Push-Location $ROOT
try {
    & $PY -m pip install -e ".[build]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    & $PY packaging\build.py @args
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
} finally {
    Pop-Location
}
