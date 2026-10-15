import pytest

manim = pytest.importorskip("manim")

from manim_lace.adapters.manim import extract_paths  # noqa: E402


def test_circle_adapter_returns_closed_polyline():
    from manim import Circle

    paths = extract_paths(Circle(radius=1), max_error=0.01)
    assert paths
    assert any(path.closed for path in paths)
