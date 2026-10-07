"""Builds the in-page JavaScript from the packaged template."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from antidetect.infrastructure.stealth.spec import StealthSpec, spec_json

_TEMPLATE = Path(__file__).with_name("js") / "payload.js"


@lru_cache(maxsize=1)
def _template() -> str:
    try:
        return _TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        # PyInstaller one-file builds extract data next to the module tree.
        from antidetect.runtime import resource_path

        return resource_path("antidetect", "infrastructure", "stealth", "js", "payload.js").read_text(encoding="utf-8")


def build_payload(spec: StealthSpec) -> str:
    """Self-contained script for ``addScriptToEvaluateOnNewDocument`` / workers."""
    return _template().replace("__CFG__", spec_json(spec)).replace("__TOKEN__", spec.token)
