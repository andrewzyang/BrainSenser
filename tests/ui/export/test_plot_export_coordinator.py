from __future__ import annotations

import pytest

from src.ui.export import (
    ExportRequest,
    build_snapshots_export_request,
    get_default_dpi_for_extension,
    run_export,
)


def test_png_default_dpi():
    called_with = []

    def fake_render(path: str, dpi: int) -> None:
        called_with.append((path, dpi))

    request = build_snapshots_export_request("/tmp/output.png", fake_render)
    outcome = run_export(request)

    assert outcome.succeeded
    assert called_with == [("/tmp/output.png", 300)]


def test_pdf_default_dpi():
    called_with = []

    def fake_render(path: str, dpi: int) -> None:
        called_with.append((path, dpi))

    request = build_snapshots_export_request("/tmp/output.pdf", fake_render)
    outcome = run_export(request)

    assert outcome.succeeded
    assert called_with == [("/tmp/output.pdf", 150)]


def test_cancelled_when_path_missing():
    called = False

    def fake_render(path: str, dpi: int) -> None:
        nonlocal called
        called = True

    request = build_snapshots_export_request(None, fake_render)
    outcome = run_export(request)

    assert outcome.cancelled
    assert not called


def test_render_exception_surface_error():
    def fake_render(path: str, dpi: int) -> None:
        raise RuntimeError("boom")

    request = build_snapshots_export_request("/tmp/output.svg", fake_render)
    outcome = run_export(request)

    assert outcome.failed
    assert isinstance(outcome.error, RuntimeError)
    assert str(outcome.error) == "boom"


def test_post_render_called_after_success():
    post_invocations = []

    def fake_render(path: str, dpi: int) -> None:
        post_invocations.append(("render", path, dpi))

    def post_render(path: str) -> None:
        post_invocations.append(("post", path))

    request = ExportRequest(
        path="/tmp/output.png",
        render=fake_render,
        post_render=post_render,
    )
    outcome = run_export(request)

    assert outcome.succeeded
    assert post_invocations == [
        ("render", "/tmp/output.png", 300),
        ("post", "/tmp/output.png"),
    ]


def test_get_default_dpi_for_extension_unknown():
    with pytest.raises(ValueError):
        get_default_dpi_for_extension(".jpg")
