"""wrap_tooltip turns plain text into escaped rich text so Qt wraps it."""

from src.ui.utils.tooltips import wrap_tooltip


def test_wraps_in_paragraph_and_escapes_markup():
    assert wrap_tooltip("p < 0.05 & n > 3") == "<p>p &lt; 0.05 &amp; n &gt; 3</p>"


def test_newlines_become_line_breaks():
    assert wrap_tooltip("a\nb") == "<p>a<br>b</p>"
