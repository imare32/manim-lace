"""Path and piece grouping for style policies (SPEC FR-061/FR-064).

Grouping is a pure function of the solved :class:`~manim_lace.model.LaceResult`:
it never touches crossings, assignments or geometry, so changing how the strands
are grouped can only change colours, never the weave (SPEC FR-062).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["GROUPING_KINDS", "StyleGroup", "build_groups"]

#: How :func:`build_groups` can partition the visible geometry.
#:
#: ``path``: one group per source path (the classic "one colour per strand").
#: ``piece``: one group per visible piece/region (finest control).
#: ``layer``: equal-size buckets of the geometry's own draw order.
#: ``degree``: one group per source path, busiest strand first.
GROUPING_KINDS = ("path", "piece", "layer", "degree")


@dataclass(frozen=True, slots=True)
class StyleGroup:
    """One colour group: a set of paths and the pieces that belong to them."""

    group_id: str
    index: int
    path_ids: tuple[str, ...]
    piece_ids: tuple[str, ...]
    label: str = ""

    @property
    def size(self) -> int:
        """How many visible pieces (or regions) the group holds."""
        return len(self.piece_ids)


def _object_id(item: Any) -> str:
    """The stable ID of a stroke piece or a ribbon region."""
    identifier = getattr(item, "piece_id", None) or getattr(item, "region_id", None)
    if identifier is None:
        raise ValueError(f"unsupported piece object without piece_id/region_id: {type(item).__name__}")
    return str(identifier)


def _path_of(item: Any) -> str:
    path_id = getattr(item, "path_id", None)
    if path_id is None:
        raise ValueError(f"unsupported piece object without path_id: {type(item).__name__}")
    return str(path_id)


def _crossing_degree(result: Any) -> dict[str, int]:
    """How many times each path visits a crossing (its weave degree)."""
    passes = getattr(result.topology, "passes_by_path", {}) or {}
    if passes:
        return {str(path_id): len(items) for path_id, items in passes.items()}
    degrees: dict[str, int] = {}
    for crossing in result.crossings:
        for path_id in (crossing.path_a, crossing.path_b):
            degrees[str(path_id)] = degrees.get(str(path_id), 0) + 1
    return degrees


def _layer_buckets(pieces: list[Any], buckets: int) -> list[list[Any]]:
    """Split the pieces' own draw order into ``buckets`` contiguous chunks."""
    ordered = sorted(pieces, key=lambda item: (getattr(item, "draw_index", 0), _object_id(item)))
    count = max(1, min(int(buckets), len(ordered)))
    chunks: list[list[Any]] = []
    for index in range(count):
        start = (index * len(ordered)) // count
        stop = ((index + 1) * len(ordered)) // count
        chunks.append(ordered[start:stop])
    return [chunk for chunk in chunks if chunk]


def build_groups(result: Any, kind: str = "path", *, buckets: int | None = None) -> list[StyleGroup]:
    """Partition the solved geometry into colour groups.

    Parameters
    ----------
    result:
        A :class:`~manim_lace.model.LaceResult` whose ``pieces`` are stroke
        pieces (``piece_id``) or ribbon regions (``region_id``).
    kind:
        One of :data:`GROUPING_KINDS`.
    buckets:
        ``layer`` only: how many layers to cut the draw order into. Defaults to
        the number of source paths, i.e. one bucket per strand.

    Every returned group is deterministic: groups follow the order of
    ``result.paths`` (or the draw order for ``layer``), and a path without any
    visible piece still gets its own group so the colour mapping does not shift
    when a cut happens to remove a piece.

    Raises ``ValueError`` for an unknown ``kind`` or a non-positive ``buckets``.
    """
    if kind not in GROUPING_KINDS:
        raise ValueError(f"grouping kind must be one of {list(GROUPING_KINDS)}; got {kind!r}")
    if buckets is not None and (not isinstance(buckets, int) or isinstance(buckets, bool) or buckets <= 0):
        raise ValueError(f"buckets must be a positive integer or None; got {buckets!r}")
    pieces = list(getattr(result, "pieces", []) or [])
    by_path: dict[str, list[str]] = {}
    for piece in pieces:
        by_path.setdefault(_path_of(piece), []).append(_object_id(piece))
    path_order = [str(path.path_id) for path in getattr(result, "paths", []) or []]
    for path_id in by_path:
        if path_id not in path_order:
            path_order.append(path_id)

    if kind == "piece":
        ordered = sorted(pieces, key=lambda item: (getattr(item, "draw_index", 0), _object_id(item)))
        return [
            StyleGroup(
                group_id=_object_id(piece),
                index=index,
                path_ids=(_path_of(piece),),
                piece_ids=(_object_id(piece),),
                label=f"piece {_object_id(piece)}",
            )
            for index, piece in enumerate(ordered)
        ]

    if kind == "layer":
        chunks = _layer_buckets(pieces, buckets if buckets is not None else max(1, len(path_order)))
        return [
            StyleGroup(
                group_id=f"layer{index:02d}",
                index=index,
                path_ids=tuple(dict.fromkeys(_path_of(item) for item in chunk)),
                piece_ids=tuple(_object_id(item) for item in chunk),
                label=f"layer {index + 1}/{len(chunks)}",
            )
            for index, chunk in enumerate(chunks)
        ]

    if kind == "degree":
        degrees = _crossing_degree(result)
        order = sorted(path_order, key=lambda path_id: (-degrees.get(path_id, 0), path_order.index(path_id)))
    else:  # "path"
        order = path_order
    return [
        StyleGroup(
            group_id=path_id,
            index=index,
            path_ids=(path_id,),
            piece_ids=tuple(by_path.get(path_id, ())),
            label=f"path {path_id}",
        )
        for index, path_id in enumerate(order)
    ]
