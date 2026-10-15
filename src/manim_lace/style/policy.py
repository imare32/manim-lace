"""Style policies: colours, grouping and draw order for the solved geometry.

A :class:`StylePolicy` is decorative only. :func:`apply_style` reads a solved
:class:`~manim_lace.model.LaceResult` and returns a :class:`StylePlan` — it never
re-solves, never mutates the result and never changes crossings, assignments or
geometry (SPEC FR-062, acceptance test AT-018). Geometry-changing choices (band
width, cut allowance) live in the engine/backends, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..diagnostics import Diagnostic, Severity
from .grouping import GROUPING_KINDS, StyleGroup, build_groups
from .palette import Palette, get_palette, parse_color

__all__ = [
    "DRAW_ORDER_MODES",
    "PieceOrderingPolicy",
    "StyleAssignment",
    "StylePlan",
    "StylePolicy",
    "apply_style",
]

#: How the visible pieces may be ordered for painting.
#:
#: ``geometry``: the order the geometry layer computed (under strands first).
#: ``path``: group by source path, then by arc position — a *readability* order,
#: which is only safe where the cuts are real geometry (ribbon backend, or a
#: stroke weave whose cuts already hide the ends).
DRAW_ORDER_MODES = ("geometry", "path")


@dataclass(frozen=True, slots=True)
class StyleAssignment:
    """The resolved style of one visible piece or region."""

    object_id: str
    path_id: str
    group_id: str
    palette_index: int
    color: str
    fill_color: str | None = None
    opacity: float = 1.0
    fill_opacity: float = 1.0
    outline_color: str | None = None
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", parse_color(self.color))
        if self.fill_color is not None:
            object.__setattr__(self, "fill_color", parse_color(self.fill_color))
        if self.outline_color is not None:
            object.__setattr__(self, "outline_color", parse_color(self.outline_color))

    @property
    def paint_color(self) -> str:
        """The colour a fill should use (falls back to the main colour)."""
        return self.fill_color or self.color


@dataclass(frozen=True, slots=True)
class PieceOrderingPolicy:
    """How the visible pieces are ordered for painting (SPEC §9 draw order)."""

    mode: str = "geometry"

    def __post_init__(self) -> None:
        if self.mode not in DRAW_ORDER_MODES:
            raise ValueError(f"draw order mode must be one of {list(DRAW_ORDER_MODES)}; got {self.mode!r}")

    def order(self, pieces: list[Any]) -> list[Any]:
        """``pieces`` in paint order: geometry order first, then path/arc order."""
        if self.mode == "geometry":
            return sorted(
                pieces,
                key=lambda item: (
                    getattr(item, "draw_index", 0),
                    str(getattr(item, "piece_id", None) or getattr(item, "region_id", "")),
                ),
            )
        return sorted(
            pieces,
            key=lambda item: (
                str(getattr(item, "path_id", "")),
                float(getattr(item, "arc_start", 0.0)),
                str(getattr(item, "piece_id", None) or getattr(item, "region_id", "")),
            ),
        )

    def diagnostics(self, pieces: list[Any], order: list[Any]) -> tuple[Diagnostic, ...]:
        """Report the visual consequence of an order that is not the geometry's own."""
        if self.mode == "geometry" or not pieces:
            return ()
        names = [_object_id(item) for item in pieces]
        automatic = sorted(
            range(len(pieces)),
            key=lambda index: (
                getattr(pieces[index], "draw_index", 0),
                names[index],
            ),
        )
        chosen = [_object_id(item) for item in order]
        moved = sum(1 for rank, index in enumerate(automatic) if names[index] != chosen[rank])
        return (
            Diagnostic(
                code="STYLE-DRAW-ORDER-OVERRIDE",
                severity=Severity.INFO,
                message=(
                    f"绘制顺序按 '{self.mode}' 重排，{moved}/{len(pieces)} 个片段不再位于几何层给出的顺序。"
                ),
                details={"mode": self.mode, "moved_pieces": moved, "piece_count": len(pieces)},
                hints=(
                    "几何顺序保证被压路径先画；重排只在切口已是真实几何时才完全安全。",
                    "改回 mode='geometry' 可恢复几何层顺序。",
                ),
            ),
        )


