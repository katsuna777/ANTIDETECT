#!/usr/bin/env python3
"""Entry point for the CLI (equivalent to the installed ``app`` command)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app.cli.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())