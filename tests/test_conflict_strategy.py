"""Minimal conflict witnesses and the FR-045 conflict strategies."""

import json

import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.animation import trace_to_jsonable
from manim_lace.model import CrossingEvent
from manim_lace.topology.solver import solve_weave


def event(cid, pa, pb, ia, ib, sa, sb):
    return CrossingEvent(
        crossing_id=cid, kind="transverse", point=(0.0, 0.0),
        path_a=pa, path_b=pb, path_index_a=ia, path_index_b=ib,
        s_a=sa, s_b=sb, segment_a=0, segment_b=0,
        u_a=0.5, u_b=0.5, sin_angle=1.0,
    )


def odd_cycle_with_tail():
    """An odd parity walk over a-b-a-b plus a consistent crossing to a fourth path.

    Pass positions: a: X0000, X0003, X0002 | b: X0000, X0001 | c: X0001, X0002 |
    d: X0003. The walk a-b (X0000), b-c (X0001), c-a (X0002) carries an odd total
    parity, while X0003 hangs off ``a`` without participating in the conflict.
    """
    return [
        event("X0000", "a", "b", 0, 1, 1.0, 1.0),
        event("X0001", "b", "c", 1, 2, 2.0, 1.0),
        event("X0002", "a", "c", 0, 2, 3.0, 2.0),
        event("X0003", "a", "d", 0, 3, 2.0, 1.0),
    ]


def bow_and_line():
    """A real unsatisfiable input: a bow-tie polyline cut by a horizontal line."""
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    line = np.array([[-1.2, 0.0], [1.2, 0.0]])
    return [bow, line]


def unsat_diagnostic(topology):
    return next(d for d in topology.diagnostics if d.code == "TOPOLOGY-ALTERNATION-UNSAT")


def test_error_strategy_reports_only_the_minimal_witness_set():
    crossings = odd_cycle_with_tail()
    topology = solve_weave(
        crossings, ["a", "b", "c", "d"], mode="alternating", conflict_strategy="error"
    )
    assert topology.assignments == {}
    diagnostic = unsat_diagnostic(topology)
    details = diagnostic.details
    assert details["crossing_ids"] == ["X0000", "X0001", "X0002"]  # X0003 is not part of it
    witnesses = details["witnesses"]
    assert len(witnesses) == 1
    assert witnesses[0]["kind"] == "odd_cycle"
    assert witnesses[0]["crossing_ids"] == ["X0000", "X0001", "X0002"]
    assert witnesses[0]["path_ids"] == ["a", "b", "c"]
    assert diagnostic.severity.value == "error"


def test_self_crossing_conflict_is_its_own_witness():
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
    details = unsat_diagnostic(topology).details
    assert details["self_conflicts"] == ["X0000"]
    assert details["crossing_ids"] == ["X0000"]
    assert details["constraint_conflicts"] == []
    self_witness = [w for w in details["witnesses"] if w["kind"] == "self_crossing"]
    assert len(self_witness) == 1
    assert self_witness[0]["crossing_ids"] == ["X0000"]
    assert "相距 2" in self_witness[0]["detail"]


def test_relax_strategy_breaks_one_edge_and_keeps_the_rest_alternating():
    crossings = odd_cycle_with_tail()
    topology = solve_weave(crossings, ["a", "b", "c", "d"], mode="alternating",
                           conflict_strategy="relax")
    assert set(topology.assignments) == {c.crossing_id for c in crossings}
    relaxed = [cid for cid, a in topology.assignments.items() if a.source == "relaxed"]
    assert relaxed == ["X0001"]
    diagnostic = next(d for d in topology.diagnostics if d.code == "TOPOLOGY-ALTERNATION-RELAXED")
    assert diagnostic.severity.value == "warning"
    assert diagnostic.details["relaxed_crossing_ids"] == ["X0001"]
    assert diagnostic.details["crossing_ids"] == ["X0000", "X0001", "X0002"]
    assert not any(d.code == "TOPOLOGY-ALTERNATION-UNSAT" for d in topology.diagnostics)
    # Every crossing still has a well-defined over and under side.
    for assignment in topology.assignments.values():
        assert assignment.over_side != assignment.under_side
    assert topology.assignments["X0000"].over_side == "a"
    assert topology.assignments["X0002"].over_side == "a"
    assert topology.assignments["X0003"].over_side == "b"


def test_manual_strategy_keeps_the_user_side_as_a_hard_constraint():
    crossings = odd_cycle_with_tail()
    topology = solve_weave(crossings, ["a", "b", "c", "d"], mode="alternating",
                           manual={"X0001": "b"}, conflict_strategy="manual")
    assignment = topology.assignments["X0001"]
    assert assignment.over_side == "b"
    assert assignment.source == "manual"
    assert set(topology.assignments) == {c.crossing_id for c in crossings}
    relaxed = {cid for cid, a in topology.assignments.items() if a.source == "relaxed"}
    assert relaxed <= {"X0000", "X0001", "X0002"}
    assert not any(d.code == "TOPOLOGY-MANUAL-OVERRIDE" for d in topology.diagnostics)


def test_manual_strategy_reports_contradicting_manual_sides():
    crossings = odd_cycle_with_tail()
    topology = solve_weave(crossings, ["a", "b", "c", "d"], mode="alternating",
                           manual={"X0000": "a", "X0003": "a"}, conflict_strategy="manual")
    # X0000 pins path a at pass 0, X0003 asks for pass 2 of the same path.
    conflict = next(d for d in topology.diagnostics if d.code == "TOPOLOGY-MANUAL-CONFLICT")
    assert conflict.details["crossing_ids"] == ["X0003"]
    assert topology.assignments["X0000"].source == "manual"
    assert topology.assignments["X0003"].source == "alternating"


