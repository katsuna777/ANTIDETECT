"""Round country flags drawn from code, so they look the same on every OS.

Flag emoji are not an option: Windows has no flag glyphs and shows two letters instead.
Each flag is a few SVG shapes on a 24x24 square, simplified to stay recognisable at 16-28 px
and clipped to a disc. Countries without a design fall back to ``None`` (callers draw a
neutral chip with the code instead).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer


# --------------------------------------------------------------------- builders
def _rect(x: float, y: float, w: float, h: float, fill: str) -> str:
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}"/>'


def _hbands(*colors: str, weights: tuple[float, ...] | None = None) -> str:
    weights = weights or (1,) * len(colors)
    total, y, out = sum(weights), 0.0, []
    for color, weight in zip(colors, weights):
        height = 24 * weight / total
        out.append(_rect(0, y, 24, height + 0.05, color))
        y += height
    return "".join(out)


def _vbands(*colors: str, weights: tuple[float, ...] | None = None) -> str:
    weights = weights or (1,) * len(colors)
    total, x, out = sum(weights), 0.0, []
    for color, weight in zip(colors, weights):
        width = 24 * weight / total
        out.append(_rect(x, 0, width + 0.05, 24, color))
        x += width
    return "".join(out)


def _circle(cx: float, cy: float, r: float, fill: str) -> str:
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{fill}"/>'


def _star(cx: float, cy: float, r: float, fill: str, points: int = 5, inner: float = 0.382, rotate: float = -90) -> str:
    coords = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * inner
        angle = math.radians(rotate + i * 180 / points)
        coords.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return f'<polygon points="{" ".join(coords)}" fill="{fill}"/>'


def _crescent(cx: float, cy: float, r: float, fill: str, bg: str, shift: float = 0.22) -> str:
    return _circle(cx, cy, r, fill) + _circle(cx + r * shift * 1.6, cy, r * 0.82, bg)


def _cross(x: float, y: float, half: float, color: str, bar: float) -> str:
    return _rect(x - bar / 2, y - half, bar, half * 2, color) + _rect(x - half, y - bar / 2, half * 2, bar, color)


def _nordic(bg: str, outer: str, inner: str | None = None) -> str:
    out = _rect(0, 0, 24, 24, bg) + _rect(6.6, 0, 5, 24, outer) + _rect(0, 9.5, 24, 5, outer)
    if inner:
        out += _rect(8.1, 0, 2, 24, inner) + _rect(0, 11, 24, 2, inner)
    return out


def _union_jack() -> str:
    return (
        _rect(0, 0, 24, 24, "#012169")
        + '<path d="M0 0 24 24M24 0 0 24" stroke="#FFF" stroke-width="4.2"/>'
        + '<path d="M0 0 24 24M24 0 0 24" stroke="#C8102E" stroke-width="1.5"/>'
        + _rect(9, 0, 6, 24, "#FFF") + _rect(0, 9, 24, 6, "#FFF")
        + _rect(10.3, 0, 3.4, 24, "#C8102E") + _rect(0, 10.3, 24, 3.4, "#C8102E")
    )


def _spokes(cx: float, cy: float, r1: float, r2: float, count: int, color: str, width: float) -> str:
    lines = []
    for i in range(count):
        a = math.radians(i * 360 / count)
        lines.append(f"M{cx + r1 * math.cos(a):.2f} {cy + r1 * math.sin(a):.2f}L{cx + r2 * math.cos(a):.2f} {cy + r2 * math.sin(a):.2f}")
    return f'<path d="{"".join(lines)}" stroke="{color}" stroke-width="{width}" fill="none"/>'


def _us() -> str:
    stripes = _rect(0, 0, 24, 24, "#B22234")
    h = 24 / 13
    for i in range(1, 12, 2):
        stripes += _rect(0, i * h, 24, h, "#FFF")
    dots = "".join(_circle(2.1 + col * 3.6, 2.3 + row * 3.4, 0.62, "#FFF") for row in range(4) for col in range(3))
    return stripes + _rect(0, 0, 13, 7 * h, "#3C3B6E") + dots


def _au_like(star: str, bg: str = "#00247D") -> str:
    return (
        _rect(0, 0, 24, 24, bg) + f'<g transform="scale(.5)">{_union_jack()}</g>'
        + _star(6, 18, 3, star, 7, 0.5) + _circle(18, 5, 0.9, star) + _circle(21.5, 10.5, 0.9, star)
        + _circle(17, 19, 0.9, star) + _circle(14, 10, 0.9, star)
    )


def _canton_flag(field: str, canton: str, star_color: str | None = None) -> str:
    out = field + _rect(0, 0, 13, 13, canton)
    if star_color:
        out += _star(6.5, 6.5, 3.3, star_color)
    return out


# --------------------------------------------------------------------- the flags
_FLAGS: dict[str, str] = {
    # Europe
    "DE": _hbands("#000", "#DD0000", "#FFCE00"),
    "FR": _vbands("#0055A4", "#FFF", "#EF4135"),
    "IT": _vbands("#009246", "#FFF", "#CE2B37"),
    "ES": _hbands("#AA151B", "#F1BF00", "#AA151B", weights=(1, 2, 1))
          + '<rect x="6.6" y="9.4" width="4.2" height="5.4" rx="1" fill="#AD1519" stroke="#C8A100" stroke-width=".6"/>',
    "NL": _hbands("#AE1C28", "#FFF", "#21468B"),
    "PL": _hbands("#FFF", "#DC143C"),
    "UA": _hbands("#005BBB", "#FFD500"),
    "RU": _hbands("#FFF", "#0039A6", "#D52B1E"),
    "BY": _hbands("#C8313E", "#4AA657", weights=(2, 1)),
    "CZ": _hbands("#FFF", "#D7141A") + '<polygon points="0,0 13,12 0,24" fill="#11457E"/>',
    "SK": _hbands("#FFF", "#0B4EA2", "#EE1C25")
          + '<path d="M6.5 8.5h5.4v4.6c0 2-2.7 3.1-2.7 3.1s-2.7-1.1-2.7-3.1z" fill="#EE1C25" stroke="#FFF" stroke-width=".7"/>'
          + '<path d="M9.2 9.6v5M7.6 11.2h3.2" stroke="#FFF" stroke-width=".8"/>',
    "HU": _hbands("#CD2A3E", "#FFF", "#436F4D"),
    "RO": _vbands("#002B7F", "#FCD116", "#CE1126"),
    "BG": _hbands("#FFF", "#00966E", "#D62612"),
    "RS": _hbands("#C6363C", "#0C4076", "#FFF") + '<rect x="6.8" y="8.6" width="4" height="6" rx="1.2" fill="#C6363C" stroke="#EDB92E" stroke-width=".6"/>',
    "HR": _hbands("#FF0000", "#FFF", "#171796")
          + "".join(_rect(8.4 + c * 2.4, 9.2 + r * 2.4, 2.4, 2.4, "#FF0000" if (r + c) % 2 == 0 else "#FFF") for r in range(3) for c in range(3) if (r + c) % 2 == 0)
          + '<rect x="8.4" y="9.2" width="7.2" height="7.2" fill="none" stroke="#171796" stroke-width=".6"/>',
    "SI": _hbands("#FFF", "#005DA4", "#ED1C24") + '<path d="M5.5 5.5h5.2v4.6c0 2-2.6 3-2.6 3s-2.6-1-2.6-3z" fill="#005DA4" stroke="#FFF" stroke-width=".6"/>',
    "AT": _hbands("#ED2939", "#FFF", "#ED2939"),
    "CH": _rect(0, 0, 24, 24, "#D52B1E") + _cross(12, 12, 6.6, "#FFF", 3.6),
    "BE": _vbands("#000", "#FAE042", "#ED2939"),
    "LU": _hbands("#ED2939", "#FFF", "#00A1DE"),
    "IE": _vbands("#169B62", "#FFF", "#FF883E"),
    "PT": _vbands("#006600", "#FF0000", weights=(2, 3)) + _circle(9.6, 12, 3.3, "#FFD200") + _circle(9.6, 12, 2.1, "#D5202D") + _circle(9.6, 12, 1, "#FFF"),
    "GR": "".join(_rect(0, i * 24 / 9, 24, 24 / 9 + 0.05, "#0D5EAF" if i % 2 == 0 else "#FFF") for i in range(9))
          + _rect(0, 0, 13.4, 13.4, "#0D5EAF") + _rect(5.4, 0, 2.6, 13.4, "#FFF") + _rect(0, 5.4, 13.4, 2.6, "#FFF"),
    "GB": _union_jack(),
    "SE": _nordic("#006AA7", "#FECC02"),
    "DK": _nordic("#C8102E", "#FFF"),
    "NO": _nordic("#BA0C2F", "#FFF", "#00205B"),
    "FI": _nordic("#FFF", "#003580"),
    "IS": _nordic("#02529C", "#FFF", "#DC1E35"),
    "EE": _hbands("#0072CE", "#000", "#FFF"),
    "LV": _hbands("#9E3039", "#FFF", "#9E3039", weights=(2, 1, 2)),
    "LT": _hbands("#FDB913", "#006A44", "#C1272D"),
    "MD": _vbands("#0046AE", "#FFD200", "#CC092F") + _circle(12, 12, 2.4, "#B5651D"),
    "GE": _rect(0, 0, 24, 24, "#FFF") + _cross(12, 12, 12, "#FF0000", 3.2)
          + "".join(_cross(x, y, 1.9, "#FF0000", 1) for x, y in ((5.5, 5.5), (18.5, 5.5), (5.5, 18.5), (18.5, 18.5))),
    "AM": _hbands("#D90012", "#0033A0", "#F2A800"),
    "AZ": _hbands("#00B5E2", "#EF3340", "#509E2F") + _crescent(11.4, 12, 3, "#FFF", "#EF3340") + _star(14.3, 12, 1.4, "#FFF"),
    "TR": _rect(0, 0, 24, 24, "#E30A17") + _crescent(10.3, 12, 5.6, "#FFF", "#E30A17", 0.18) + _star(15.6, 12, 2.3, "#FFF"),
    "CY": _rect(0, 0, 24, 24, "#FFF") + '<path d="M5.5 9.5c3 1 6 3.5 13 1.5-1.5 4-5 6-13-1.5z" fill="#D57800"/>',
    "MT": _vbands("#FFF", "#CF142B") + _rect(1, 1, 4, 4, "#9AA0A6"),
    # Americas
    "US": _us(),
    "CA": _vbands("#D52B1E", "#FFF", "#D52B1E", weights=(1, 2, 1))
          + '<path d="M12 4.6l1.5 3 1.9-.7-.7 4 2.1-1.5.5 1.4 2.4.7-1.1 1.7 1 .9-4.3 3.4.5 1.6-4.1-.4v3.6h-1.4v-3.6l-4.1.4.5-1.6-4.3-3.4 1-.9-1.1-1.7 2.4-.7.5-1.4 2.1 1.5-.7-4 1.9.7z" fill="#D52B1E"/>',
    "MX": _vbands("#006847", "#FFF", "#CE1126") + _circle(12, 12, 2.6, "#9A6F34") + _circle(12, 12, 1.4, "#6B8E4E"),
    "BR": _rect(0, 0, 24, 24, "#009C3B") + '<polygon points="12,3.2 21.5,12 12,20.8 2.5,12" fill="#FFDF00"/>' + _circle(12, 12, 4.7, "#002776")
          + '<path d="M7.4 11.2q4.6-1.8 9.2 1.6" stroke="#FFF" stroke-width="1" fill="none"/>',
    "AR": _hbands("#74ACDF", "#FFF", "#74ACDF") + _circle(12, 12, 2.4, "#F6B40E") + _spokes(12, 12, 3.1, 4.2, 12, "#F6B40E", 0.6),
    "CL": _hbands("#FFF", "#D52B1E") + _rect(0, 0, 12.5, 12, "#0039A6") + _star(6.2, 6, 3.3, "#FFF"),
    "CO": _hbands("#FCD116", "#003893", "#CE1126", weights=(2, 1, 1)),
    "PE": _vbands("#D91023", "#FFF", "#D91023"),
    "VE": _hbands("#FFCC00", "#00247D", "#CF142B")
          + "".join(_circle(12 + 6 * math.cos(math.radians(200 + i * 20)), 17.5 + 6 * math.sin(math.radians(200 + i * 20)), 0.5, "#FFF") for i in range(8)),
    "EC": _hbands("#FFDD00", "#034EA2", "#ED1C24", weights=(2, 1, 1)),
    # Asia
    "JP": _rect(0, 0, 24, 24, "#FFF") + _circle(12, 12, 5.4, "#BC002D"),
    "CN": _rect(0, 0, 24, 24, "#DE2910") + _star(6.4, 7, 3.6, "#FFDE00")
          + _star(11.8, 3.6, 1.2, "#FFDE00") + _star(14, 6.2, 1.2, "#FFDE00") + _star(14, 9.4, 1.2, "#FFDE00") + _star(11.8, 12, 1.2, "#FFDE00"),
    "KR": _rect(0, 0, 24, 24, "#FFF") + '<path d="M7 12a5 5 0 0 1 10 0z" fill="#CD2E3A"/><path d="M17 12a5 5 0 0 1-10 0z" fill="#0047A0"/>'
          + '<path d="M7 12a2.5 2.5 0 0 1 5 0z" fill="#0047A0"/><path d="M12 12a2.5 2.5 0 0 1 5 0z" fill="#CD2E3A" transform="rotate(180 14.5 12)"/>',
    "IN": _hbands("#FF9933", "#FFF", "#138808") + f'<circle cx="12" cy="12" r="3.2" fill="none" stroke="#000080" stroke-width=".6"/>' + _spokes(12, 12, 0.6, 3.2, 12, "#000080", 0.35),
    "ID": _hbands("#E70011", "#FFF"),
    "TH": _hbands("#A51931", "#F4F5F8", "#2D2A4A", "#F4F5F8", "#A51931", weights=(1, 1, 2, 1, 1)),
    "VN": _rect(0, 0, 24, 24, "#DA251D") + _star(12, 12.5, 6.4, "#FFFF00"),
    "PH": _hbands("#0038A8", "#CE1126") + '<polygon points="0,0 14,12 0,24" fill="#FFF"/>' + _circle(4.2, 12, 1.7, "#FCD116"),
    "MY": "".join(_rect(0, i * 24 / 7, 24, 24 / 7 + 0.05, "#CC0001" if i % 2 == 0 else "#FFF") for i in range(7))
          + _rect(0, 0, 13, 13.7, "#010066") + _crescent(5.6, 6.8, 3.3, "#FC0", "#010066") + _star(8.9, 6.8, 1.9, "#FC0", 14, 0.6),
    "SG": _hbands("#EF3340", "#FFF") + _crescent(7, 6, 3.4, "#FFF", "#EF3340", 0.2)
          + "".join(_circle(11.2 + 2.1 * math.cos(math.radians(-90 + i * 72)), 6 + 2.1 * math.sin(math.radians(-90 + i * 72)), 0.55, "#FFF") for i in range(5)),
    "HK": _rect(0, 0, 24, 24, "#DE2910")
          + "".join(f'<ellipse cx="12" cy="8.6" rx="1.7" ry="3.2" fill="#FFF" transform="rotate({i * 72} 12 12)"/>' for i in range(5)),
    "TW": _rect(0, 0, 24, 24, "#FE0000") + _rect(0, 0, 12.5, 12.5, "#000095") + _circle(6.2, 6.2, 3, "#FFF") + _circle(6.2, 6.2, 2.2, "#000095") + _circle(6.2, 6.2, 1.6, "#FFF"),
    "KZ": _rect(0, 0, 24, 24, "#00AFCA") + _circle(12, 12, 3.8, "#FEC50C") + _spokes(12, 12, 4.8, 6.4, 16, "#FEC50C", 0.9),
    "IL": _rect(0, 0, 24, 24, "#FFF") + _rect(0, 3, 24, 2.8, "#0038B8") + _rect(0, 18.2, 24, 2.8, "#0038B8")
          + '<path d="M12 7.6l3.9 6.8H8.1zM12 16.4l-3.9-6.8h7.8z" fill="none" stroke="#0038B8" stroke-width=".9" stroke-linejoin="round"/>',
    "SA": _rect(0, 0, 24, 24, "#006C35") + _rect(6, 8.6, 12, 1.5, "#FFF") + _rect(7, 13.6, 10, 1, "#FFF") + _rect(14.8, 13.1, 2.6, 2, "#006C35"),
    "AE": _hbands("#00732F", "#FFF", "#000") + _rect(0, 0, 6.5, 24, "#FF0000"),
    "IR": _hbands("#239F40", "#FFF", "#DA0000") + _circle(12, 12, 1.9, "#DA0000"),
    "PK": _rect(0, 0, 24, 24, "#01411C") + _rect(0, 0, 6, 24, "#FFF") + _crescent(14.5, 12, 5, "#FFF", "#01411C", 0.2) + _star(17.7, 9.8, 1.7, "#FFF"),
    "BD": _rect(0, 0, 24, 24, "#006A4E") + _circle(10.8, 12, 6, "#F42A41"),
    # Africa
    "ZA": _hbands("#DE3831", "#002395")
          + '<path d="M-2 2.5 9 12-2 21.5M9 12H26" stroke="#FFF" stroke-width="8" fill="none"/>'
          + '<path d="M-2 2.5 9 12-2 21.5M9 12H26" stroke="#007A4D" stroke-width="5" fill="none"/>'
          + '<polygon points="0,5.5 0,18.5 6.2,12" fill="#000" stroke="#FFB612" stroke-width="1"/>',
    "EG": _hbands("#CE1126", "#FFF", "#000") + _circle(12, 12, 1.5, "#C09300"),
    "NG": _vbands("#008751", "#FFF", "#008751"),
    "KE": _hbands("#000", "#FFF", "#BB0000", "#FFF", "#006600", weights=(6, 1, 8, 1, 6))
          + '<ellipse cx="12" cy="12" rx="2.6" ry="5.4" fill="#BB0000" stroke="#000" stroke-width=".8"/>',
    "GH": _hbands("#CE1126", "#FCD116", "#006B3F") + _star(12, 12, 3, "#000"),
    "MA": _rect(0, 0, 24, 24, "#C1272D") + '<path d="M12 6.2l1.6 4.9h5.1l-4.1 3 1.6 4.8L12 15.9l-4.2 3 1.6-4.8-4.1-3h5.1z" fill="none" stroke="#006233" stroke-width=".9"/>',
    "DZ": _vbands("#006633", "#FFF") + _crescent(12.2, 12, 5, "#D21034", "#FFF", 0.2) + _star(14.4, 12, 1.9, "#D21034"),
    "TN": _rect(0, 0, 24, 24, "#E70013") + _circle(12, 12, 6.8, "#FFF") + _crescent(11.4, 12, 4.4, "#E70013", "#FFF", 0.2) + _star(13.4, 12, 2, "#E70013"),
    # Oceania
    "AU": _au_like("#FFF"),
    "NZ": _au_like("#CC142B"),
}


# --------------------------------------------------------------------- rendering
_cache: dict[tuple, QPixmap] = {}


def has_flag(code: str | None) -> bool:
    return (code or "").strip().upper() in _FLAGS


def known() -> tuple[str, ...]:
    return tuple(_FLAGS)


def _svg(code: str) -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{_FLAGS[code]}</svg>'.encode()


def pixmap(code: str | None, diameter: int = 22, dpr: float | None = None) -> QPixmap | None:
    """A rounded square ``diameter`` px across showing the flag of ``code``; ``None`` when there is no design."""
    key_code = (code or "").strip().upper()
    if key_code not in _FLAGS:
        return None
    if dpr is None:
        screen = QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    key = (key_code, diameter, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    side = max(2, round(diameter * dpr))
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    corner = side * 0.3
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0.5, 0.5, side - 1, side - 1), corner, corner)
    painter.setClipPath(clip)
    QSvgRenderer(QByteArray(_svg(key_code))).render(painter, QRectF(0, 0, side, side))
    painter.setClipping(False)
    ring = QColor(0, 0, 0, 38)  # a faint edge so white flags do not melt into a white card
    painter.setPen(QPen(ring, max(1.0, dpr * 0.75)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(0.5, 0.5, side - 1, side - 1), corner, corner)
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(dpr)
    _cache[key] = result
    return result


def clear_cache() -> None:
    _cache.clear()


def icon(code: str | None, diameter: int = 18) -> QIcon:
    """The flag as a QIcon (for combo boxes and menus); empty when there is no design for ``code``."""
    result = QIcon()
    for ratio_ in (1.0, 2.0):
        pixmap_ = pixmap(code, diameter, ratio_)
        if pixmap_ is None:
            return result
        result.addPixmap(pixmap_)
    return result
