"""Interface text and theme: complete in both languages, no leftovers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from antidetect import i18n
from antidetect.gui import theme
from antidetect.gui.theme import icons

pytestmark = pytest.mark.usefixtures("qapp")

_SRC = Path(__file__).resolve().parents[2] / "src" / "antidetect"
_PLACEHOLDER = re.compile(r"\{(\w+)(?:![rs])?(?::[^}]*)?\}")


def test_every_key_has_both_languages():
    missing = [k for k, v in i18n._STRINGS.items() if not v.get("en") or not v.get("ru")]
    assert missing == []


def test_placeholders_match_between_languages():
    for key, table in i18n._STRINGS.items():
        en, ru = set(_PLACEHOLDER.findall(table["en"])), set(_PLACEHOLDER.findall(table["ru"]))
        assert en == ru, f"{key}: {en} vs {ru}"


def test_every_literal_key_used_by_the_gui_exists():
    prefixes = {k.split(".")[0] for k in i18n._STRINGS}
    literal = re.compile(r"""["']([a-z]+\.[a-z0-9_.]+)["']""")
    used: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if path.name == "i18n.py" or "migrations" in path.parts:
            continue
        used |= {m for m in literal.findall(path.read_text(encoding="utf-8")) if m.split(".")[0] in prefixes}
    # settings keys and documented field names, not texts
    ignored = {"gui.language", "gui.theme", "api.enabled", "api.port", "api.token", "error.code", "error.message",
               "browser.path"}
    unknown = sorted(k for k in used - ignored if k not in i18n._STRINGS)
    assert unknown == []


def test_unknown_key_falls_back_to_the_key_and_format_errors_are_safe():
    assert i18n.tr("no.such.key") == "no.such.key"
    assert i18n.tr("toast.started", _lang="en", name="X") == "“X” started"
    assert i18n.tr("toast.started", _lang="ru", name="X") == "«X» запущен"
    assert i18n.tr("toast.started", _lang="en") == "“{name}” started"  # missing arg: no crash


def test_language_normalization():
    assert i18n.normalize("Русский") == "ru" and i18n.normalize("EN") == "en"
    assert i18n.normalize("de") == i18n.DEFAULT


def test_stylesheets_are_fully_substituted_for_both_palettes():
    for palette in (theme.LIGHT, theme.DARK):
        sheet = theme.build_stylesheet(palette)
        assert "$" not in sheet
        assert palette.accent in sheet and palette.window in sheet


def test_apply_theme_resolves_and_remembers_the_request(qapp):
    assert theme.apply_theme(qapp, "dark") == "dark"
    assert theme.current_theme(qapp) == "dark" and theme.current_palette(qapp) is theme.DARK
    assert theme.apply_theme(qapp, "light") == "light"
    assert theme.resolve_theme("system", qapp) in ("light", "dark")
    assert theme.normalize_theme("neon") == "system"
    theme.apply_theme(qapp, "light")


def test_palettes_have_readable_text_on_accent():
    def luminance(hex_color: str) -> float:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    for palette in (theme.LIGHT, theme.DARK):
        lighter, darker = sorted((luminance(palette.accent), luminance(palette.accent_text)), reverse=True)
        assert (lighter + 0.05) / (darker + 0.05) >= 4.0, palette.name
        lighter, darker = sorted((luminance(palette.window), luminance(palette.text)), reverse=True)
        assert (lighter + 0.05) / (darker + 0.05) >= 7.0, palette.name


def test_every_icon_the_gui_asks_for_exists_and_renders():
    literal = re.compile(r"""(?:icon=|IconLabel\(|IconButton\(|icon\(|set_icon\(|set_icon_name\(|pixmap\()\s*["']([a-z-]+)["']""")
    used: set[str] = set()
    for path in (_SRC / "gui").rglob("*.py"):
        used |= set(literal.findall(path.read_text(encoding="utf-8")))
    assert used, "icon usage pattern matched nothing"
    assert sorted(used - set(icons.names())) == []
    for name in icons.names():
        assert not icons.pixmap(name, "#112233", 16).isNull()


def test_light_and_dark_palettes_define_the_same_tokens():
    assert theme.LIGHT.__dataclass_fields__.keys() == theme.DARK.__dataclass_fields__.keys()
    for palette in (theme.LIGHT, theme.DARK):
        for field, value in palette.__dict__.items():
            if field != "name":
                assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), (palette.name, field, value)


def test_status_text_is_readable_on_its_soft_background():
    def luminance(hex_color: str) -> float:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a: str, b: str) -> float:
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for palette in (theme.LIGHT, theme.DARK):
        for fg, bg in (("success", "success_soft"), ("danger", "danger_soft"), ("warning", "warning_soft"),
                       ("muted", "subtle"), ("accent", "accent_soft"), ("danger_text", "danger")):
            assert ratio(getattr(palette, fg), getattr(palette, bg)) >= 3.0, (palette.name, fg, bg)


def test_applying_the_current_theme_again_does_no_work(qapp):
    seen: list[str] = []
    on_about, on_changed = (lambda: seen.append("about")), (lambda: seen.append("changed"))
    theme.bus.aboutToChange.connect(on_about)
    theme.bus.changed.connect(on_changed)
    try:
        theme.apply_theme(qapp, "light")
        assert seen == []                                                # nothing to restyle
        theme.apply_theme(qapp, "dark")
        assert seen == ["about", "changed"] and theme.current_palette(qapp) is theme.DARK
        theme.apply_theme(qapp, "dark")
        assert seen == ["about", "changed"]
        resolved = theme.resolve_theme("system", qapp)
        theme.apply_theme(qapp, "system")                                # still remembered as the request
        assert theme.current_theme(qapp) == "system"
        assert seen == ["about", "changed"] + ([] if resolved == "dark" else ["about", "changed"])
    finally:
        theme.bus.aboutToChange.disconnect(on_about)
        theme.bus.changed.disconnect(on_changed)
        theme.apply_theme(qapp, "light")


def test_a_theme_switch_restyles_what_is_inside_a_scroll_area(qapp):
    from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

    area = QScrollArea()
    area.setWidgetResizable(True)
    body = QWidget()
    QVBoxLayout(body)
    label = QLabel("muted text")
    label.setProperty("role", "muted")
    body.layout().addWidget(label)
    area.setWidget(body)
    area.resize(300, 200)
    area.show()
    try:
        theme.apply_theme(qapp, "dark")
        qapp.processEvents()
        assert label.palette().color(label.foregroundRole()).name().upper() == theme.DARK.muted
        theme.apply_theme(qapp, "light")
        qapp.processEvents()
        assert label.palette().color(label.foregroundRole()).name().upper() == theme.LIGHT.muted
        assert area.widget() is body and area.isVisible()
    finally:
        area.close()
