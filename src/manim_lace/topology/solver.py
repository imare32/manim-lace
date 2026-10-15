"""Path-pass ordering and alternating/free over-under assignment."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Literal

from ..diagnostics import Diagnostic, Severity
from ..model import CrossingEvent, Pass, WeaveAssignment, WeaveTopology

WeaveMode = Literal["alternating", "free", "manual"]


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


def solve_weave(
    crossings: list[CrossingEvent],
    path_ids: list[str],
    *,
    mode: WeaveMode = "alternating",
    manual: dict[str, Literal["a", "b"]] | None = None,
) -> WeaveTopology:
    """Solve over/under identities independently of rendering.

    ``manual`` maps crossing IDs to the side (a or b) that should be over.
    In ``free`` mode unspecified crossings use a deterministic alternating-by-ID
    fallback; this makes a result available while never claiming path-wise strict
    alternation. For fully specified control, use ``mode='manual'``.
    """
    if mode not in {"alternating", "free", "manual"}:
        raise ValueError(f"unsupported weave mode: {mode}")
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

    # Binary constraint: flag[path] XOR parity(pass) determines whether a pass
    # is over. At a crossing the two pass values must differ.
    constraints: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    self_conflicts: list[CrossingEvent] = []
    for crossing in transverse:
        pa = positions[(crossing.crossing_id, "a")]
        pb = positions[(crossing.crossing_id, "b")]
        if crossing.path_a == crossing.path_b:
            if (pa % 2) == (pb % 2):
                self_conflicts.append(crossing)
            continue
        parity = 1 ^ (pa % 2) ^ (pb % 2)
        constraints[crossing.path_a].append((crossing.path_b, parity, crossing.crossing_id))
        constraints[crossing.path_b].append((crossing.path_a, parity, crossing.crossing_id))

    flags: dict[str, int] = {}
    conflicts: list[tuple[str, str, str]] = []
    for start in path_ids:
        if start in flags:
            continue
        flags[start] = 1
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for other, parity, crossing_id in constraints[current]:
                expected = flags[current] ^ parity
                if other not in flags:
                    flags[other] = expected
                    queue.append(other)
                elif flags[other] != expected:
                    conflicts.append((current, other, crossing_id))
    if self_conflicts or conflicts:
        affected = sorted({c.crossing_id for c in self_conflicts} | {c for _, _, c in conflicts})
        diagnostics.append(Diagnostic(
            code="TOPOLOGY-ALTERNATION-UNSAT",
            severity=Severity.ERROR,
            message="严格路径交替约束存在冲突；本次不会伪造一个声称满足严格交替的解。",
            details={
                "crossing_ids": affected,
                "self_conflicts": [c.crossing_id for c in self_conflicts],
                "constraint_conflicts": conflicts,
            },
            hints=("改用 mode='free'，或提供完整的手动上下关系。",),
        ))
        return WeaveTopology(crossings, passes_by_path, {}, mode, diagnostics)

    for crossing in transverse:
        pa = positions[(crossing.crossing_id, "a")]
        is_a_over = bool(flags[crossing.path_a] ^ (pa % 2))
        side = "a" if is_a_over else "b"
        if crossing.crossing_id in manual:
            # The explicit assignment is authoritative. This may break strict
            # alternation, so make that override visible in the result.
            side = manual[crossing.crossing_id]
            diagnostics.append(Diagnostic(
                code="TOPOLOGY-MANUAL-OVERRIDE",
                severity=Severity.INFO,
                message="用户上下关系覆盖了自动交替结果；路径级严格交替可能不再成立。",
                crossing_id=crossing.crossing_id,
                path_ids=(crossing.path_a, crossing.path_b),
            ))
            source = "manual"
        else:
            source = "alternating"
        assignments[crossing.crossing_id] = WeaveAssignment(
            crossing_id=crossing.crossing_id,
            over_side=side,
            under_side="b" if side == "a" else "a",
            source=source,  # type: ignore[arg-type]
            explanation="沿路径经过次序交替，并满足交叉的一上一下约束。",
        )
    return WeaveTopology(crossings, passes_by_path, assignments, mode, diagnostics)
