"""Profiles page offers one-click timezone auto-fix on geo mismatch."""

from __future__ import annotations

import pytest

from app.application.profile_doctor import DoctorFinding, DoctorReport
from app.gui.widgets.pages.profiles_page import ProfilesPage

pytestmark = pytest.mark.usefixtures("qapp")


def _page(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    return ProfilesPage(gui_container, TaskRunner())


def _mismatch_report():
    return DoctorReport(
        ok=False,
        blocks=[
            DoctorFinding(
                "block",
                "geo-timezone-mismatch",
                "Proxy exits in DE but timezone is America/New_York (US)",
                "fix it",
            )
        ],
        facts={"proxy_country": "DE"},
    )


def test_geo_autofix_detects_timezone_mismatch(gui_container, monkeypatch):
    cfg = gui_container.configurations.create_configuration(
        "misaligned", timezone="America/New_York"
    )
    profile = gui_container.profiles.create_profile(
        "blocked", configuration_id=cfg.id
    )
    monkeypatch.setattr(
        gui_container.profiles,
        "diagnose_profile",
        lambda profile_id, probe_google=True: _mismatch_report(),
    )
    page = _page(gui_container)
    assert page._geo_autofix(profile.id) == (cfg.id, "DE")


def test_geo_autofix_ignores_other_errors(gui_container, monkeypatch):
    cfg = gui_container.configurations.create_configuration("fine")
    profile = gui_container.profiles.create_profile(
        "fine-profile", configuration_id=cfg.id
    )
    monkeypatch.setattr(
        gui_container.profiles,
        "diagnose_profile",
        lambda profile_id, probe_google=True: DoctorReport(ok=True),
    )
    page = _page(gui_container)
    assert page._geo_autofix(profile.id) is None
    assert page._autofix_offer(profile.id) is None


def _drift_report():
    return DoctorReport(
        ok=False,
        blocks=[
            DoctorFinding(
                "block",
                "ua-binary-drift",
                "User-Agent Chrome/150 vs installed Chrome/152",
                "Regenerate for Chrome/152",
            )
        ],
        facts={"binary_major": 152},
    )


def test_autofix_offer_regenerates_for_installed_chrome(
    gui_container, monkeypatch
):
    cfg = gui_container.configurations.create_configuration("drifted")
    profile = gui_container.profiles.create_profile(
        "drifted-profile", configuration_id=cfg.id
    )
    monkeypatch.setattr(
        gui_container.profiles,
        "diagnose_profile",
        lambda profile_id, probe_google=True: _drift_report(),
    )
    page = _page(gui_container)
    offer = page._autofix_offer(profile.id)
    assert offer is not None
    label, _apply = offer
    assert "Chrome/152" in label
