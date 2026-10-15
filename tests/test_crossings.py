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


def test_t_junction_stays_endpoint_touch_and_is_diagnostic_only():
    paths = [
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, 0.0], [0.0, 1.0]]), path_id="b"),
    ]
    result = detect_crossings(paths)
    assert len(result.crossings) == 1
    assert result.crossings[0].kind == "endpoint_touch"
    assert any(d.code == "GEOM-ENDPOINT_TOUCH" for d in result.diagnostics)


def test_vertex_crossing_on_interior_segments_is_transverse():
    paths = [
        PolylinePath(np.array([[-1.0, -1.0], [0.0, 0.0], [1.0, -1.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, -2.0], [0.0, 2.0]]), path_id="b"),
    ]
    result = detect_crossings(paths)
    assert len(result.crossings) == 1
    event = result.crossings[0]
    assert event.kind == "transverse"
    assert 0.0 < event.sin_angle <= 1.0
    assert np.allclose(event.point, (0.0, 0.0))


def test_repeated_vertices_do_not_demote_a_vertex_crossing():
    # Both paths repeat the crossing vertex, so the local branch rays must skip
    # coincident samples instead of collapsing to a single branch.
    paths = [
        PolylinePath(
            np.array([[-1.0, 0.0], [0.0, 0.0], [0.0, 0.0], [1.0, 0.0]]), path_id="a"
        ),
        PolylinePath(
            np.array([[0.0, -1.0], [0.0, 0.0], [0.0, 0.0], [0.0, 1.0]]), path_id="b"
        ),
    ]
    result = detect_crossings(paths)
    assert len(result.crossings) == 1
    event = result.crossings[0]
    assert event.kind == "transverse"
    assert 0.0 < event.sin_angle <= 1.0
    assert np.allclose(event.point, (0.0, 0.0))


def test_closed_seam_crossing_is_reported_once_at_arc_zero():
    theta = np.linspace(0, 2 * np.pi, 65)
    circle = PolylinePath(
        np.column_stack((np.cos(theta), np.sin(theta))), path_id="circle", closed=True
    )
    horizontal = PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="h")
    result = detect_crossings([circle, horizontal])
    assert len(result.crossings) == 2
    seam = [event for event in result.crossings if np.allclose(event.point, (1.0, 0.0))]
    assert len(seam) == 1
    event = seam[0]
    # The seam is arc 0 of the loop, not the duplicated final index.
    assert min(event.s_a, circle.length - event.s_a) <= 1e-9
    assert event.kind == "transverse"


def test_self_crossing_arc_positions_are_ordered_on_one_path():
    bowtie = PolylinePath(
        np.array([[0.0, 0.0], [2.0, 2.0], [2.0, 0.0], [0.0, 2.0]]),
        path_id="bowtie",
        closed=True,
    )
    result = detect_crossings([bowtie])
    assert len(result.crossings) == 1
    event = result.crossings[0]
    assert event.path_a == event.path_b == "bowtie"
    assert event.s_a < event.s_b
    assert np.allclose(event.point, (1.0, 1.0), atol=1e-9)


def test_detection_is_deterministic_across_runs():
    theta = np.linspace(0, 2 * np.pi, 181)
    paths = [
        PolylinePath(np.column_stack((np.cos(theta), np.sin(theta))), path_id="circle", closed=True),
        PolylinePath(np.array([[-1.5, -0.3], [1.5, 0.3]]), path_id="diag"),
        PolylinePath(np.array([[-1.5, 0.3], [1.5, -0.3]]), path_id="anti"),
    ]
    first, second = detect_crossings(paths), detect_crossings(paths)
    assert _signature(first) == _signature(second)
    assert len(first.crossings) >= 1


def _signature(result):
    return [
        (event.crossing_id, event.kind, event.point, event.s_a, event.s_b)
        for event in result.crossings
    ]


def test_degenerate_zero_length_path_is_diagnosed_and_skipped():
    degenerate = PolylinePath(np.array([[0.0, 0.0], [0.0, 0.0]]), path_id="zero")
    other = PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="a")
    result = detect_crossings([degenerate, other])
    assert result.crossings == []
    diagnostics = [d for d in result.diagnostics if d.code == "GEOM-DEGENERATE-PATH"]
    assert len(diagnostics) == 1
    assert diagnostics[0].path_ids == ("zero",)