def _object_id(item: Any) -> str:
    identifier = getattr(item, "piece_id", None) or getattr(item, "region_id", None)
    if identifier is None:
        raise ValueError(f"unsupported piece object without piece_id/region_id: {type(item).__name__}")
    return str(identifier)


@dataclass(frozen=True, slots=True)
class StylePolicy:
    """Colours, grouping and draw order for one rendering of a solved result.

    Parameters
    ----------
    palette:
        A palette name (``"haru"``, ``"祭"``), a :class:`~manim_lace.style.palette.Palette`,
        or ``None`` to paint every group with ``color``. A name is resolved at
        construction, so a typo fails immediately.
    color:
        The single colour used when ``palette`` is ``None``.
    group_by:
        ``path`` (default), ``piece``, ``layer`` or ``degree`` — see
        :func:`~manim_lace.style.grouping.build_groups`.
    color_mode:
        ``cycle`` (palette order), ``even`` (spread over the palette) or
        ``shuffle`` (deterministic shuffle, reproducible through ``seed``).
    seed:
        Seed for ``color_mode='shuffle'`` (SPEC FR-063).
    opacity, fill_opacity:
        Stroke opacity and fill opacity; ``fill_opacity=None`` follows ``opacity``.
    outline_color:
        When set, every piece gets this thin outline colour instead of no outline.
    background:
        Paper colour; ``None`` means "the palette's own background", and
        ``"none"`` means "no paper" (the adapter then draws nothing behind).
    buckets:
        ``group_by='layer'`` only: how many draw-order buckets to cut.
    piece_order:
        ``geometry`` (default) or ``path`` — see :class:`PieceOrderingPolicy`.
    """

    palette: Palette | str | None = None
    color: str = "#888888"
    group_by: str = "path"
    color_mode: str = "cycle"
    seed: int | None = None
    opacity: float = 1.0
    fill_opacity: float | None = None
    outline_color: str | None = None
    background: str | None = None
    buckets: int | None = None
    piece_order: str = "geometry"

    def __post_init__(self) -> None:
        if self.palette is not None and not isinstance(self.palette, Palette):
            object.__setattr__(self, "palette", get_palette(self.palette))
        object.__setattr__(self, "color", parse_color(self.color))
        if self.group_by not in GROUPING_KINDS:
            raise ValueError(f"group_by must be one of {list(GROUPING_KINDS)}; got {self.group_by!r}")
        if self.color_mode not in ("cycle", "even", "shuffle"):
            raise ValueError(f"color_mode must be 'cycle', 'even' or 'shuffle'; got {self.color_mode!r}")
        if not 0.0 < float(self.opacity) <= 1.0:
            raise ValueError(f"opacity must be within (0, 1]; got {self.opacity!r}")
        if self.fill_opacity is not None and not 0.0 <= float(self.fill_opacity) <= 1.0:
            raise ValueError(f"fill_opacity must be within [0, 1]; got {self.fill_opacity!r}")
        if self.outline_color is not None:
            object.__setattr__(self, "outline_color", parse_color(self.outline_color))
        if self.background is not None:
            text = str(self.background).strip().lower()
            if text in ("", "none"):
                object.__setattr__(self, "background", "none")
            else:
                object.__setattr__(self, "background", parse_color(str(self.background)))
        if self.buckets is not None:
            if not isinstance(self.buckets, int) or isinstance(self.buckets, bool) or self.buckets <= 0:
                raise ValueError(f"buckets must be a positive integer or None; got {self.buckets!r}")
        if self.piece_order not in DRAW_ORDER_MODES:
            raise ValueError(
                f"piece_order must be one of {list(DRAW_ORDER_MODES)}; got {self.piece_order!r}"
            )

    @property
    def colors(self) -> tuple[str, ...]:
        """The colours this policy can draw from, in order."""
        if self.palette is not None:
            return self.palette.colors
        return (self.color,)

    @property
    def has_paper(self) -> bool:
        """Whether the policy asks for a paper colour behind the pattern."""
        return self.background != "none"

    @property
    def background_color(self) -> str:
        """The paper colour: explicit, else the palette's, else white."""
        if self.background == "none":
            return "#ffffff"
        if self.background:
            return self.background
        if self.palette is not None:
            return self.palette.background
        return "#ffffff"


