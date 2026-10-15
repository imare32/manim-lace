"""The Manim facade's M6 style layer: palettes, frame, paper and density."""

import numpy as np
import pytest

manim = pytest.importorskip("manim")

from manim_lace import Lace  # noqa: E402
from manim_lace.style import BorderSpec, DensityPolicy, StylePolicy, get_palette  # noqa: E402


def _source():
    from manim import Circle, Line, VGroup

    return VGroup(
        Circle(radius=1.0),
        Line(np.array([-1.6, 0.0, 0.0]), np.array([1.6, 0.0, 0.0])),
    )


def _dense_source():
    """A straight strand crossed eight times inside a narrow x window."""
    from manim import Line, VGroup, VMobject

    corners = np.array([
        [x, y, 0.0]
        for x, y in (
            (0.35, -0.4), (0.35, 0.4), (0.5, -0.4), (0.5, 0.4), (0.65, -0.4),
            (0.65, 0.4), (0.8, -0.4), (0.8, 0.4), (0.95, -0.4),
        )
    ])
    zigzag = VMobject().set_points_as_corners(corners)
    return VGroup(Line(np.array([-2.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])), zigzag)


def _hexes(mobjects) -> list[str]:
    return [str(mob.get_stroke_color().to_hex()).lower() for mob in mobjects]


def test_palette_colours_reach_the_strokes():
    palette = get_palette("haru")
    lace = Lace(_source(), offset=0.15, palette="haru")
    assert len(lace.ribbons) == len(lace.result.pieces)
    assert set(_hexes(lace.ribbons)) <= set(palette.colors)
    assert lace.style_plan is not None
    for mob, assignment in zip(
        lace.ribbons, lace.style_plan.ordered(), strict=True
    ):
        assert str(mob.get_stroke_color().to_hex()).lower() == assignment.color


def test_style_policy_does_not_change_the_geometry():
    warm = Lace(_source(), offset=0.15, palette="aki")
    cool = Lace(_source(), offset=0.15, style_policy=StylePolicy(palette="ayame"))
    assert [c.crossing_id for c in warm.crossings] == [c.crossing_id for c in cool.crossings]
    assert [p.piece_id for p in warm.result.pieces] == [p.piece_id for p in cool.result.pieces]
    assert np.allclose(
        np.vstack([p.points for p in warm.result.pieces]),
        np.vstack([p.points for p in cool.result.pieces]),
    )
    assert _hexes(warm.ribbons) != _hexes(cool.ribbons)


def test_paper_and_border_layers_are_added_behind_and_around_the_weave():
    from manim import RED

    palette = get_palette("matsuri")
    lace = Lace(
        _source(),
        offset=0.15,
        palette="matsuri",
        paper=True,
        border=BorderSpec(margin=0.3, thickness=0.05, corner="round", radius=0.15, bands=2),
    )
    assert lace.paper_layer is not None
    paper = lace.paper_layer[0]
    assert paper.z_index == -1
    assert str(paper.get_fill_color().to_hex()).lower() == palette.background
    assert lace.border_layer is not None
    assert len(lace.border_layer) == 2
    assert len(lace.border_geometry.centerlines) == 2
    # The default border colour is the palette's deepest colour.
    assert str(lace.border_layer[0].get_stroke_color().to_hex()).lower() == palette.colors[0]
    # BorderSpec.thickness is a world-space thickness; Manim's stroke_width is 100x it.
    assert lace.border_layer[0].stroke_width == pytest.approx(5.0)
    # The paper is the first submobject, so it cannot cover the weave.
    assert lace.submobjects[0] is lace.paper_layer

    red_frame = Lace(_source(), offset=0.15, border=BorderSpec(), border_color=RED)
    assert str(red_frame.border_layer[0].get_stroke_color().to_hex()).lower() == "#fc6255"
    assert red_frame.paper_layer is None


def test_cover_allowance_flows_through_the_facade():
    lace = Lace(_source(), offset=0.15, cover_allowance=0.02)
    assert lace.engine.cover_allowance == pytest.approx(0.02)
    assert [d.code for d in lace.diagnostics] == ["RENDER-COVER-ALLOWANCE"]


def test_density_policy_limits_the_drawn_pieces_without_touching_the_result():
    lace = Lace(_dense_source(), offset=0.05, density_policy=DensityPolicy())
    assert lace.density is not None
    assert lace.density.applied
    assert len(lace.ribbons) == len(lace.density.kept_ids)
    assert len(lace.result.pieces) > len(lace.ribbons)
    codes = [diagnostic.code for diagnostic in lace.diagnostics]
    assert "RENDER-DENSITY-SIMPLIFIED" in codes
    quiet = Lace(_source(), offset=0.15, density_policy=DensityPolicy())
    assert not quiet.density.applied
    assert len(quiet.ribbons) == len(quiet.result.pieces)


def test_ribbon_backend_takes_per_region_colours():
    palette = get_palette("wabi")
    lace = Lace(_source(), offset=0.15, render="ribbon", palette="wabi")
    assert lace.style_plan is not None
    fills = {str(mob.get_fill_color().to_hex()).lower() for mob in lace.ribbons}
    assert fills <= set(palette.colors)
    assert len(fills) > 1


def test_palette_and_style_policy_together_are_rejected():
    with pytest.raises(ValueError, match="either palette or style_policy"):
        Lace(_source(), offset=0.15, palette="haru", style_policy=StylePolicy(palette="aki"))


def test_factory_methods_accept_the_style_options():
    lace = Lace.from_parametric(
        lambda t: (np.cos(t), 0.5 * np.sin(2.0 * t)),
        (0.0, 2.0 * np.pi),
        offset=0.08,
        palette="natsu",
        paper=True,
        border=BorderSpec(margin=0.2),
    )
    assert lace.style is not None
    assert lace.paper_layer is not None
    assert lace.border_layer is not None
    assert set(_hexes(lace.ribbons)) <= set(get_palette("natsu").colors)
