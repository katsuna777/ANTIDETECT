"""PySide6 desktop shell.

The GUI is a thin presentation layer: it reaches the application services only
through the shared :class:`antidetect.container.Container` (the same composition
root the CLI uses) and never touches SQLite, Chromium or the repositories directly.

Layout: ``theme`` (tokens, QSS, icons) · ``components`` (reusable widgets) ·
``views`` (tables and their painters) · ``models`` (Qt models, read-models) ·
``pages`` (one per sidebar section) · ``dialogs`` · ``workers`` (background tasks).

Entry points: ``python -m antidetect.gui`` and :func:`antidetect.gui.app.run_app`
(used by tests, with an injected Container).
"""
