import numpy as np
import pytest

from manim_lace import LaceEngine


def _spans(result, path_id):
    return sorted((p.arc_start, p.arc_end) for p in result.pieces if p.path_id == path_id)


def _assert_pieces_disjoint_and_bounded(result):
    """Invariant: one path's pieces never overlap and are never longer than it."""
    for path in result.paths:
        spans = _spans(result, path.path_id)
        for (start_a, end_a), (start_b, end_b) in zip(spans, spans[1:]):
            assert end_a <= start_b + 1e-9, (path.path_id, spans)
        for start, end in spans:
            assert start >= -1e-9, (path.path_id, spans)
            assert end - start <= path.length + 1e-9, (path.path_id, spans)


def test_crossing_splits_the_under_path():
    paths = [
        np.array([[-2.0, 0.0], [2.0, 0.0]]),
        np.array([[0.0, -2.0], [0.0, 2.0]]),
    ]
    result = LaceEngine(paths, offset=0.2, weave_mode="alternating").solve()
    assert len(result.crossings) == 1
    assert len(result.topology.assignments) == 1
    assert len(result.pieces) == 3
    pieces_by_path = {}
    for piece in result.pieces:
        pieces_by_path.setdefault(piece.path_id, []).append(piece)
    assert sorted(map(len, pieces_by_path.values())) == [1, 2]


def test_trace_contains_real_pipeline_events():
    paths = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, -1.0], [0.0, 1.0]])]
    result = LaceEngine(paths).solve()
    event_types = {event.event_type for event in result.trace}
    assert "path.normalized" in event_types
    assert "crossing.detected" in event_types
    assert "crossing.assigned" in event_types
    assert "stroke.piece" in event_types
    assert "result.complete" in event_types


def test_closed_path_crossings_split_without_nonfinite_piece_data():
    theta = np.linspace(0, 2 * np.pi, 129)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    horizontal = np.array([[-1.5, 0.0], [1.5, 0.0]])
    result = LaceEngine([circle, horizontal], offset=0.08, weave_mode="free").solve()
    assert len([c for c in result.crossings if c.kind == "transverse"]) == 2
    assert result.pieces
    assert all(np.isfinite(piece.points).all() for piece in result.pieces)
    assert all(len(piece.points) >= 2 for piece in result.pieces)


def test_closed_path_fully_cut_is_reported_not_doubled():
    theta = np.linspace(0, 2 * np.pi, 33)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    horizontal = np.array([[-2.0, 0.0], [2.0, 0.0]])
    result = LaceEngine([circle, horizontal], offset=10.0, weave_mode="free").solve()
    assert any(d.code == "RENDER-PATH-FULLY-CUT" for d in result.diagnostics)


def test_uncut_closed_path_is_emitted_as_one_closed_piece():
    theta = np.linspace(0, 2 * np.pi, 129)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    result = LaceEngine([circle], offset=0.1).solve()
    assert len(result.pieces) == 1
    piece = result.pieces[0]
    assert piece.closed
    assert piece.arc_start == 0.0
    assert piece.arc_end == pytest.approx(result.paths[0].length)
    assert np.allclose(piece.points[0], piece.points[-1])


def test_under_cut_wrapping_the_closed_seam_does_not_duplicate_geometry():
    # The circle is the under-side exactly at its own seam (arc 0), so the cut
    # wraps and the visible arc must be split into a seam piece plus one piece.
    theta = np.linspace(0, 2 * np.pi, 257)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    horizontal = np.array([[-2.0, 0.0], [2.0, 0.0]])
    result = LaceEngine(
        [circle, horizontal], offset=0.12, weave_mode="manual", manual_over={"X0000": "b"}
    ).solve()
    pieces = [p for p in result.pieces if p.path_id == "P0000"]
    assert len(pieces) == 2
    assert any(p.piece_id.endswith("piece-seam") for p in pieces)
    length = result.paths[0].length
    spans = _spans(result, "P0000")
    _assert_pieces_disjoint_and_bounded(result)
    # Neither piece may cover the whole loop: the cut around the seam must stay empty.
    assert not any(start <= 1e-9 and end >= length - 1e-9 for start, end in spans)
    # The seam piece wraps by exactly the length removed before arc 0.
    assert spans[0][0] == pytest.approx(spans[-1][1] - length, abs=1e-6)
    assert spans[0][1] == pytest.approx(spans[-1][0], abs=1e-6)
    assert sum(end - start for start, end in spans) == pytest.approx(length, abs=1e-6)


