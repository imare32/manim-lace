"""Deterministic painter order for the render backends.

Both backends express "this strand is over that one" partly through geometry (a gap or
a Boolean subtraction) and partly through the order their output is painted in. The
order is computed here once, from the same over/under assignments, so a backend can
never invent its own.
"""

from __future__ import annotations

__all__ = ["paint_order"]


def paint_order(
    nodes: list[str], edges: list[tuple[str, str]]
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Layer ``nodes`` so that every under node comes before the nodes over it.

    ``edges`` are ``(under, over)`` pairs. A cycle has no consistent painter order;
    the edges that forced the deterministic break are returned so the caller can report
    them instead of hiding the fact.
    """
    incoming: dict[str, list[str]] = {node: [] for node in nodes}
    seen: set[tuple[str, str]] = set()
    for under, over in edges:
        if under == over or (under, over) in seen:
            continue
        seen.add((under, over))
        incoming.setdefault(over, []).append(under)
    layers = {node: 0 for node in nodes}
    remaining = [node for node in nodes]
    resolved: set[str] = set()
    congested: list[tuple[str, str]] = []
    while remaining:
        progressed = False
        for node in list(remaining):
            if any(blocker not in resolved for blocker in incoming[node]):
                continue
            layers[node] = max((layers[blocker] + 1 for blocker in incoming[node]), default=0)
            resolved.add(node)
            remaining.remove(node)
            progressed = True
        if progressed:
            continue
        # Every remaining node waits for something inside a cycle: break it in the given
        # order and remember which constraints had to give.
        node = remaining.pop(0)
        for blocker in incoming[node]:
            if blocker not in resolved:
                congested.append((blocker, node))
        layers[node] = max(
            (layers[blocker] + 1 for blocker in incoming[node] if blocker in resolved), default=0
        )
        resolved.add(node)
    congested.sort()
    return layers, congested
