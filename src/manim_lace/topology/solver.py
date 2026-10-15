"""Path-pass ordering and alternating/free over-under assignment."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..diagnostics import Diagnostic, Severity
from ..model import ConflictStrategy, CrossingEvent, Pass, WeaveAssignment, WeaveTopology

WeaveMode = Literal["alternating", "free", "manual"]
TopologyTracer = Callable[[str, dict[str, Any]], None]

#: Over side used when a crossing has to be relaxed and the user gave no side.
RELAXED_OVER_SIDE: Literal["a", "b"] = "a"


def build_passes(crossings: list[CrossingEvent], path_ids: list[str]) -> dict[str, list[Pass]]:
    raw: dict[str, list[tuple[float, str, str]]] = {path_id: [] for path_id in path_ids}
    for crossing in crossings:
        if crossing.kind != "transverse":
            continue
        raw.setdefault(crossing.path_a, []).append((crossing.s_a, crossing.crossing_id, "a"))
        raw.setdefault(crossing.path_b, []).append((crossing.s_b, crossing.crossing_id, "b"))
    result: dict[str, list[Pass]] = {}
    for path_id, rows in raw.items():
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
        result[path_id] = [
            Pass(crossing_id=crossing_id, path_id=path_id, side=side, arc_length=s, position=index)
            for index, (s, crossing_id, side) in enumerate(rows)
        ]
    return result


@dataclass(frozen=True, slots=True)
class _Edge:
    """One parity constraint: the two pass values at a crossing must differ."""

    path_a: str
    path_b: str
    parity: int
    crossing_id: str


@dataclass(frozen=True, slots=True)
class _Witness:
    """One minimal reason why strict alternation has no solution."""

    kind: Literal["odd_cycle", "self_crossing"]
    crossing_ids: tuple[str, ...]
    path_ids: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "crossing_ids": list(self.crossing_ids),
            "path_ids": list(self.path_ids),
            "detail": self.detail,
        }


def _adjacency(
    edges: list[_Edge], path_ids: list[str]
) -> dict[str, list[tuple[str, int, str]]]:
    """Neighbour list keyed by path; entries are ordered by crossing ID."""
    adjacency: dict[str, list[tuple[str, int, str]]] = {path_id: [] for path_id in path_ids}
    for edge in edges:
        adjacency.setdefault(edge.path_a, []).append((edge.path_b, edge.parity, edge.crossing_id))
        adjacency.setdefault(edge.path_b, []).append((edge.path_a, edge.parity, edge.crossing_id))
    for entries in adjacency.values():
        entries.sort(key=lambda entry: (entry[2], entry[0]))
    return adjacency


def _parity_constraints(
    transverse: list[CrossingEvent], positions: dict[tuple[str, str], int]
) -> tuple[list[_Edge], list[CrossingEvent]]:
    """Binary parity edges plus self-crossings whose two passes share a parity."""
    edges: list[_Edge] = []
    self_conflicts: list[CrossingEvent] = []
    for crossing in transverse:
        position_a = positions[(crossing.crossing_id, "a")]
        position_b = positions[(crossing.crossing_id, "b")]
        if crossing.path_a == crossing.path_b:
            if (position_a % 2) == (position_b % 2):
                self_conflicts.append(crossing)
            continue
        edges.append(_Edge(
            path_a=crossing.path_a,
            path_b=crossing.path_b,
            parity=1 ^ (position_a % 2) ^ (position_b % 2),
            crossing_id=crossing.crossing_id,
        ))
    return edges, self_conflicts


def _manual_pins(
    transverse: list[CrossingEvent],
    positions: dict[tuple[str, str], int],
    manual: dict[str, str],
) -> tuple[dict[str, int], list[str]]:
    """Translate manual over sides into hard path-flag pins.

    A manual side fixes the flag of the path that owns it. Two manual sides on the
    same path are compatible only if their passes have the same parity; the earliest
    crossing ID wins and the later one is reported as dropped.
    """
    pins: dict[str, int] = {}
    dropped: list[str] = []
    for crossing in sorted(transverse, key=lambda item: item.crossing_id):
        side = manual.get(crossing.crossing_id)
        if side not in {"a", "b"}:
            continue
        position = positions[(crossing.crossing_id, side)]
        value = 1 ^ (position % 2)
        path_id = crossing.path_a if side == "a" else crossing.path_b
        known = pins.get(path_id)
        if known is None:
            pins[path_id] = value
        elif known != value:
            dropped.append(crossing.crossing_id)
    return pins, dropped


def _seed_order(path_ids: list[str], pins: dict[str, int]) -> list[tuple[str, int]]:
    """Deterministic propagation order: pinned paths first, then the declared order."""
    seeds = [(path_id, pins[path_id]) for path_id in sorted(pins)]
    seeds.extend((path_id, 1) for path_id in path_ids)
    return seeds


def _propagate(
    path_ids: list[str],
    adjacency: dict[str, list[tuple[str, int, str]]],
    seeds: list[tuple[str, int]],
    *,
    tracer: TopologyTracer | None = None,
) -> tuple[dict[str, int], list[tuple[str, str, str]]]:
    """Assign one parity flag per path and collect the edges that contradict them."""
    flags: dict[str, int] = {}
    rejected: list[tuple[str, str, str]] = []
    rejected_ids: set[str] = set()
    for start, value in seeds:
        if start in flags:
            continue
        flags[start] = value
        if tracer is not None:
            tracer("seed", {"path_id": start, "flag": value})
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for other, parity, crossing_id in adjacency[current]:
                expected = flags[current] ^ parity
                if other not in flags:
                    flags[other] = expected
                    queue.append(other)
                    if tracer is not None:
                        tracer("propagate", {
                            "from": current, "to": other, "flag": expected,
                            "crossing_id": crossing_id, "parity": parity,
                        })
                elif flags[other] != expected and crossing_id not in rejected_ids:
                    rejected_ids.add(crossing_id)
                    rejected.append((current, other, crossing_id))
                    if tracer is not None:
                        tracer("reject", {
                            "from": current, "to": other, "crossing_id": crossing_id,
                            "expected": expected, "actual": flags[other],
                        })
    return flags, rejected


def _shortest_alternative(
    adjacency: dict[str, list[tuple[str, int, str]]],
    start: str,
    target: str,
    *,
    forbidden: str,
) -> list[str] | None:
    """Crossing IDs of a shortest path between two paths that avoids one constraint."""
    if start == target:
        return []
    parents: dict[str, tuple[str, str]] = {}
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for other, _parity, crossing_id in adjacency[current]:
            if crossing_id == forbidden or other in seen:
                continue
            seen.add(other)
            parents[other] = (current, crossing_id)
            if other == target:
                trail: list[str] = []
                node = target
                while node != start:
                    previous, edge_id = parents[node]
                    trail.append(edge_id)
                    node = previous
                return list(reversed(trail))
            queue.append(other)
    return None


def _witnesses(
    adjacency: dict[str, list[tuple[str, int, str]]],
    edges_by_id: dict[str, _Edge],
    rejected: list[tuple[str, str, str]],
    self_conflicts: list[CrossingEvent],
    positions: dict[tuple[str, str], int],
) -> list[_Witness]:
    """Minimal conflict explanations: one odd cycle per rejected constraint."""
    witnesses: list[_Witness] = []
    seen: set[tuple[str, ...]] = set()
    for current, other, crossing_id in rejected:
        edge = edges_by_id.get(crossing_id)
        ends = (edge.path_a, edge.path_b) if edge is not None else (current, other)
        alternative = _shortest_alternative(adjacency, current, other, forbidden=crossing_id) or []
        cycle = tuple(sorted({crossing_id, *alternative}))
        if cycle in seen:
            continue
        seen.add(cycle)
        members = set(ends)
        for cycle_id in cycle:
            cycle_edge = edges_by_id.get(cycle_id)
            if cycle_edge is not None:
                members.update((cycle_edge.path_a, cycle_edge.path_b))
        witnesses.append(_Witness(
            kind="odd_cycle",
            crossing_ids=cycle,
            path_ids=tuple(sorted(members)),
            detail=(
                f"{ends[0]} 与 {ends[1]} 之间存在奇偶性冲突的路径环，涉及 {len(cycle)} 个交叉；"
                "环上的约束无法同时满足严格交替。"
            ),
        ))
    for crossing in self_conflicts:
        position_a = positions[(crossing.crossing_id, "a")]
        position_b = positions[(crossing.crossing_id, "b")]
        witnesses.append(_Witness(
            kind="self_crossing",
            crossing_ids=(crossing.crossing_id,),
            path_ids=(crossing.path_a,),
            detail=(
                f"自交 {crossing.crossing_id} 的两次经过在 {crossing.path_a} 的经过序列中相距 "
                f"{position_b - position_a}（偶数）；严格交替要求两者一上一下，无法满足。"
            ),
        ))
    witnesses.sort(key=lambda witness: (witness.kind, witness.crossing_ids))
    return witnesses


def _conflict_details(
    witnesses: list[_Witness],
    rejected: list[tuple[str, str, str]],
    *,
    relaxed: set[str] | None = None,
) -> dict[str, object]:
    """Minimal conflict set plus, when relaxing, the crossings that had to give way.

    ``crossing_ids`` is the minimal set of crossings whose constraints cannot all
    hold (one witness cycle each); ``relaxed_crossing_ids`` is the subset that
    actually received a relaxed assignment, which can be smaller because breaking any
    single edge of a witness cycle is enough.
    """
    crossing_ids = sorted({cid for witness in witnesses for cid in witness.crossing_ids})
    details: dict[str, object] = {
        "crossing_ids": crossing_ids,
        "witnesses": [witness.as_dict() for witness in witnesses],
        "self_conflicts": [
            witness.crossing_ids[0] for witness in witnesses if witness.kind == "self_crossing"
        ],
        "constraint_conflicts": [[a, b, cid] for a, b, cid in rejected],
    }
    if relaxed is not None:
        details["relaxed_crossing_ids"] = sorted(relaxed)
    return details


def solve_weave(
    crossings: list[CrossingEvent],
    path_ids: list[str],
    *,
    mode: WeaveMode = "alternating",
    manual: dict[str, Literal["a", "b"]] | None = None,
    conflict_strategy: ConflictStrategy = "error",
    topology_tracer: TopologyTracer | None = None,
) -> WeaveTopology:
    """Solve over/under identities independently of rendering.

    ``manual`` maps crossing IDs to the side (a or b) that should be over.
    In ``free`` mode unspecified crossings use a deterministic alternating-by-ID
    fallback; this makes a result available while never claiming path-wise strict
    alternation. For fully specified control, use ``mode='manual'``.

    ``conflict_strategy`` only applies to ``alternating`` mode, and only decides what
    happens when strict alternation has no solution (SPEC FR-045):

    ``error``
        Report the minimal conflict witnesses and return no assignment at all. This
        is the default: the result never claims strict alternation that does not hold.
    ``manual``
        Keep the user's over sides as hard constraints, relax the automatic
        constraints that contradict them, and mark every relaxed crossing.
    ``relax``
        Keep the automatic alternation solution wherever it exists, relax the
        remaining constraints, and mark every relaxed crossing.
    """
    if mode not in {"alternating", "free", "manual"}:
        raise ValueError(f"unsupported weave mode: {mode}")
    if conflict_strategy not in {"error", "manual", "relax"}:
        raise ValueError(f"unsupported conflict strategy: {conflict_strategy}")
    manual = manual or {}
    invalid_manual = {cid: side for cid, side in manual.items() if side not in {"a", "b"}}
    if invalid_manual:
        raise ValueError(f"manual over assignments must be 'a' or 'b': {invalid_manual}")
    transverse = [c for c in crossings if c.kind == "transverse"]
    passes_by_path = build_passes(transverse, path_ids)
    positions: dict[tuple[str, str], int] = {}
    for records in passes_by_path.values():
        for record in records:
            positions[(record.crossing_id, record.side)] = record.position

    assignments: dict[str, WeaveAssignment] = {}
    diagnostics: list[Diagnostic] = []
    if mode == "manual":
        missing = [c.crossing_id for c in transverse if c.crossing_id not in manual]
        for crossing in transverse:
            over_side = manual.get(crossing.crossing_id)
            if over_side not in {"a", "b"}:
                continue
            assignments[crossing.crossing_id] = WeaveAssignment(
                crossing_id=crossing.crossing_id,
                over_side=over_side,
                under_side="b" if over_side == "a" else "a",
                source="manual",
                explanation="由用户显式指定。",
            )
        if missing:
            diagnostics.append(Diagnostic(
                code="TOPOLOGY-MANUAL-ASSIGNMENT-MISSING",
                severity=Severity.ERROR,
                message="手动模式缺少部分交叉的上方指定。",
                details={"crossing_ids": missing},
                hints=("为每个横穿交叉提供 over_side='a' 或 'b'。",),
            ))
        return WeaveTopology(crossings, passes_by_path, assignments, mode, diagnostics)

    if mode == "free":
        for index, crossing in enumerate(transverse):
            side = manual.get(crossing.crossing_id, "a" if index % 2 == 0 else "b")
            assignments[crossing.crossing_id] = WeaveAssignment(
                crossing_id=crossing.crossing_id,
                over_side=side,
                under_side="b" if side == "a" else "a",
                source="manual" if crossing.crossing_id in manual else "free",
                explanation="手动指定。" if crossing.crossing_id in manual else "自由模式的确定性默认值；不保证路径级交替。",
            )
        return WeaveTopology(crossings, passes_by_path, assignments, mode, diagnostics)

    # Binary constraint: flag[path] XOR parity(pass) determines whether a pass is
    # over, and the two pass values at a crossing must differ.
    edges, self_conflicts = _parity_constraints(transverse, positions)
    edges_by_id = {edge.crossing_id: edge for edge in edges}
    adjacency = _adjacency(edges, path_ids)
    pins: dict[str, int] = {}
    dropped_manual: list[str] = []
    if conflict_strategy == "manual":
        pins, dropped_manual = _manual_pins(transverse, positions, manual)
    flags, rejected = _propagate(path_ids, adjacency, _seed_order(path_ids, pins), tracer=topology_tracer)
    witnesses = _witnesses(adjacency, edges_by_id, rejected, self_conflicts, positions)

    if witnesses and conflict_strategy == "error":
        diagnostics.append(Diagnostic(
            code="TOPOLOGY-ALTERNATION-UNSAT",
            severity=Severity.ERROR,
            message="严格路径交替约束存在冲突；本次不会伪造一个声称满足严格交替的解。",
            details=_conflict_details(witnesses, rejected),
            hints=(
                "改用 mode='free'，或提供完整的手动上下关系。",
                "也可用 conflict_strategy='manual' 或 'relax' 得到明确标记的近似解。",
            ),
        ))
        return WeaveTopology(crossings, passes_by_path, {}, mode, diagnostics)

    # Only the rejected constraints have to give way: breaking one edge of a witness
    # cycle is enough, and every other edge of that cycle keeps its alternation value.
    relaxed_ids = {crossing_id for _, _, crossing_id in rejected}
    relaxed_ids.update(crossing.crossing_id for crossing in self_conflicts)
    if witnesses:
        diagnostics.append(Diagnostic(
            code="TOPOLOGY-ALTERNATION-RELAXED",
            severity=Severity.WARNING,
            message=(
                "严格路径交替约束无解，已按所选冲突策略放宽部分交叉；"
                "结果不是严格交替编织。"
            ),
            details=_conflict_details(witnesses, rejected, relaxed=relaxed_ids),
            hints=("移动几何或调整手动上下关系，可以恢复严格交替。",),
        ))
    if dropped_manual:
        diagnostics.append(Diagnostic(
            code="TOPOLOGY-MANUAL-CONFLICT",
            severity=Severity.WARNING,
            message="手动上下关系彼此不相容；保留了交叉 ID 较小的一项。",
            details={"crossing_ids": dropped_manual, "pinned_paths": sorted(pins)},
            hints=("同一路径上的两次手动指定必须落在奇偶性相同的经过位置。",),
            crossing_id=dropped_manual[0],
        ))

    dropped_manual_ids = set(dropped_manual)
    for crossing in transverse:
        crossing_id = crossing.crossing_id
        # A manual side that lost a manual-vs-manual conflict does not get to decide
        # anything here: the earliest crossing ID already pinned the path flag.
        manual_side = None if crossing_id in dropped_manual_ids else manual.get(crossing_id)
        if crossing_id in relaxed_ids:
            side = manual_side if manual_side in {"a", "b"} else RELAXED_OVER_SIDE
            explanation = "严格交替无解，该交叉被放宽为确定性默认值。"
            if manual_side in {"a", "b"}:
                explanation = "严格交替无解，该交叉被放宽并采用用户指定的一侧。"
            assignments[crossing_id] = WeaveAssignment(
                crossing_id=crossing_id,
                over_side=side,  # type: ignore[arg-type]
                under_side="b" if side == "a" else "a",
                source="relaxed",
                explanation=explanation,
            )
            continue
        if conflict_strategy == "manual" and manual_side in {"a", "b"}:
            assignments[crossing_id] = WeaveAssignment(
                crossing_id=crossing_id,
                over_side=manual_side,  # type: ignore[arg-type]
                under_side="b" if manual_side == "a" else "a",
                source="manual",
                explanation="手动指定作为硬约束参与了交替求解。",
            )
            continue
        position_a = positions[(crossing_id, "a")]
        is_a_over = bool(flags[crossing.path_a] ^ (position_a % 2))
        automatic_side = "a" if is_a_over else "b"
        side = automatic_side
        source: Literal["alternating", "manual"] = "alternating"
        explanation = "沿路径经过次序交替，并满足交叉的一上一下约束。"
        if manual_side in {"a", "b"}:
            # The explicit assignment is authoritative. Only report an override when it
            # actually disagreed with the automatic solution.
            side = manual_side
            source = "manual"
            explanation = "用户上下关系与自动交替一致。"
            if side != automatic_side:
                explanation = "用户上下关系覆盖了自动交替结果；路径级严格交替可能不再成立。"
                diagnostics.append(Diagnostic(
                    code="TOPOLOGY-MANUAL-OVERRIDE",
                    severity=Severity.INFO,
                    message="用户上下关系覆盖了自动交替结果；路径级严格交替可能不再成立。",
                    crossing_id=crossing_id,
                    path_ids=(crossing.path_a, crossing.path_b),
                ))
        assignments[crossing_id] = WeaveAssignment(
            crossing_id=crossing_id,
            over_side=side,  # type: ignore[arg-type]
            under_side="b" if side == "a" else "a",
            source=source,
            explanation=explanation,
        )
    return WeaveTopology(crossings, passes_by_path, assignments, mode, diagnostics)