def test_open_path_fully_cut_reports_diagnostic_without_phantom_pieces():
    result = LaceEngine(
        [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, -1.0], [0.0, 1.0]])],
        offset=5.0,
        weave_mode="free",
    ).solve()
    fully_cut = [d for d in result.diagnostics if d.code == "RENDER-PATH-FULLY-CUT"]
    assert len(fully_cut) == 1
    assert fully_cut[0].path_ids == ("P0001",)
    assert {piece.path_id for piece in result.pieces} == {"P0000"}
    _assert_pieces_disjoint_and_bounded(result)


@pytest.mark.parametrize(
    ("weave_mode", "offset"),
    [("free", 0.08), ("alternating", 0.2), ("free", 0.45)],
)
def test_piece_arc_intervals_stay_disjoint_and_bounded(weave_mode, offset):
    theta = np.linspace(0, 2 * np.pi, 181)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    paths = [
        circle,
        np.array([[-1.5, -0.3], [1.5, 0.3]]),
        np.array([[-1.5, 0.3], [1.5, -0.3]]),
    ]
    result = LaceEngine(paths, offset=offset, weave_mode=weave_mode).solve()
    _assert_pieces_disjoint_and_bounded(result)


def test_shallow_angle_cut_is_bounded_by_min_sin():
    # The two paths form a sin(theta)=0.01 crossing; the cut half-width is
    # clamped by min_sin instead of exploding towards offset/sin(theta).
    paths = [
        np.array([[-2.0, 0.0], [2.0, 0.0]]),
        np.array([[-2.0, -0.02], [2.0, 0.02]]),
    ]
    result = LaceEngine(paths, offset=0.1, weave_mode="free").solve()
    assert any(d.code == "RENDER-SHALLOW-ANGLE-APPROXIMATION" for d in result.diagnostics)
    event = result.crossings[0]
    assert abs(event.sin_angle) < 0.2  # clamped by min_sin, not offset / sin(theta)
    radius = 0.1 / 0.2 + 0.03 * 0.1  # offset / min_sin + overshoot * offset
    spans = _spans(result, "P0001")
    assert len(spans) == 2
    assert spans[0][1] == pytest.approx(event.s_b - radius, abs=1e-6)
    assert spans[1][0] == pytest.approx(event.s_b + radius, abs=1e-6)
    _assert_pieces_disjoint_and_bounded(result)


def test_unsatisfiable_alternation_is_not_cut_and_keeps_full_pieces():
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    vertical = np.array([[-1.2, 0.0], [1.2, 0.0]])
    result = LaceEngine([bow, vertical], offset=0.15, weave_mode="alternating").solve()
    transverse = [c for c in result.crossings if c.kind == "transverse"]
    assert transverse
    assert result.topology.assignments == {}
    assert any(d.code == "TOPOLOGY-ALTERNATION-UNSAT" for d in result.diagnostics)
    missing = [d for d in result.diagnostics if d.code == "RENDER-MISSING-ASSIGNMENT"]
    assert len(missing) == len(transverse)
    assert len(result.pieces) == 2
    for piece, path in zip(result.pieces, result.paths, strict=True):
        assert piece.arc_end - piece.arc_start == pytest.approx(path.length)


def test_short_pieces_are_dropped_with_a_diagnostic():
    theta = np.linspace(0, 2 * np.pi, 721)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    result = LaceEngine(
        [
            circle,
            np.array([[-1.5, -0.35], [1.5, -0.35]]),
            np.array([[-1.5, 0.35], [1.5, 0.35]]),
        ],
        offset=0.4,
        weave_mode="free",
        min_piece_length=0.4,
    ).solve()
    dropped = [d for d in result.diagnostics if d.code == "RENDER-PIECE-DROPPED"]
    assert dropped
    assert all(d.details["dropped_count"] >= 1 for d in dropped)
    assert all(piece.arc_end - piece.arc_start >= 0.4 - 1e-9 for piece in result.pieces)
    _assert_pieces_disjoint_and_bounded(result)


def test_degenerate_path_produces_no_piece():
    from manim_lace import PolylinePath

    result = LaceEngine(
        [
            PolylinePath(np.array([[0.0, 0.0], [0.0, 0.0]]), path_id="zero"),
            np.array([[-1.0, 0.0], [1.0, 0.0]]),
        ],
        offset=0.1,
    ).solve()
    assert any(d.code == "GEOM-DEGENERATE-PATH" for d in result.diagnostics)
    assert {piece.path_id for piece in result.pieces} == {"P0001"}


def test_invalid_stroke_parameters_raise_value_error():
    paths = [np.array([[0.0, 0.0], [1.0, 0.0]])]
    with pytest.raises(ValueError):
        LaceEngine(paths, min_piece_length=-1.0)
    with pytest.raises(ValueError):
        LaceEngine(paths, overshoot=-0.5).solve()
