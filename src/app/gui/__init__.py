"""PySide6 desktop shell for the Antidetect application (Stage 1).

The GUI is a thin presentation layer: it talks to the application services
exclusively through the shared :class:`app.di.Container` (the same composition
root the CLI uses) and never touches SQLite, Chromium or the repositories
directly. Two entry points are provided:

* ``python -m app.gui`` — bootstraps the Container and opens the main window;
* :func:`app.gui.app.run_app` — injects an existing Container (used by tests).
"""