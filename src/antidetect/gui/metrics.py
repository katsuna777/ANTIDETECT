"""Sizes shared by every page, so that things which should line up do.

The first row of each page (title, counters, toolbar) is ``HEADER_HEIGHT`` tall and starts
``PAGE_MARGINS[1]`` below the top edge of the sheet; the sidebar's brand row uses the same two numbers,
so the app name sits level with the page title on every page. Controls come in two sizes: ``CONTROL_HEIGHT``
(toolbars, forms, dialogs) and ``COMPACT_HEIGHT`` (actions inside a card or a list row) — the style sheet
builds them from the same numbers (min-height + the 1 px border on each side).
"""

from __future__ import annotations

PAGE_MARGINS = (24, 18, 24, 16)          # left, top, right, bottom of a page inside the sheet
HEADER_HEIGHT = 36
CONTROL_HEIGHT = 36
COMPACT_HEIGHT = 32
CONTENT_MAX_WIDTH = 2000                 # pages fill the sheet; only an enormous window stops them
SHEET_BORDER = 1                         # the sheet draws a 1 px frame: its content starts that much lower
