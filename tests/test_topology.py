from manim_lace.model import CrossingEvent
from manim_lace.topology.solver import solve_weave


def event(cid, pa, pb, ia, ib, sa, sb):
    return CrossingEvent(
        crossing_id=cid, kind="transverse", point=(0.0, 0.0),
        path_a=pa, path_b=pb, path_index_a=ia, path_index_b=ib,
        s_a=sa, s_b=sb, segment_a=0, segment_b=0,
        u_a=0.5, u_b=0.5, sin_angle=1.0,
    )


def test_one_crossing_has_one_over_and_one_under():
    crossing = event("X0000", "a", "b", 0, 1, 1.0, 1.0)
    topology = solve_weave([crossing], ["a", "b"], mode="alternating")
    assignment = topology.assignment_for("X0000")
    assert assignment is not None
    assert assignment.under_side != assignment.over_side


def test_manual_mode_requires_all_crossings():
    crossing = event("X0000", "a", "b", 0, 1, 1.0, 1.0)
    topology = solve_weave([crossing], ["a", "b"], mode="manual", manual={})
    assert "X0000" not in topology.assignments
    assert any(d.code == "TOPOLOGY-MANUAL-ASSIGNMENT-MISSING" for d in topology.diagnostics)


def test_free_mode_accepts_explicit_assignment():
    crossing = event("X0000", "a", "b", 0, 1, 1.0, 1.0)
    topology = solve_weave([crossing], ["a", "b"], mode="free", manual={"X0000": "b"})
    assert topology.assignments["X0000"].over_side == "b"
    assert topology.assignments["X0000"].source == "manual"


def test_self_crossing_with_even_pass_gap_reports_conflict():
    # A self-crossing X0000 has two visits at arcs 1 and 5. The A-B event at
    # arc 3 sits between them, so the self-crossing visits occupy positions 0
    # and 2 in A's sequence: strict alternation cannot satisfy this event.
    crossings = [
        CrossingEvent(
            crossing_id="X0000", kind="transverse", point=(0.0, 0.0),
            path_a="a", path_b="a", path_index_a=0, path_index_b=0,
            s_a=1.0, s_b=5.0, segment_a=0, segment_b=2,
            u_a=0.5, u_b=0.5, sin_angle=1.0,
        ),
        event("X0001", "a", "b", 0, 1, 3.0, 2.0),
    ]
    topology = solve_weave(crossings, ["a", "b"], mode="alternating", conflict_strategy="error")
    assert topology.assignments == {}
    assert any(d.code == "TOPOLOGY-ALTERNATION-UNSAT" for d in topology.diagnostics)


def test_the_default_strategy_relaxes_the_same_input_instead_of_giving_up():
    # The same unsatisfiable input, solved the way the engine does by default: the
    # automatic alternation is kept where it holds and only the forced crossing is
    # relaxed and marked, so a renderer always has an over/under for every crossing.
    crossings = [
        CrossingEvent(
            crossing_id="X0000", kind="transverse", point=(0.0, 0.0),
            path_a="a", path_b="a", path_index_a=0, path_index_b=0,
            s_a=1.0, s_b=5.0, segment_a=0, segment_b=2,
            u_a=0.5, u_b=0.5, sin_angle=1.0,
        ),
        event("X0001", "a", "b", 0, 1, 3.0, 2.0),
    ]
    topology = solve_weave(crossings, ["a", "b"], mode="alternating")
    assert set(topology.assignments) == {"X0000", "X0001"}
    assert any(a.source == "relaxed" for a in topology.assignments.values())
    assert topology.assignments["X0001"].source == "alternating"
    codes = [d.code for d in topology.diagnostics]
    assert codes.count("TOPOLOGY-ALTERNATION-RELAXED") == 1
    assert "TOPOLOGY-ALTERNATION-UNSAT" not in codes
