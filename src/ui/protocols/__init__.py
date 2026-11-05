"""UI layer protocols (structural typing contracts)."""

from src.ui.protocols.analysis_page import AnalysisPage
from src.ui.protocols.density_aware import ArrangementAware, DensityAware

__all__ = ["AnalysisPage", "ArrangementAware", "DensityAware"]
