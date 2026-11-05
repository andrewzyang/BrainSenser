"""Helpers for coordinating plot exports across Timeline and Snapshots views."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

SupportedStatus = Literal["success", "error", "cancelled"]


@dataclass(frozen=True)
class ExportRequest:
    """Container describing an export action requested by a view."""

    path: Optional[str]
    render: Callable[[str, int], None]
    dpi_override: Optional[int] = None
    post_render: Optional[Callable[[str], None]] = None


@dataclass(frozen=True)
class ExportOutcome:
    """Result returned after attempting to run an export."""

    status: SupportedStatus
    path: Optional[str] = None
    error: Optional[Exception] = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def failed(self) -> bool:
        return self.status == "error"


def run_export(request: ExportRequest) -> ExportOutcome:
    """Execute the export described by the request."""

    path = request.path
    if not path:
        return ExportOutcome(status="cancelled")

    extension = Path(path).suffix.lower()
    if not extension:
        return ExportOutcome(
            status="error",
            path=path,
            error=ValueError("Export path missing extension."),
        )

    dpi = request.dpi_override if request.dpi_override is not None else get_default_dpi_for_extension(extension)

    try:
        request.render(path, dpi)
        if request.post_render:
            request.post_render(path)
    except Exception as exc:  # noqa: BLE001
        return ExportOutcome(status="error", path=path, error=exc)

    return ExportOutcome(status="success", path=path)


def get_default_dpi_for_extension(extension: str) -> int:
    """Return the default DPI for supported extensions."""
    ext = extension.lower()
    if ext == ".png":
        return 200  # Higher resolution export while maintaining viewport appearance
    elif ext in (".pdf", ".svg"):
        return 200  # Consistent DPI across all formats
    else:
        raise ValueError(f"Unsupported export format: {extension}")


def build_snapshots_export_request(
    path: Optional[str],
    render: Callable[[str, int], None],
    *,
    dpi_override: Optional[int] = None,
    post_render: Optional[Callable[[str], None]] = None,
) -> ExportRequest:
    """Factory used by the Snapshots view to prepare an export request."""

    return ExportRequest(
        path=path,
        render=render,
        dpi_override=dpi_override,
        post_render=post_render,
    )


def build_timeline_export_request(
    path: Optional[str],
    render: Callable[[str, int], None],
    *,
    dpi_override: Optional[int] = None,
    post_render: Optional[Callable[[str], None]] = None,
) -> ExportRequest:
    """Factory used by the Timeline view to prepare an export request."""

    return ExportRequest(
        path=path,
        render=render,
        dpi_override=dpi_override,
        post_render=post_render,
    )
