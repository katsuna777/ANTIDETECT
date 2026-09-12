# Build Antidetect.exe (standalone onefile) on Windows.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$ROOT = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
$SPEC = Join-Path $ROOT "build-windows.spec"
$PY = if ($env:PYBIN) { $env:PYBIN } else { "python" }

if (-not (Test-Path $SPEC)) { Write-Error "spec not found: $SPEC"; exit 1 }

& $PY -m pip install -r (Join-Path $ROOT "requirements-build.txt")
& $PY (Join-Path $ROOT "scripts\check_build_env.py")
New-Item -ItemType Directory -Force -Path (Join-Path $ROOT "release") | Out-Null
$exe = Join-Path $ROOT "dist\Antidetect.exe"
if (Test-Path $exe) { Remove-Item $exe -Force }
$releaseExe = Join-Path $ROOT "release\Antidetect.exe"
if (Test-Path $releaseExe) { Remove-Item $releaseExe -Force }

Push-Location $ROOT
& $PY -m PyInstaller --noconfirm --clean --distpath (Join-Path $ROOT "dist") --workpath (Join-Path $ROOT "build") $SPEC
Pop-Location

if (-not (Test-Path $exe)) { Write-Error "ERROR: dist\Antidetect.exe was not created"; exit 1 }

& $PY (Join-Path $ROOT "scripts\validate_windows.py") --exe $exe

Copy-Item $exe $releaseExe -Force
& $PY (Join-Path $ROOT "scripts\validate_windows.py") --exe $releaseExe
Write-Host "OK: $releaseExe"
