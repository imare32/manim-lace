"""Borders, cut-end treatments and density-aware simplification (M6).

The border and the piece outline are pure geometry, so they are checked the way the
rest of the geometry layer is: closure, orientation, exact areas where an analytic
value exists, and explicit failures where the request is not representable.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.render.stroke import StrokePiece
from manim_lace.style import (
    BorderSpec,
    CapTreatment,
    DensityPolicy,
    analyze_density,
    build_border,
    get_palette,
    is_light,
    pattern_bounds,
    simplify_for_density,
    stroke_piece_outline,
    trim_cut_half_length,
    validate_cover_allowance,
)

TWO_STRAND = [
    np.array([[-2.0, 0.0], [2.0, 0.0]]),
    np.array([[0.0, -2.0], [0.0, 2.0]]),
]


def _two_strand(**kwargs):
    return LaceEngine(TWO_STRAND, offset=0.2, **kwargs).solve()


def _dense_result(offset: float = 0.05):
    zigzag = np.array([
        [0.35, -0.4], [0.35, 0.4], [0.5, -0.4], [0.5, 0.4], [0.65, -0.4],
        [0.65, 0.4], [0.8, -0.4], [0.8, 0.4], [0.95, -0.4],
    ])
    return LaceEngine([np.array([[-2.0, 0.0], [2.0, 0.0]]), zigzag], offset=offset).solve()


def _straight_piece(length: float = 2.0) -> StrokePiece:
    return StrokePiece(
        piece_id="p0", path_id="P0000",
        points=np.array([[0.0, 0.0], [length, 0.0]]),
        arc_start=0.0, arc_end=length,
    )


def _signed_area(ring: np.ndarray) -> float:
    """The shoelace area of a closed ring, positive when counter-clockwise."""
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _assert_ring(ring: np.ndarray, *, counter_clockwise: bool = True) -> None:
    assert len(ring) >= 4
    assert np.allclose(ring[0], ring[-1])
    assert (_signed_area(ring) > 0) is counter_clockwise


# --------------------------------------------------------------------------- #
# Border design
# --------------------------------------------------------------------------- #


def test_pattern_bounds_follow_the_visible_geometry():
    assert pattern_bounds(_two_strand()) == (-2.0, -2.0, 2.0, 2.0)
    with pytest.raises(ValueError, match="no visible geometry"):
        pattern_bounds(SimpleNamespace(pieces=[], paths=[]))


def test_square_border_bands_step_out_by_thickness_plus_gap():
    result = _two_strand()
    geometry = build_border(
        result, BorderSpec(margin=0.3, thickness=0.05, gap=0.1, corner="square", bands=2)
    )
    assert len(geometry.centerlines) == 2
    for ring in geometry.centerlines:
        _assert_ring(ring)
    inner, outer = geometry.band_bounds
    assert inner == (-2.3, -2.3, 2.3, 2.3)
    assert outer == pytest.approx((-2.45, -2.45, 2.45, 2.45))
    assert geometry.frame_bounds == pytest.approx(outer)
    assert geometry.pattern_bounds == (-2.0, -2.0, 2.0, 2.0)
    assert geometry.spec.expansion(0) == pytest.approx(0.3)
    assert geometry.spec.expansion(1) == pytest.approx(0.45)
    with pytest.raises(ValueError, match="band"):
        geometry.spec.expansion(2)


def test_rounded_and_beveled_corners_change_only_the_corners():
    result = _two_strand()
    square = build_border(result, BorderSpec(margin=0.25, corner="square"))
    assert len(square.centerlines[0]) == 5
    rounded = build_border(result, BorderSpec(margin=0.25, corner="round", radius=0.2, samples=6))
    ring = rounded.centerlines[0]
    _assert_ring(ring)
    assert len(ring) > 4 * 6  # four sampled arcs plus the straight edges
    assert np.all(ring[:, 0] >= -2.26) and np.all(ring[:, 0] <= 2.26)
    beveled = build_border(result, BorderSpec(margin=0.25, corner="bevel", radius=0.2))
    beveled_ring = beveled.centerlines[0]
    _assert_ring(beveled_ring)
    assert len(beveled_ring) == 9  # four corners replaced by two points each
    assert not np.any(np.all(np.isclose(beveled_ring, [2.25, -2.25]), axis=1))


def test_border_takes_its_colour_from_a_palette():
    geometry = build_border(_two_strand(), BorderSpec(color_index=1))
    palette = get_palette("haru")
    assert geometry.color_index == 1
    assert geometry.color(palette) == palette.colors[1]
    # The default picks the deepest colour, not the paper-like last one, and that
    # colour is dark enough to read as a frame on the palette's own paper.
    default = build_border(_two_strand(), BorderSpec()).color(palette)
    assert default == palette.colors[0]
    assert not is_light(default)
    for name in ("haru", "natsu", "aki", "fuyu", "matsuri", "wabi", "ayame"):
        candidate = get_palette(name)
        assert not is_light(candidate.color(BorderSpec().color_index))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"corner": "diamond"}, "corner"),
        ({"thickness": 0.0}, "thickness"),
        ({"margin": -1.0}, "margin"),
        ({"radius": -0.5}, "radius"),
        ({"bands": 0}, "bands"),
        ({"samples": 0}, "samples"),
        ({"color_index": 1.5}, "color_index"),
    ],
)
def test_border_spec_validates_its_fields(kwargs, match):
    with pytest.raises(ValueError, match=match):
        BorderSpec(**kwargs)


def test_border_rejects_an_inset_that_swallows_the_pattern_and_a_huge_radius():
    result = _two_strand()
    with pytest.raises(ValueError, match="inside the pattern"):
        build_border(result, BorderSpec(margin=0.1, inset=0.5))
    with pytest.raises(ValueError, match="does not fit"):
        build_border(result, BorderSpec(margin=0.25, corner="round", radius=3.0))
    with pytest.raises(ValueError, match="BorderSpec"):
        build_border(result, "thick frame")


# --------------------------------------------------------------------------- #
# Cut-end treatments
# --------------------------------------------------------------------------- #


def test_butt_and_square_outlines_have_exact_areas():
    piece = _straight_piece()
    butt = stroke_piece_outline(piece, 0.1, cap_style="butt")
    _assert_ring(butt.outer)
    assert butt.holes == ()
    assert butt.area == pytest.approx(2 * 0.1 * 2.0)
    square = stroke_piece_outline(piece, 0.1, cap_style="square")
    assert square.area == pytest.approx(2 * 0.1 * 2.2)


def test_round_cap_area_converges_to_the_analytic_value():
    piece = _straight_piece()
    rough = stroke_piece_outline(piece, 0.1, cap_style="round", samples=8)
    _assert_ring(rough.outer)
    fine = stroke_piece_outline(piece, 0.1, cap_style="round", samples=64)
    analytic = 2 * 0.1 * 2.0 + np.pi * 0.1**2
    assert rough.area < fine.area < analytic
    assert fine.area == pytest.approx(analytic, abs=2e-3)
    assert fine.area - rough.area > 5e-4


def test_a_miter_corner_keeps_the_exact_polyline_length():
    piece = StrokePiece(
        piece_id="bent", path_id="P0000",
        points=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]),
        arc_start=0.0, arc_end=2.0,
    )
    outline = stroke_piece_outline(piece, 0.1)
    _assert_ring(outline.outer)
    assert outline.area == pytest.approx(2 * 0.1 * 2.0)


def test_a_closed_centerline_becomes_an_annulus_with_a_clockwise_hole():
    angles = np.linspace(0.0, 2.0 * np.pi, 13)
    ring = np.column_stack((np.cos(angles), np.sin(angles)))
    piece = StrokePiece(
        piece_id="loop", path_id="P0000", points=ring, arc_start=0.0, arc_end=6.0, closed=True
    )
    outline = stroke_piece_outline(piece, 0.1)
    _assert_ring(outline.outer, counter_clockwise=True)
    assert len(outline.holes) == 1
    _assert_ring(outline.holes[0], counter_clockwise=False)
    perimeter = float(np.linalg.norm(np.diff(ring, axis=0), axis=1).sum())
    assert outline.area == pytest.approx(perimeter * 0.2, rel=1e-9)
    # A clockwise centerline is handled too, and the rings still come out oriented.
    reversed_piece = StrokePiece(
        piece_id="loop-cw", path_id="P0000", points=ring[::-1], arc_start=0.0, arc_end=6.0, closed=True
    )
    reversed_outline = stroke_piece_outline(reversed_piece, 0.1)
    _assert_ring(reversed_outline.outer, counter_clockwise=True)
    _assert_ring(reversed_outline.holes[0], counter_clockwise=False)
    assert reversed_outline.area == pytest.approx(outline.area)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"half_width": 0.0}, "half_width"),
        ({"half_width": float("nan")}, "half_width"),
        ({"half_width": 0.1, "cap_style": "flat"}, "cap_style"),
        ({"half_width": 0.1, "samples": 0}, "samples"),
    ],
)
def test_piece_outline_validates_its_arguments(kwargs, match):
    with pytest.raises(ValueError, match=match):
        stroke_piece_outline(_straight_piece(), **kwargs)


def test_piece_outline_refuses_a_collapsed_inner_offset():
    # A 0.05-wide strip of length 2 cannot be inset by more than half its width.
    strip = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 0.05], [0.0, 0.05], [0.0, 0.0]])
    piece = StrokePiece(
        piece_id="strip", path_id="P0000", points=strip, arc_start=0.0, arc_end=4.1, closed=True
    )
    assert stroke_piece_outline(piece, 0.01).holes  # thin enough: the hole survives
    with pytest.raises(ValueError, match="collapsed"):
        stroke_piece_outline(piece, 0.05)


def test_cover_allowance_contract_and_arithmetic():
    assert validate_cover_allowance(0.03, 0.03) == pytest.approx(0.03)
    assert validate_cover_allowance(0.0, 0.03) == 0.0
    with pytest.raises(ValueError, match="exceeds overshoot"):
        validate_cover_allowance(0.04, 0.03)
    with pytest.raises(ValueError, match="non-negative"):
        validate_cover_allowance(-0.01, 0.03)
    with pytest.raises(ValueError, match="overshoot"):
        validate_cover_allowance(0.01, float("nan"))
    assert trim_cut_half_length(1.0, allowance=0.03, offset=0.2) == pytest.approx(0.994)


def test_engine_cover_allowance_shortens_the_gap_and_reports_it():
    plain_engine = LaceEngine(TWO_STRAND, offset=0.2)
    tucked_engine = LaceEngine(TWO_STRAND, offset=0.2, cover_allowance=0.03)
    plain = plain_engine.solve()
    tucked = tucked_engine.solve()
    assert tucked_engine.cover_allowance == pytest.approx(0.03)
    codes = [diagnostic.code for diagnostic in tucked.diagnostics]
    assert "RENDER-COVER-ALLOWANCE" in codes
    under = "P0001"
    plain_spans = sorted((p.arc_start, p.arc_end) for p in plain.pieces if p.path_id == under)
    tucked_spans = sorted((p.arc_start, p.arc_end) for p in tucked.pieces if p.path_id == under)
    assert len(plain_spans) == len(tucked_spans) == 2
    # Both ends of the gap move towards the crossing.
    assert tucked_spans[0][1] == pytest.approx(plain_spans[0][1] + 0.03 * 0.2)
    assert tucked_spans[1][0] == pytest.approx(plain_spans[1][0] - 0.03 * 0.2)
    crossing_arc = plain.crossings[0].s_b if plain.crossings[0].path_b == under else plain.crossings[0].s_a
    assert tucked_spans[0][1] < crossing_arc < tucked_spans[1][0]
    # Crossings and assignments are untouched by the cut-end treatment.
    assert [c.point for c in plain.crossings] == [c.point for c in tucked.crossings]


def test_engine_rejects_a_cover_allowance_larger_than_the_cut_slack():
    with pytest.raises(ValueError, match="exceeds overshoot"):
        LaceEngine(TWO_STRAND, offset=0.2, cover_allowance=0.05)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"style": "flat"}, "style"),
        ({"cover_allowance": -0.1}, "cover_allowance"),
        ({"samples": 0}, "samples"),
    ],
)
def test_cap_treatment_validates_its_fields(kwargs, match):
    with pytest.raises(ValueError, match=match):
        CapTreatment(**kwargs)


def test_cap_treatment_bundles_style_allowance_and_outline():
    treatment = CapTreatment(style="square", cover_allowance=0.02, samples=4)
    assert treatment.validated_allowance(overshoot=0.03) == pytest.approx(0.02)
    with pytest.raises(ValueError, match="exceeds overshoot"):
        treatment.validated_allowance(overshoot=0.01)
    outline = treatment.outline(_straight_piece(), 0.1)
    assert outline.cap_style == "square"
    assert outline.area == pytest.approx(0.44)


# --------------------------------------------------------------------------- #
# Density-aware simplification
# --------------------------------------------------------------------------- #


def test_a_sparse_pattern_is_not_dense():
    report = analyze_density(_two_strand())
    assert report.crossing_count == 1
    assert report.max_per_cell == 1
    assert report.clusters == ()
    assert not report.is_dense
    assert report.dense_crossing_ids == frozenset()
    hotspots = report.hotspots(3)
    assert len(hotspots) == 1 and hotspots[0][1] == 1
    assert report.cell_count(hotspots[0][0]) == 1


def test_a_dense_pattern_is_clustered_with_a_cell_hotspot():
    report = analyze_density(_dense_result())
    assert report.crossing_count == 8
    assert report.is_dense
    assert len(report.clusters) == 1
    cluster = report.clusters[0]
    assert cluster.size == 8
    assert cluster.cluster_id == "C000"
    assert 0.0 < cluster.radius <= 2.0 * report.cluster_radius
    assert report.max_per_cell >= 2
    assert len(report.dense_crossing_ids) == 8
    assert 0.3 < cluster.centroid[0] < 1.1
    assert abs(cluster.centroid[1]) < 1e-9


def test_density_scales_can_be_pinned_and_are_validated():
    result = _dense_result()
    coarse = analyze_density(result, cluster_radius=0.01, min_cluster_size=2)
    assert coarse.clusters == ()  # nothing is that close together
    fine = analyze_density(result, cluster_radius=0.5, min_cluster_size=2)
    assert fine.clusters and fine.clusters[0].size == 8
    with pytest.raises(ValueError, match="cluster_radius"):
        analyze_density(result, cluster_radius=0.0)
    with pytest.raises(ValueError, match="cell_size"):
        analyze_density(result, cluster_radius=0.1, cell_size=-1.0)
    with pytest.raises(ValueError, match="min_cluster_size"):
        analyze_density(result, min_cluster_size=1)


def test_simplification_hides_only_short_slivers_inside_a_cluster():
    result = _dense_result()
    board = len(result.pieces)
    simplification = simplify_for_density(result, DensityPolicy())
    assert simplification.applied
    assert simplification.dropped_count == 3
    assert [d.code for d in simplification.diagnostics] == ["RENDER-DENSITY-SIMPLIFIED"]
    assert len(simplification.kept_ids) + len(simplification.dropped_ids) == board
    dropped = {p.piece_id: p for p in result.pieces if p.piece_id in simplification.dropped_ids}
    assert set(dropped) == {"P0000.piece1", "P0000.piece2", "P0000.piece3"}
    for piece in dropped.values():
        assert piece.arc_end - piece.arc_start < simplification.threshold
    kept = simplification.kept(result)
    assert {p.piece_id for p in kept} == set(simplification.kept_ids)
    # The engine's own result is untouched: nothing was removed from it.
    assert len(result.pieces) == board


def test_simplification_can_be_disabled_or_tightened():
    result = _dense_result()
    assert not simplify_for_density(result, DensityPolicy(enabled=False)).applied
    assert not simplify_for_density(result, DensityPolicy(sliver_length=1e-3)).applied
    assert not simplify_for_density(result, DensityPolicy(min_cluster_size=20)).applied
    tight = simplify_for_density(result, DensityPolicy(sliver_length=1.0))
    assert tight.applied and tight.dropped_count >= 3


def test_simplification_of_a_sparse_pattern_keeps_every_piece():
    result = _two_strand()
    simplification = simplify_for_density(result, DensityPolicy())
    assert not simplification.applied
    assert simplification.diagnostics == ()
    assert simplification.kept_ids == tuple(p.piece_id for p in result.pieces)
    assert simplification.threshold > 0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"cluster_radius": 0.0}, "cluster_radius"),
        ({"cell_size": -1.0}, "cell_size"),
        ({"sliver_length": 0.0}, "sliver_length"),
        ({"sliver_fraction": -0.5}, "sliver_fraction"),
        ({"min_cluster_size": 1}, "min_cluster_size"),
    ],
)
def test_density_policy_validates_its_fields(kwargs, match):
    with pytest.raises(ValueError, match=match):
        DensityPolicy(**kwargs)


def test_ribbon_results_report_that_density_simplification_is_skipped():
    pytest.importorskip("shapely")
    dense = _dense_result()
    result = LaceEngine(
        [np.asarray(path.points) for path in dense.paths], offset=0.05, render_mode="ribbon"
    ).solve()
    simplification = simplify_for_density(result, DensityPolicy())
    assert not simplification.applied
    assert [d.code for d in simplification.diagnostics] == ["RENDER-DENSITY-SKIPPED"]
    assert simplification.diagnostics[0].details["pieces"] == len(result.pieces)
    assert len(simplification.kept_ids) == len(result.pieces)
    # A sparse ribbon result has nothing to simplify, so it stays quiet.
    quiet = simplify_for_density(
        LaceEngine(TWO_STRAND, offset=0.2, render_mode="ribbon").solve(), DensityPolicy()
    )
    assert quiet.diagnostics == ()


def test_ribbon_mode_reports_an_ignored_cover_allowance():
    pytest.importorskip("shapely")
    result = LaceEngine(TWO_STRAND, offset=0.2, render_mode="ribbon", cover_allowance=0.02).solve()
    codes = [diagnostic.code for diagnostic in result.diagnostics]
    assert "RENDER-COVER-ALLOWANCE-IGNORED" in codes
    assert "RENDER-COVER-ALLOWANCE" not in codes
