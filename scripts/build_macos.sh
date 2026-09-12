#!/usr/bin/env bash
# Build Antidetect.app + Antidetect.dmg on macOS.
# Usage: bash scripts/build_macos.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="${ROOT}/build-macos.spec"
PY="${PYBIN:-python3}"

if [ ! -f "${SPEC}" ]; then
  echo "spec not found: ${SPEC}" >&2
  exit 1
fi

"${PY}" -m pip install -r "${ROOT}/requirements-build.txt"
"${PY}" "${ROOT}/scripts/check_build_env.py"
mkdir -p "${ROOT}/release"
rm -rf "${ROOT}/dist/Antidetect.app" "${ROOT}/release/Antidetect.dmg"

cd "${ROOT}"
"${PY}" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${ROOT}/dist" \
  --workpath "${ROOT}/build" \
  "${SPEC}"

if [ ! -d "${ROOT}/dist/Antidetect.app" ]; then
  echo "ERROR: dist/Antidetect.app was not created" >&2
  exit 1
fi

"${PY}" "${ROOT}/scripts/validate_macos.py" --app "${ROOT}/dist/Antidetect.app"

VOLNAME="Antidetect"
DMG="${ROOT}/release/Antidetect.dmg"
STAGE="$(mktemp -d)"
cp -R "${ROOT}/dist/Antidetect.app" "${STAGE}/"
ln -s /Applications "${STAGE}/Applications" || true
hdiutil create -volname "${VOLNAME}" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}"
rm -rf "${STAGE}"

"${PY}" "${ROOT}/scripts/validate_macos.py" --dmg "${DMG}"
echo "OK: ${DMG}"
