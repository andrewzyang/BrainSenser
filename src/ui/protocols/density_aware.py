"""
DensityAware and ArrangementAware protocols.

The window's layout classes are measured once, at the shell, by
:class:`~src.ui.layouts.responsive_context.ResponsiveContext`; pages never
measure them or subscribe to global state (plan R4/R5). A page that adapts to
them satisfies :class:`DensityAware`: ``MainLayout.add_page`` registers it, it
gets the current :class:`~src.ui.policy.layout.Density` at once — hidden pages
too, since Qt doesn't resize hidden stack pages — and again whenever it
changes. The page commands its own children with it (margins, its panel, its
plot's interface size). Separate from ``AnalysisPage``: the Data page is
density-aware, and the contract stays one method.

A page whose grouping panel can arrange its sections in a ROW also satisfies
:class:`ArrangementAware`, so the context knows the narrowest content width
the ROW arrangement fits (that page's honest minimum).
"""
from typing import Protocol, runtime_checkable

from src.ui.policy.layout import Density


@runtime_checkable
class DensityAware(Protocol):
    """A page the ResponsiveContext commands with the window's density."""

    def apply_density(self, density: Density) -> None:
        """Adapt to ``density``; idempotent (an unchanged density changes nothing)."""
        ...


@runtime_checkable
class ArrangementAware(DensityAware, Protocol):
    """A DensityAware page whose panel takes the ROW or STACKED arrangement."""

    def row_minimum_width(self) -> int:
        """The narrowest content width the page fits with its panel in a ROW."""
        ...
