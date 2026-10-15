import numpy as np

from manim_lace import LaceEngine


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
