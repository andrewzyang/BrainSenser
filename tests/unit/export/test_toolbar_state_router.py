from __future__ import annotations

from src.ui.export.toolbar_state_router import ToolbarExportStateRouter


def test_active_page_updates_toolbar_immediately():
    calls: list[bool] = []
    router = ToolbarExportStateRouter(lambda enabled: calls.append(enabled))

    router.on_page_changed("timeline")
    assert calls == [False]

    router.update_page_state("timeline", True)
    assert calls[-1] is True


def test_inactive_page_updates_wait_until_page_is_active():
    calls: list[bool] = []
    router = ToolbarExportStateRouter(lambda enabled: calls.append(enabled))

    router.on_page_changed("timeline")
    calls.clear()

    router.update_page_state("snapshots", True)
    assert calls == []

    router.on_page_changed("snapshots")
    assert calls == [True]


def test_unknown_page_defaults_to_disabled():
    calls: list[bool] = []
    router = ToolbarExportStateRouter(lambda enabled: calls.append(enabled))

    router.on_page_changed("data_management")
    assert calls == [False]

    router.update_page_state("data_management", True)
    assert calls[-1] is True

    router.on_page_changed("streaming")
    assert calls[-1] is False