def test_manual_strategy_agrees_with_alternation_when_it_can():
    # Two crossings between the same pair of paths: pinning one side keeps both
    # crossings alternating instead of overriding one of them.
    crossings = [
        event("X0000", "a", "b", 0, 1, 1.0, 1.0),
        event("X0001", "a", "b", 0, 1, 3.0, 3.0),
    ]
    topology = solve_weave(crossings, ["a", "b"], mode="alternating",
                           manual={"X0000": "b"}, conflict_strategy="manual")
    assert topology.assignments["X0000"].over_side == "b"
    assert topology.assignments["X0000"].source == "manual"
    assert topology.assignments["X0001"].over_side == "a"
    assert topology.diagnostics == []


def test_manual_override_is_only_reported_when_it_disagrees():
    crossings = [
        event("X0000", "a", "b", 0, 1, 1.0, 1.0),
        event("X0001", "a", "b", 0, 1, 3.0, 3.0),
    ]
    automatic = solve_weave(crossings, ["a", "b"], mode="alternating")
    agreeing_side = automatic.assignments["X0000"].over_side
    agreed = solve_weave(crossings, ["a", "b"], mode="alternating", manual={"X0000": agreeing_side})
    assert agreed.assignments["X0000"].source == "manual"
    assert not any(d.code == "TOPOLOGY-MANUAL-OVERRIDE" for d in agreed.diagnostics)

    other_side = "b" if agreeing_side == "a" else "a"
    disagreed = solve_weave(crossings, ["a", "b"], mode="alternating", manual={"X0000": other_side})
    assert disagreed.assignments["X0000"].over_side == other_side
    assert any(d.code == "TOPOLOGY-MANUAL-OVERRIDE" for d in disagreed.diagnostics)


@pytest.mark.parametrize("strategy", ["error", "manual", "relax"])
def test_conflict_strategy_is_validated(strategy):
    solve_weave([], ["a"], mode="alternating", conflict_strategy=strategy)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        solve_weave([], ["a"], mode="alternating", conflict_strategy="guess")  # type: ignore[arg-type]


def test_the_default_engine_strategy_relaxes_and_marks_instead_of_giving_up():
    # Pins the contract that matters for the interactive path: the default must weave.
    # Strict alternation that cannot hold is relaxed as little as possible and every
    # exception is visible, so no caller ever gets an unweaveable empty assignment.
    result = LaceEngine(bow_and_line(), offset=0.15, weave_mode="alternating").solve()
    transverse = [c for c in result.crossings if c.kind == "transverse"]
    assert transverse
    assert set(result.topology.assignments) == {c.crossing_id for c in transverse}
    sources = [a.source for a in result.topology.assignments.values()]
    assert "relaxed" in sources
    assert sources.count("relaxed") < len(sources)
    codes = [d.code for d in result.diagnostics]
    assert "TOPOLOGY-ALTERNATION-RELAXED" in codes
    assert "TOPOLOGY-ALTERNATION-UNSAT" not in codes


def test_engine_relax_keeps_every_crossing_assignable():
    result = LaceEngine(
        bow_and_line(), offset=0.15, weave_mode="alternating", conflict_strategy="relax"
    ).solve()
    transverse = [c for c in result.crossings if c.kind == "transverse"]
    assert transverse
    assert set(result.topology.assignments) == {c.crossing_id for c in transverse}
    assert any(a.source == "relaxed" for a in result.topology.assignments.values())
    codes = [d.code for d in result.diagnostics]
    assert "TOPOLOGY-ALTERNATION-RELAXED" in codes
    assert "TOPOLOGY-ALTERNATION-UNSAT" not in codes
    assert "RENDER-MISSING-ASSIGNMENT" not in codes
    traced = [event for event in result.trace if event.event_type == "crossing.assigned"]
    assert any(event.data["source"] == "relaxed" for event in traced)
    assert {event.data["source"] for event in traced} >= {"alternating", "relaxed"}


def test_engine_manual_strategy_keeps_the_user_side_on_an_unsatisfiable_input():
    bow, line = bow_and_line()
    result = LaceEngine(
        [bow, line], offset=0.15, weave_mode="alternating",
        manual_over={"X0001": "a"}, conflict_strategy="manual",
    ).solve()
    assignment = result.topology.assignment_for("X0001")
    assert assignment is not None
    assert assignment.over_side == "a"
    assert assignment.source in {"manual", "relaxed"}
    assert any(d.code == "TOPOLOGY-ALTERNATION-RELAXED" for d in result.diagnostics)


def test_engine_rejects_an_unknown_conflict_strategy():
    with pytest.raises(ValueError):
        LaceEngine(bow_and_line(), conflict_strategy="guess")  # type: ignore[arg-type]


def test_conflict_details_stay_json_serializable():
    result = LaceEngine(
        bow_and_line(), offset=0.15, weave_mode="alternating", conflict_strategy="relax"
    ).solve()
    payload = json.dumps(trace_to_jsonable(result.trace), ensure_ascii=False)
    assert "TOPOLOGY-ALTERNATION-RELAXED" in payload
    assert "witnesses" in payload


@pytest.mark.parametrize("strategy", ["relax", "manual"])
def test_relaxation_is_deterministic(strategy):
    first = solve_weave(odd_cycle_with_tail(), ["a", "b", "c", "d"], mode="alternating",
                        conflict_strategy=strategy)  # type: ignore[arg-type]
    second = solve_weave(odd_cycle_with_tail(), ["a", "b", "c", "d"], mode="alternating",
                         conflict_strategy=strategy)  # type: ignore[arg-type]
    assert first.assignments == second.assignments
    assert [d.details for d in first.diagnostics] == [d.details for d in second.diagnostics]
