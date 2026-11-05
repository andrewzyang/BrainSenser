"""AnalysisPageScaffold: the shell the four analysis pages share (composition).

Every analysis page has the same shape: a white host with page margins around
an optional status banner and a two-page stack — the empty state (index 0) and
the analysis view (index 1), the page's plot above its grouping panel. The
scaffold builds that shell around the page's own plot and panel and adapts it
to the page's density, which the page forwards from its ``apply_density``:

| Density        | regular (today) | compact |
|----------------|-----------------|---------|
| page margins   | 16              | 8       |
| page spacing   | 12              | 4       |
| plot minimum   | 260             | 220     |
| plot to panel  | 16              | 4       |

Only the PSD page separates its plot from the panel; on the others they meet.
The plot takes 7/10 of the height and the panel 3/10 while the panel's sections
sit side by side (ROW); a STACKED panel needs more, so the two share it evenly.
The plot gets the interface size (``Density.scale``) and the panel the whole
density (compact controls, ROW or STACKED). Nothing is re-created.
"""

from typing import Optional

from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from src.ui.components import EmptyStateWidget
from src.ui.components.base_grouping_panel import BaseGroupingPanel
from src.ui.policy.layout import Arrangement, Density, HeightClass
from src.ui.policy.tokens import DENSITY_SPECS
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

# Plot : panel height stretch.
_ROW_STRETCH = (7, 3)
_STACKED_STRETCH = (1, 1)


class AnalysisPageScaffold:
    """
    The shell of one analysis page, built around its plot and grouping panel.

    Example:
        >>> self._scaffold = AnalysisPageScaffold(self, plot, panel)
        >>> self.content_stack = self._scaffold.content_stack   # empty state / analysis
        >>> self._scaffold.apply_density(density)                # in the page's own
    """

    def __init__(self, page: QWidget, plot: ResponsiveFigureWidget, panel: BaseGroupingPanel, *,
                 banner: Optional[QWidget] = None, plot_gap: bool = False):
        """
        Build the shell into ``page``, which must not have a layout yet.

        Args:
            page: The analysis page
            plot: Its plot widget, shown above the panel
            panel: Its grouping panel
            banner: A status line above the content, hidden until it has news
            plot_gap: Separate the plot from the panel by the density's plot
                gap; without it they meet
        """
        self._plot = plot
        self._panel = panel
        self._plot_gap = plot_gap
        self._layout = None  # the (height class, arrangement) laid out

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Content area (white background)
        host = QWidget()
        host.setStyleSheet("QWidget { background-color: #ffffff; }")
        self._host_layout = QVBoxLayout(host)
        if banner is not None:
            self._host_layout.addWidget(banner)

        # Empty state (index 0) and the analysis view (index 1)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(EmptyStateWidget())
        analysis = QWidget()
        self._analysis_layout = QVBoxLayout(analysis)
        self._analysis_layout.setContentsMargins(0, 0, 0, 0)
        self._analysis_layout.addWidget(plot)
        self._analysis_layout.addWidget(panel)
        self.content_stack.addWidget(analysis)
        self._host_layout.addWidget(self.content_stack)

        page_layout.addWidget(host)
        self._lay_out(HeightClass.REGULAR, Arrangement.ROW)

    def apply_density(self, density: Density) -> None:
        """Adapt the shell, the plot and the panel to ``density`` (idempotent)."""
        self._plot.set_ui_scale(density.scale)
        self._panel.apply_density(density)
        self._lay_out(density.height, density.arrangement)

    def row_minimum_width(self) -> int:
        """The narrowest content width the page fits with its panel in a ROW,
        taken at the regular (widest) page margins."""
        content = max(self._plot.minimumSizeHint().width(), self._panel.row_minimum_width())
        return content + 2 * DENSITY_SPECS[HeightClass.REGULAR.value].page_margin

    def _lay_out(self, height: HeightClass, arrangement: Arrangement) -> None:
        if (height, arrangement) == self._layout:
            return
        self._layout = (height, arrangement)
        spec = DENSITY_SPECS[height.value]
        margin = spec.page_margin
        self._host_layout.setContentsMargins(margin, margin, margin, margin)
        self._host_layout.setSpacing(spec.page_spacing)
        self._analysis_layout.setSpacing(spec.plot_gap if self._plot_gap else 0)
        self._plot.setMinimumHeight(spec.plot_min_height)
        stretch = _STACKED_STRETCH if arrangement is Arrangement.STACKED else _ROW_STRETCH
        for index, factor in enumerate(stretch):
            self._analysis_layout.setStretch(index, factor)
