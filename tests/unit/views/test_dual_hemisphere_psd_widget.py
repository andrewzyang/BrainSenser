"""Unit tests for DualHemispherePsdWidget export functionality"""
import pytest
from PySide6.QtGui import QImage
import numpy as np

from src.ui.views.snapshots_psd.components.dual_hemisphere_psd_widget import DualHemispherePsdWidget


class TestDualHemispherePsdWidgetExport:
    """Test plot export functionality"""

    @pytest.fixture
    def widget(self, qtbot):
        """Create widget with test data"""
        w = DualHemispherePsdWidget()
        qtbot.addWidget(w)

        # Add test data
        freq = np.linspace(1, 30, 100)
        psd = np.random.rand(100)
        # Format: (median, lower_ci, upper_ci, n_events)
        w.update_psd_data(
            freq,
            (psd, psd * 0.9, psd * 1.1, 10),  # left craving
            (psd * 0.9, psd * 0.8, psd * 1.0, 10),  # left non-craving
            (psd * 1.1, psd * 1.0, psd * 1.2, 10),  # right craving
            (psd, psd * 0.9, psd * 1.1, 10)  # right non-craving
        )

        return w

    def test_export_png_creates_file(self, widget, qtbot, tmp_path):
        """Test PNG export creates non-empty file"""
        output_path = tmp_path / "test_plot.png"

        widget.export_figure(str(output_path))

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_export_png_has_content(self, widget, qtbot, tmp_path):
        """Test PNG export contains plot content (not blank)"""
        output_path = tmp_path / "test_plot.png"

        widget.export_figure(str(output_path))

        # Load image and verify it's not blank
        image = QImage(str(output_path))
        assert not image.isNull()

        # Check that image has non-white pixels (contains plot data)
        has_content = False
        for x in range(image.width()):
            for y in range(image.height()):
                pixel = image.pixel(x, y)
                # If pixel is not white, we have content
                if pixel != 0xFFFFFFFF:
                    has_content = True
                    break
            if has_content:
                break

        assert has_content, "Exported image appears to be blank"

    def test_export_immediate_after_update(self, widget, qtbot, tmp_path):
        """Test export immediately after data update (reproduces blank bug)"""
        output_path = tmp_path / "test_immediate.png"

        # Update data
        freq = np.linspace(1, 30, 100)
        psd = np.random.rand(100)
        # Format: (median, lower_ci, upper_ci, n_events)
        widget.update_psd_data(
            freq,
            (psd, psd * 0.9, psd * 1.1, 10),
            (psd * 0.9, psd * 0.8, psd * 1.0, 10),
            (psd * 1.1, psd * 1.0, psd * 1.2, 10),
            (psd, psd * 0.9, psd * 1.1, 10)
        )

        # Export IMMEDIATELY (this would fail before fix)
        widget.export_figure(str(output_path))

        # Verify image has content
        image = QImage(str(output_path))
        assert not image.isNull()

        # Check for non-white pixels
        has_content = False
        for x in range(0, image.width(), 10):  # Sample every 10 pixels
            for y in range(0, image.height(), 10):
                if image.pixel(x, y) != 0xFFFFFFFF:
                    has_content = True
                    break
            if has_content:
                break

        assert has_content, "Immediate export produced blank image"

    def test_export_svg_creates_file(self, widget, qtbot, tmp_path):
        """Test SVG export creates a single combined (both-hemisphere) file.

        The matplotlib port saves one figure containing both panels, replacing
        the old PyQtGraph behavior that split into ``_left.svg`` / ``_right.svg``.
        """
        output_path = tmp_path / "test_plot.svg"

        widget.export_figure(str(output_path))

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_export_pdf_creates_file(self, widget, qtbot, tmp_path):
        """Test PDF export creates file"""
        output_path = tmp_path / "test_plot.pdf"

        widget.export_figure(str(output_path))

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_export_invalid_format_raises_error(self, widget, qtbot, tmp_path):
        """Test invalid format raises ValueError"""
        output_path = tmp_path / "test_plot.xyz"

        with pytest.raises(ValueError, match="Unsupported format"):
            widget.export_figure(str(output_path))
