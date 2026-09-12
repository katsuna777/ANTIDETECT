"""Allow ``python -m app.gui`` to launch the desktop shell."""

import sys
from pathlib import Path

# Mirrors main.py: make ``src`` importable even without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.gui.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())