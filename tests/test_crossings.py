import numpy as np

from manim_lace.geometry.intersections import detect_crossings
from manim_lace.model import PolylinePath


def test_two_open_paths_have_one_transverse_crossing():
    paths = [
        PolylinePath(np.array([[-1, 0], [1, 0]]), path_id="horizontal"),
        PolylinePath(np.array([[0, -1], [0, 1]]), path_id="vertical"),
    ]
    result = detect_crossings(paths)
    assert len(result.crossings) == 1
    event = result.crossings[0]
    assert event.kind == "transverse"
    assert np.allclose(event.point, (0, 0))
    assert event.path_a == "horizontal"
    assert event.path_b == "vertical"


def test_non_adjacent_self_crossing_is_found():
    bow = PolylinePath(
        np.array([[-1, -1], [1, 1], [-1, 1], [1, -1]]),
        path_id="bow",
    )
    result = detect_crossings([bow])
    assert len(result.crossings) == 1
    assert result.crossings[0].path_a == result.crossings[0].path_b == "bow"
    assert np.allclose(result.crossings[0].point, (0, 0))


def test_collinear_overlap_is_diagnostic_not_crossing():
    paths = [
        PolylinePath(np.array([[0, 0], [2, 0]]), path_id="a"),
        PolylinePath(np.array([[1, 0], [3, 0]]), path_id="b"),
    ]
    result = detect_crossings(paths)
    assert result.crossings == []
    assert any(d.code == "GEOM-COLLINEAR-OVERLAP" for d in result.diagnostics)


def test_crossing_at_segment_vertices_is_deduplicated():
    paths = [
        PolylinePath(np.array([[-1, 0], [0, 0], [1, 0]]), path_id="a"),
        PolylinePath(np.array([[0, -1], [0, 0], [0, 1]]), path_id="b"),
    ]
    result = detect_crossings(paths)
    # Current MVP classifies segment-endpoint intersections as endpoint-touch;
    # this test freezes deduplication behavior, not ideal crossing semantics.
    assert len(result.crossings) == 1


def test_multiway_crossing_is_not_treated_as_three_binary_crossings():
    paths = [
        PolylinePath(np.array([[-1, 0], [1, 0]]), path_id="a"),
        PolylinePath(np.array([[0, -1], [0, 1]]), path_id="b"),
        PolylinePath(np.array([[-1, -1], [1, 1]]), path_id="c"),
    ]
    result = detect_crossings(paths)
    assert len(result.crossings) == 3
    assert all(event.kind == "multiway" for event in result.crossings)
    assert any(d.code == "GEOM-MULTIWAY-CROSSING" for d in result.diagnostics)


def test_very_shallow_crossing_is_retained_as_near_tangent():
    paths = [
        PolylinePath(np.array([[0.0, 0.0], [1e9, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, -1.0], [1e9, 1.0]]), path_id="b"),
    ]
    result = detect_crossings(paths, angle_tol=1e-8)
    assert len(result.crossings) == 1
    assert result.crossings[0].kind == "near_tangent"
    assert np.allclose(result.crossings[0].point, (5e8, 0.0))


def test_two_distinct_nearby_crossings_are_not_distance_deduplicated():
    # The zig-zag crosses y=0 twice, with points only 1e-5 apart in x.
    paths = [
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="baseline"),
        PolylinePath(np.array([[-1e-5, -1.0], [0.0, 1.0], [1e-5, -1.0]]), path_id="zigzag"),
    ]
    result = detect_crossings(paths, position_tol=1e-7)
    transverse = [event for event in result.crossings if event.kind == "transverse"]
    assert len(transverse) == 2
    assert abs(transverse[0].point[0] - transverse[1].point[0]) > 1e-6
