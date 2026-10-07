"""Table models, filters and delegates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QStyleOptionViewItem

from antidetect import i18n
from antidetect.gui.models import ProfileRow, ProxyRow
from antidetect.gui.models import profiles as pm
from antidetect.gui.models import proxies as xm
from antidetect.gui.models import roles
from antidetect.gui.models.rows import browser_label, relative_time, short_gpu
from antidetect.gui.models.logs import LogFilter, LogModel, format_line
from antidetect.gui.views.delegates import ProfileDelegate
from antidetect.gui.views.table import DataTable

pytestmark = pytest.mark.usefixtures("qapp")


def _row(i=1, name="Alpha", **kw) -> ProfileRow:
    base = dict(
        id=i, name=name, running=False, pid=None, notes="", tags=(), platform="windows",
        browser="Chrome 154", user_agent="UA", timezone="Europe/Berlin", locale="de-DE", language="de",
        screen="1920×1080", gpu="NVIDIA GeForce RTX 3060", cores=8, memory_gb=16, proxy_id=None,
        proxy_endpoint=None, proxy_protocol=None, proxy_country_code=None, proxy_country=None,
        proxy_latency=None, last_started_at=None, geo_auto=True, start_url=None,
        configuration_id=1, profile_path="/tmp/p",
    )
    base.update(kw)
    return ProfileRow(**base)


def _proxy(i=1, **kw) -> ProxyRow:
    base = dict(id=i, protocol="HTTP", host="1.2.3.4", port=80, username=None, country_code="DE",
                country="Germany", latency_ms=120, status="WORKING", anonymity="ELITE", source="manual",
                used_by=(), checked_at=None)
    base.update(kw)
    return ProxyRow(**base)


def test_profile_model_columns_and_text():
    i18n.set_language("en")
    model = pm.ProfilesModel()
    model.set_rows([_row(tags=("a",), proxy_endpoint="9.9.9.9:80", proxy_country_code="de", proxy_latency=88)])
    assert model.rowCount() == 1 and model.columnCount() == pm.COLUMN_COUNT
    d = lambda col, role=Qt.ItemDataRole.DisplayRole: model.index(0, col).data(role)  # noqa: E731
    assert d(pm.COL_NAME) == "Alpha" and d(pm.COL_STATUS) == "Stopped"
    assert d(pm.COL_NAME, roles.SUB_ROLE) == "Windows · Chrome 154"
    assert d(pm.COL_PROXY) == "9.9.9.9:80" and d(pm.COL_PROXY, roles.SUB_ROLE) == "DE · 88 ms"
    assert d(pm.COL_LAST) == "Never" and d(pm.COL_NAME, roles.CHIPS_ROLE) == ("a",)
    assert model.headerData(pm.COL_NAME, Qt.Orientation.Horizontal) == "Profile"


def test_profile_model_without_proxy_and_busy_state():
    model = pm.ProfilesModel()
    model.set_rows([_row()])
    assert model.index(0, pm.COL_PROXY).data() == "No proxy"
    model.set_busy(1, "starting")
    assert model.index(0, pm.COL_STATUS).data() == "Starting…"
    assert model.index(0, 0).data(roles.BUSY_ROLE) == "starting"
    model.set_busy(1, None)
    assert model.busy(1) is None


def test_set_rows_keeps_selection_friendly_updates_when_ids_are_unchanged():
    model = pm.ProfilesModel()
    seen = []
    model.dataChanged.connect(lambda *a: seen.append("changed"))
    model.modelReset.connect(lambda: seen.append("reset"))
    model.layoutChanged.connect(lambda *a: None)
    model.set_rows([_row(1), _row(2, "B")])
    model.set_rows([_row(1, running=True), _row(2, "B")])
    assert seen == ["changed"]       # the first fill is a layout change: no reset, no flicker
    model.set_rows([_row(1)])
    assert len(seen) == 1            # a removed row is a layout change as well (selection remapped by id)


def test_profile_sorting_keys():
    model = pm.ProfilesModel()
    model.set_rows([_row(1, "beta", running=True), _row(2, "Alpha"), _row(3, "gamma", last_started_at=datetime(2026, 1, 1))])
    model.sort(pm.COL_NAME)
    assert [model.index(i, pm.COL_NAME).data() for i in range(3)] == ["Alpha", "beta", "gamma"]  # case-insensitive
    model.sort(pm.COL_STATUS)
    assert model.index(0, pm.COL_NAME).data() == "beta"  # running first
    model.sort(pm.COL_NAME, Qt.SortOrder.DescendingOrder)
    assert [model.index(i, pm.COL_NAME).data() for i in range(3)] == ["gamma", "beta", "Alpha"]
    model.sort(pm.COL_LAST, Qt.SortOrder.DescendingOrder)
    assert model.index(0, pm.COL_NAME).data() == "gamma"            # the only profile that ever ran comes first


def test_sorting_and_filtering_keep_the_selection_by_row_id():
    from PySide6.QtCore import QItemSelectionModel

    model = pm.ProfilesModel()
    model.set_rows([_row(1, "Alpha"), _row(2, "Bravo"), _row(3, "Charlie")])
    model.sort(pm.COL_NAME)
    view = DataTable(60)
    view.setModel(model)
    view.selectionModel().select(model.index(0, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    model.sort(pm.COL_NAME, Qt.SortOrder.DescendingOrder)
    (picked,) = view.selectionModel().selectedRows()
    assert picked.data(roles.ROW_ROLE).name == "Alpha" and picked.row() == 2
    model.set_text("bravo")                                   # the selected row is filtered out...
    assert not view.selectionModel().hasSelection()
    model.set_text("")                                        # ...and the others are all back
    assert model.rowCount() == 3 and model.total() == 3


def test_profile_filter_text_state_and_tag():
    model = pm.ProfilesModel()
    model.set_rows([
        _row(1, "Shop", tags=("eu",), proxy_endpoint="1.1.1.1:80"),
        _row(2, "Ads", running=True, tags=("us",), notes="campaign", platform="macos"),
        _row(3, "Zed", tags=("eu", "us")),
    ])
    assert model.rowCount() == 3
    model.set_text("camp")
    assert model.rowCount() == 1
    model.set_text("1.1.1")
    assert model.rowCount() == 1  # matches the proxy endpoint
    model.set_text("")
    model.set_state("running")
    assert model.rowCount() == 1
    model.set_state("stopped")
    assert model.rowCount() == 2
    model.set_state(None)
    model.set_tag("US")
    assert model.rowCount() == 2
    model.set_tag(None)
    model.set_platforms({"macos"})
    assert model.rowCount() == 1 and model.active_filters() == 1
    model.set_platforms(set())
    model.set_proxy("with")
    assert [model.index(i, pm.COL_NAME).data() for i in range(model.rowCount())] == ["Shop"]
    model.set_proxy("without")
    assert model.rowCount() == 2
    model.clear_filters()
    assert model.rowCount() == 3 and model.active_filters() == 0
    assert model.tag_counts() == {"eu": 2, "us": 2}


def test_relative_labels():
    i18n.set_language("en")
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # the DB stores UTC-naive
    assert pm.relative_label(None) == "Never"
    assert pm.relative_label(now - timedelta(seconds=5)) == "Just now"
    assert pm.relative_label(now - timedelta(minutes=7)) == "7 min ago"
    assert pm.relative_label(now - timedelta(hours=3)) == "3 h ago"
    assert pm.relative_label(now - timedelta(days=2)) == "2 d ago"
    assert relative_time(None) is None


def test_row_helpers():
    assert browser_label("Mozilla Chrome/154.0.0.0 Safari") == "Chrome 154" and browser_label(None) == "Chrome"
    assert short_gpu(None) is None
    assert short_gpu("ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)") == "Apple M2"
    assert short_gpu("ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)") == "NVIDIA GeForce RTX 3060"
    assert short_gpu("ANGLE (Intel, Mesa Intel(R) UHD Graphics 630 (CFL GT2), OpenGL 4.6)") == "Intel UHD Graphics 630"


def test_proxy_model_and_filter():
    i18n.set_language("en")
    model = xm.ProxiesModel()
    model.set_rows([_proxy(1), _proxy(2, host="5.6.7.8", status="DEAD", source="pool", country_code="FR", country="France", used_by=("Shop",))])
    d = lambda r, c: model.index(r, c).data()  # noqa: E731
    assert d(0, xm.COL_ADDRESS) == "1.2.3.4:80" and d(0, xm.COL_STATUS) == "Working" and d(0, xm.COL_SOURCE) == "Yours"
    assert d(1, xm.COL_STATUS) == "Dead" and d(1, xm.COL_SOURCE) == "Free list" and d(1, xm.COL_USED) == "Shop"
    assert d(0, xm.COL_PING) == "120 ms" and d(0, xm.COL_ANON) == "Elite"
    model.set_text("france")
    assert model.rowCount() == 1
    model.set_text("shop")
    assert model.rowCount() == 1
    model.set_text("")
    model.sort(xm.COL_STATUS)
    assert model.index(0, xm.COL_ADDRESS).data() == "1.2.3.4:80"  # working before dead


def test_profile_delegate_clicks_only_inside_the_buttons_and_not_while_busy():
    model = pm.ProfilesModel()
    model.set_rows([_row()])
    view = DataTable(60)
    view.setModel(model)
    delegate = ProfileDelegate(view)
    view.setItemDelegate(delegate)
    view.resize(900, 200)
    view.show()
    index = model.index(0, pm.COL_ACTION)
    more_index = model.index(0, pm.COL_MORE)
    option = QStyleOptionViewItem()
    option.rect = view.visualRect(index)
    more_option = QStyleOptionViewItem()
    more_option.rect = view.visualRect(more_index)
    actions, menus = [], []
    delegate.actionClicked.connect(actions.append)
    delegate.menuClicked.connect(lambda idx, pos: menus.append(pos))

    def release(point, *, more=False):
        event = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(point), QPointF(point),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        return delegate.editorEvent(event, model, more_option if more else option, more_index if more else index)

    inside = delegate.action_rect(option.rect).center()
    assert release(inside) is True and len(actions) == 1
    assert release(delegate.more_rect(more_option.rect).center(), more=True) is True and len(menus) == 1
    assert release(option.rect.topLeft()) is False and len(actions) == 1
    assert delegate.hotspot(index, inside, view) and not delegate.hotspot(index, option.rect.topLeft(), view)
    model.set_busy(1, "starting")
    assert release(inside) is False and len(actions) == 1
    view.close()


def test_rows_model_only_signals_the_rows_that_changed():
    model = pm.ProfilesModel()
    changed = []
    model.dataChanged.connect(lambda top, bottom, *_: changed.append((top.row(), bottom.row())))
    model.set_rows([_row(1), _row(2, "B"), _row(3, "C")])
    changed.clear()
    model.set_rows([_row(1), _row(2, "B"), _row(3, "C")])          # identical: silence
    assert changed == []
    model.set_rows([_row(1), _row(2, "B", running=True), _row(3, "C")])
    assert changed == [(1, 1)] and model.running_ids() == frozenset({2})


def test_log_model_appends_trims_and_filters(monkeypatch):
    from antidetect.gui.models import logs as lm

    monkeypatch.setattr(lm, "MAX_LINES", 5)

    class Entry:
        def __init__(self, i, level="INFO", message="m"):
            self.id, self.level, self.source, self.message, self.ts = i, level, "src", message, datetime(2026, 1, 1, 10, 0, i % 60)

    model = LogModel()
    model.append([Entry(i) for i in range(1, 4)])
    assert model.rowCount() == 3 and model.last_id == 3
    model.append([Entry(i) for i in range(4, 9)])
    assert model.rowCount() == 5 and model.lines()[0].id == 4 and model.last_id == 8
    model.append([Entry(9, "ERROR", "boom")])
    flt = LogFilter()
    flt.setSourceModel(model)
    flt.set_level(3)
    assert flt.rowCount() == 1 and "boom" in format_line(flt.index(0, 0).data(lm.LINE_ROLE))
    flt.set_level(0)
    flt.set_text("BOOM")
    assert flt.rowCount() == 1
    model.clear()
    assert model.rowCount() == 0 and model.last_id == 0
