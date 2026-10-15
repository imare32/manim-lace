"""Event policies: what happens to candidates that are not plain crossings (FR-032)."""

import numpy as np
import pytest

from manim_lace import EventPolicy, LaceEngine, PolylinePath
from manim_lace.geometry.intersections import detect_crossings
from manim_lace.model import normalize_event_policy


def _codes(result):
    return [diagnostic.code for diagnostic in result.diagnostics]


def _junction_paths():
    return [
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, 0.0], [0.0, 1.0]]), path_id="b"),
    ]


def _shallow_paths():
    return [
        PolylinePath(np.array([[0.0, 0.0], [1e9, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, -1.0], [1e9, 1.0]]), path_id="b"),
    ]


def _overlap_paths():
    return [
        PolylinePath(np.array([[0.0, 0.0], [2.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[1.0, 0.0], [3.0, 0.0]]), path_id="b"),
    ]


def _multiway_paths():
    return [
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, -1.0], [0.0, 1.0]]), path_id="b"),
        PolylinePath(np.array([[-1.0, -1.0], [1.0, 1.0]]), path_id="c"),
    ]


CONTACTS = [
    (_junction_paths, "endpoint_touch", "GEOM-ENDPOINT_TOUCH"),
    (_shallow_paths, "near_tangent", "GEOM-NEAR_TANGENT"),
]


@pytest.mark.parametrize(("build", "kind", "warning"), CONTACTS)
def test_default_policy_reports_the_contact_and_its_warning(build, kind, warning):
    result = detect_crossings(build())
    assert [event.kind for event in result.crossings] == [kind]
    assert warning in _codes(result)


@pytest.mark.parametrize(("build", "kind", "warning"), CONTACTS)
def test_ignore_policy_keeps_the_event_and_drops_the_warning(build, kind, warning):
    result = detect_crossings(build(), policy=EventPolicy(**{kind: "ignore"}))
    assert [event.kind for event in result.crossings] == [kind]
    assert result.diagnostics == []


@pytest.mark.parametrize(("build", "kind", "warning"), CONTACTS)
def test_weave_policy_promotes_contacts_into_the_solver(build, kind, warning):
    result = detect_crossings(build(), policy=EventPolicy(**{kind: "weave"}))
    assert [event.kind for event in result.crossings] == ["transverse"]
    assert warning not in _codes(result)
    woven = [d for d in result.diagnostics if d.code == "GEOM-CONTACT-WOVEN"]
    assert len(woven) == 1
    assert woven[0].severity.value == "info"
    assert woven[0].crossing_id == result.crossings[0].crossing_id
    assert woven[0].details["classified_as"] == kind


def test_overlap_policy_only_controls_the_warning():
    diagnosed = detect_crossings(_overlap_paths())
    assert diagnosed.crossings == []
    assert _codes(diagnosed) == ["GEOM-COLLINEAR-OVERLAP"]

    ignored = detect_crossings(_overlap_paths(), policy=EventPolicy(collinear_overlap="ignore"))
    # An overlap is an interval, so it never becomes an event either way.
    assert ignored.crossings == []
    assert ignored.diagnostics == []


def test_multiway_policy_only_controls_the_warning():
    diagnosed = detect_crossings(_multiway_paths())
    assert {event.kind for event in diagnosed.crossings} == {"multiway"}
    assert "GEOM-MULTIWAY-CROSSING" in _codes(diagnosed)

    ignored = detect_crossings(_multiway_paths(), policy=EventPolicy(multiway="ignore"))
    assert {event.kind for event in ignored.crossings} == {"multiway"}
    assert ignored.diagnostics == []


def test_normalize_event_policy_accepts_the_documented_shapes():
    assert normalize_event_policy(None) == EventPolicy()
    assert normalize_event_policy("ignore") == EventPolicy(
        endpoint_touch="ignore", near_tangent="ignore",
        collinear_overlap="ignore", multiway="ignore",
    )
    assert normalize_event_policy({"endpoint_touch": "weave"}) == EventPolicy(endpoint_touch="weave")
    explicit = EventPolicy(near_tangent="weave")
    assert normalize_event_policy(explicit) is explicit


@pytest.mark.parametrize(
    "policy",
    [
        "weave",  # cannot be applied to overlaps and multiway nodes
        {"endpoint_touch": "sometimes"},
        {"multiway": "weave"},
        {"not_a_field": "ignore"},
        42,
        (),
    ],
)
def test_invalid_event_policy_is_rejected(policy):
    with pytest.raises(ValueError):
        normalize_event_policy(policy)


def test_policy_validation_reaches_the_engine():
    paths = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, 0.0], [0.0, 1.0]])]
    with pytest.raises(ValueError):
        LaceEngine(paths, event_policy="weave")
    with pytest.raises(ValueError):
        LaceEngine(paths, event_policy={"endpoint_touch": "sometimes"})
    assert LaceEngine(paths, event_policy={"endpoint_touch": "weave"}).event_policy == EventPolicy(
        endpoint_touch="weave"
    )


def test_default_policy_keeps_a_t_junction_out_of_the_weave():
    paths = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, 0.0], [0.0, 1.0]])]
    result = LaceEngine(paths, offset=0.1).solve()
    assert [event.kind for event in result.crossings] == ["endpoint_touch"]
    assert result.topology.assignments == {}
    assert "GEOM-ENDPOINT_TOUCH" in _codes(result)
    assert not any(d.code == "GEOM-CONTACT-WOVEN" for d in result.diagnostics)


def test_weave_policy_actually_cuts_a_promoted_t_junction():
    paths = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, 0.0], [0.0, 1.0]])]
    result = LaceEngine(
        paths, offset=0.1, weave_mode="alternating",
        event_policy=EventPolicy(endpoint_touch="weave"),
    ).solve()
    crossing = result.crossings[0]
    assert crossing.kind == "transverse"
    assert crossing.crossing_id in result.topology.assignments
    assert "GEOM-CONTACT-WOVEN" in _codes(result)
    assert not any(d.code == "RENDER-MISSING-ASSIGNMENT" for d in result.diagnostics)
    # The under path no longer covers the junction, so the contact is visible.
    assignment = result.topology.assignment_for(crossing.crossing_id)
    assert assignment is not None and assignment.under_side != assignment.over_side
    under_path = crossing.path_a if assignment.under_side == "a" else crossing.path_b
    under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
    pieces = [piece for piece in result.pieces if piece.path_id == under_path]
    assert pieces
    assert not any(piece.arc_start <= under_arc <= piece.arc_end for piece in pieces)
    detected = [event for event in result.trace if event.event_type == "crossing.detected"]
    assert [event.data["kind"] for event in detected] == ["transverse"]


def test_manual_override_decides_which_path_of_a_promoted_contact_is_cut():
    paths = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, 0.0], [0.0, 1.0]])]
    result = LaceEngine(
        paths, offset=0.1, event_policy=EventPolicy(endpoint_touch="weave"),
        manual_over={"X0000": "b"},
    ).solve()
    assert result.topology.assignments["X0000"].over_side == "b"
    through = sorted(
        (piece for piece in result.pieces if piece.path_id == "P0000"),
        key=lambda piece: piece.arc_start,
    )
    assert len(through) == 2
    assert through[0].arc_end < result.crossings[0].s_a < through[1].arc_start
    ending = [piece for piece in result.pieces if piece.path_id == "P0001"]
    assert len(ending) == 1 and ending[0].arc_start == 0.0
