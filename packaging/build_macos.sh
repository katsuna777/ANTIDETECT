#!/usr/bin/env bash
# Build Antidetect for this Mac - the same script CI runs: release/Antidetect-<version>-macos-<arm64|x64>.dmg
# Usage: bash packaging/build_macos.sh [--no-smoke] [--qt-platform offscreen]
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYBIN:-python3}"

"${PY}" -m pip install -e ".[build]"
exec "${PY}" packaging/build.py "$@"