@dataclass(frozen=True, slots=True)
class StylePlan:
    """The result of :func:`apply_style`: colours per piece, groups, and draw order."""

    policy: StylePolicy
    groups: tuple[StyleGroup, ...]
    assignments: tuple[StyleAssignment, ...]
    order: tuple[str, ...]
    background: str
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)

    def assignment_for(self, object_id: str) -> StyleAssignment | None:
        for assignment in self.assignments:
            if assignment.object_id == str(object_id):
                return assignment
        return None

    def color_for(self, object_id: str) -> str | None:
        assignment = self.assignment_for(object_id)
        return assignment.color if assignment else None

    def colors(self) -> tuple[str, ...]:
        """The distinct colours actually used, in assignment order."""
        return tuple(dict.fromkeys(assignment.color for assignment in self.assignments))

    def by_group(self) -> dict[str, tuple[StyleAssignment, ...]]:
        grouped: dict[str, list[StyleAssignment]] = {}
        for assignment in self.assignments:
            grouped.setdefault(assignment.group_id, []).append(assignment)
        return {group_id: tuple(items) for group_id, items in grouped.items()}

    def ordered(self) -> tuple[StyleAssignment, ...]:
        """Assignments in the planned paint order."""
        positions = {object_id: index for index, object_id in enumerate(self.order)}
        return tuple(
            sorted(self.assignments, key=lambda item: (positions.get(item.object_id, 0), item.object_id))
        )


def apply_style(result: Any, policy: StylePolicy) -> StylePlan:
    """Resolve ``policy`` against a solved ``result`` without touching its geometry.

    Every visible piece/region of the result gets exactly one
    :class:`StyleAssignment`; pieces are sorted by the policy's draw-order mode,
    and any deviation from the geometry layer's own painter order is reported
    through a ``STYLE-DRAW-ORDER-OVERRIDE`` diagnostic instead of being silent
    (SPEC FR-082).
    """
    if not isinstance(policy, StylePolicy):
        raise ValueError(f"policy must be a StylePolicy; got {type(policy).__name__}")
    pieces = list(getattr(result, "pieces", []) or [])
    groups = build_groups(result, policy.group_by, buckets=policy.buckets)
    palette_index_by_group = {group.group_id: group.index for group in groups}
    if policy.palette is not None:
        group_colors = policy.palette.strand_colors(
            len(groups), seed=policy.seed, mode=policy.color_mode
        )
    else:
        group_colors = [policy.color] * len(groups)
    colors_by_group = {group.group_id: group_colors[index] for index, group in enumerate(groups)}
    group_by_piece: dict[str, str] = {}
    for group in groups:
        for piece_id in group.piece_ids:
            group_by_piece[piece_id] = group.group_id

    assignments: list[StyleAssignment] = []
    for piece in pieces:
        object_id = _object_id(piece)
        path_id = str(getattr(piece, "path_id", ""))
        group_id = group_by_piece.get(object_id, path_id or object_id)
        color = colors_by_group.get(group_id, policy.color)
        assignments.append(
            StyleAssignment(
                object_id=object_id,
                path_id=path_id,
                group_id=group_id,
                palette_index=palette_index_by_group.get(group_id, 0),
                color=color,
                fill_color=color,
                opacity=float(policy.opacity),
                fill_opacity=float(
                    policy.opacity if policy.fill_opacity is None else policy.fill_opacity
                ),
                outline_color=policy.outline_color,
                z_index=int(getattr(piece, "draw_index", 0)),
            )
        )
    ordering = PieceOrderingPolicy(policy.piece_order)
    ordered = ordering.order(pieces)
    diagnostics = ordering.diagnostics(pieces, ordered)
    return StylePlan(
        policy=policy,
        groups=tuple(groups),
        assignments=tuple(assignments),
        order=tuple(_object_id(item) for item in ordered),
        background=policy.background_color,
        diagnostics=diagnostics,
    )
