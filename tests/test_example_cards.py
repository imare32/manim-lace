"""The gallery's two comparison cards must actually weave (regression pins).

Both cards invite the reader to compare panels *by eye*: ``RosetteWeave`` shows one
weave through three drawing channels, ``RibbonGallery`` shows one pair of strands
through three backends. Both had drifted into looking wrong in ways no geometry test
notices, because each still rendered something plausible:

* the ribbon panels stroked their bands in the facade's default white on white paper,
  so no strand edge was visible;
* the rosette was woven with ``weave_mode="free"``, which put a strand on the same side
  twice in a row 60 times, where plain alternation has a perfect solution;
* the two strands of the channel card shared one colour, and ribbon mode removes the
  under strand's footprint — so both ribbon panels rendered as one flat silhouette.

The assertions below describe the fixed state; the old state is not assumed, it is
measured. The channel-card pin was run against the pre-fix card and fails there
(``AssertionError: ('boolean', {'#5CD0B3'})`` — one colour for both strands), and the
same card, built with the rosette's old ``weave_mode="free"``, scores 60 alternation
defects where default alternation scores 0. These are solver/style assertions only:
they never render, so they stay fast and headless.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# The gallery scenes under test import Manim at module scope, and ``manim`` is an
# optional extra: CI installs ``.[dev]`` only, so without this guard collection itself
# fails instead of the module skipping (same convention as the other optional modules).
manim = pytest.importorskip("manim")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import scene_gallery  # noqa: E402
import scene_rosette  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from manim_lace import Lace  # noqa: E402
from manim_lace.render.regions import (  # noqa: E402
    _arm_strip,
    _local_lens,
    _self_crossing_reach,
    build_bands,
)

BLACK = "#000000"


def _alternation_defects(lace: Lace) -> int:
    """Visits where a strand lands on the same side as on its previous visit.

    A self-crossing is visited twice by the same path, so both passes are counted
    separately: that is exactly where a "single path cannot alternate with itself"
    claim would show up if it were true.
    """
    assignments = lace.result.topology.assignments
    defects = 0
    for path in lace.result.paths:
        visits: list[tuple[float, bool]] = []
        for crossing in lace.crossings:
            record = assignments.get(crossing.crossing_id)
            if record is None:
                continue
            over_is_a = record.over_side == "a"
            if crossing.path_a == path.path_id:
                visits.append((float(crossing.s_a), over_is_a))
                if crossing.path_b == path.path_id:
                    visits.append((float(crossing.s_b), not over_is_a))
            elif crossing.path_b == path.path_id:
                visits.append((float(crossing.s_b), not over_is_a))
        visits.sort()
        defects += sum(
            1 for index in range(1, len(visits)) if visits[index][1] == visits[index - 1][1]
        )
    return defects


def _stroked_colours(lace: Lace) -> set[str]:
    """Colours actually used to stroke the drawn band edges."""
    mobjects = [*lace.ribbons, *lace.outlines]
    return {
        mobject.get_stroke_color().to_hex()
        for mobject in mobjects
        if mobject.get_stroke_width() > 0
    }


def test_the_rosette_card_weaves_with_default_alternation() -> None:
    trio = scene_rosette.build_rosette_weave_trio()
    assert [channel for channel, _ in trio] == ["stroke", "boolean", "arrangement"]
    for channel, lace in trio:
        # 3 loops, 11 + 11 + 41 points: 70 crossings of which 20 are self-crossings.
        assert len(lace.crossings) == 70, channel
        assert sum(1 for c in lace.crossings if c.path_a == c.path_b) == 20, channel
        sources = {record.source for record in lace.result.topology.assignments.values()}
        assert sources == {"alternating"}, (channel, sources)
        assert _alternation_defects(lace) == 0, channel


def test_the_rosette_card_strokes_its_ribbon_bands_against_the_paper() -> None:
    # The stroke channel's band width *is* a stroke colour, so only the ribbon panels
    # are checked: they must not inherit the white default that hid every band edge.
    # (Some pieces keep their own fill colour on the edge — that is the seam-cover
    # path, and it is invisible rather than wrong; what mattered was white on white.)
    for channel, lace in scene_rosette.build_rosette_weave_trio():
        if channel == "stroke":
            continue
        colours = _stroked_colours(lace)
        assert BLACK in colours, (channel, colours)
        assert "#FFFFFF" not in colours, (channel, colours)


def test_the_channel_card_keeps_its_two_strands_apart() -> None:
    trio = dict(scene_gallery.build_backend_trio())
    assert set(trio) == {"stroke", "boolean", "arrangement"}
    for channel in ("boolean", "arrangement"):
        lace = trio[channel]
        fills = {
            mobject.get_fill_color().to_hex()
            for mobject in lace.ribbons
            if mobject.get_fill_opacity() > 0
        }
        # Two strands, two colours: one colour collapses the panel into a silhouette,
        # because ribbon mode shows the under strand's removal as a colour change.
        assert len(fills) == 2, (channel, fills)
        assert "#FFFFFF" not in fills, (channel, fills)
        # And the band edges must not be drawn in the paper colour either.
        strokes = _stroked_colours(lace)
        assert BLACK in strokes, (channel, strokes)
        assert "#FFFFFF" not in strokes, (channel, strokes)
        assert _alternation_defects(lace) == 0, channel


def test_the_channel_card_keeps_the_ring_unbroken_where_it_is_over() -> None:
    # The ring's polyline starts at (+1, 0) — exactly the crossing where the ring passes
    # *over* the bar. The stroke backend must not split the ring at its own seam there:
    # the two halves butt at the seam and their butt caps, each perpendicular to its own
    # local chord, leave a hairline wedge of paper across the bar, which reads as a cut
    # in a path that is whole (the thin white slit on the ring's right side).
    lace = dict(scene_gallery.build_backend_trio())["stroke"]
    ring = [piece for piece in lace.result.pieces if piece.path_id == "P0000"]
    assert len(ring) == 1
    piece = ring[0]
    length = lace.result.paths[0].length
    # Cut once, where it goes under, and the remaining arc wraps the seam as one piece.
    assert piece.arc_start > 0.0 and piece.arc_end > length
    seam = lace.result.paths[0].points[0]
    interior = np.flatnonzero(np.all(np.isclose(piece.points, seam, atol=1e-9), axis=1))
    assert interior.size == 1
    assert 0 < interior[0] < len(piece.points) - 1


def test_the_ribbon_panels_leave_no_occlusion_hole() -> None:
    """The Boolean backend must cut a strand through, never into a *hole*.

    Where the over strand's local footprint sits inside the under band without reaching its
    edges — a miter corner is the usual reason — the subtraction used to leave an occlusion
    hole. A hole has to be painted in the paper colour (Manim fills an exterior ring solid),
    and the painter order cannot always put the strand that covers the footprint on top:
    two strands crossing more than twice alternate their over/under into a cycle no total
    order satisfies. Where it broke, the hole bit a background-coloured notch out of the
    pattern — on the card, a 148 px bite at (+0.81, +1.59) in the Boolean panel.

    Measured on the simple 10-crossing rosette: 1 occlusion hole before the fix, 0 after,
    and the union of the region exteriors covers the band union exactly.
    """
    loops = scene_rosette.rosette_loops(10, 1, "PA")
    source = scene_rosette._loops_as_mobjects(loops, color="#000000", width=2.0)
    offset = 0.08
    for backend in ("boolean", "arrangement"):
        lace = Lace(source, offset=offset, render="ribbon", ribbon_backend=backend)
        holes = [hole for region in lace.result.pieces for hole in region.holes]
        assert [hole.role for hole in holes] == [], (backend, [h.role for h in holes])
        bands, _ = build_bands(
            lace.engine.paths, offset=offset, cap_style="butt", join="miter",
            miter_limit=5.0, diagnostics=[],
        )
        painted = unary_union([Polygon(region.exterior.points) for region in lace.result.pieces])
        band_union = unary_union(list(bands.values()))
        # Nothing inside the ribbon is left unpainted: no paper shows through the strands.
        assert band_union.difference(painted).area < 1e-12, backend


def test_the_boolean_backend_strokes_every_self_crossing_notch_whole():
    # The report behind docs/ROSETTE_RIBBON_OUTLINE_TICKS.md §9: on the n = 7 CA card the
    # Boolean panel drew the notch of the tip crossing only as far as its section window
    # reached, so the line stopped 0.088 short of the strand's edge — a stroke poking into
    # the ribbon. Every notch — the lens edge that lies on the band of the pass on top —
    # must be stroked from one side of the under strand to the other.
    loops = scene_rosette.rosette_loops(7, 2, "CA")
    source = scene_rosette._loops_as_mobjects(loops)
    offset = 0.10
    lace = Lace(
        source, offset=offset, render="ribbon", ribbon_backend="boolean",
        palette="ayame", stroke_color="#000000", stroke_width_px=2.0,
        fill_opacity=1.0, hole_color="#ffffff",
    )
    strokes = []
    for piece in lace.result.pieces:
        ring = np.asarray(piece.exterior.points, dtype=float)
        flush = set(piece.flush_edges)
        for index in range(len(ring) - 1):
            if index in flush:
                continue
            if float(np.hypot(*(ring[index + 1] - ring[index]))) > 1e-9:
                strokes.append((ring[index], ring[index + 1]))
    assert strokes
    ordered = sorted(
        lace.result.pieces, key=lambda piece: (piece.draw_index, piece.region_id)
    )
    fills = {
        piece.region_id: Polygon(
            np.asarray(piece.exterior.points, dtype=float),
            [np.asarray(hole.points, dtype=float) for hole in piece.holes] or None,
        )
        for piece in ordered
    }
    fill_tree = STRtree([fills[piece.region_id] for piece in ordered])

    def owner(point):
        best = None
        for index in fill_tree.query(point):
            if fills[ordered[index].region_id].intersects(point):
                best = index if best is None else max(best, index)
        return None if best is None else ordered[best].region_id

    path = lace.result.paths[0]
    checked = 0
    for crossing in lace.crossings:
        if crossing.path_a != crossing.path_b or crossing.kind != "transverse":
            continue
        assignment = lace.result.topology.assignments[crossing.crossing_id]
        assert assignment is not None
        under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
        over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
        arms = [
            _arm_strip(
                path, arc, _self_crossing_reach(offset, crossing.sin_angle),
                offset=offset, join="miter", miter_limit=5.0, line_class=LineString,
            )
            for arc in (under_arc, over_arc)
        ]
        lens = _local_lens(arms[0], arms[1], crossing.point, Point)
        if lens is None:
            continue
        ring = np.asarray(lens.exterior.coords, dtype=float)
        for start, end in zip(ring[:-1], ring[1:], strict=False):
            edge = LineString([start, end])
            # The notch edges are the two that lie on the band of the pass on top: the
            # other two run along the band below and are hidden by the material over
            # them. Every edge *touches* both bands at its corners, so the edge is
            # classified by where its middle runs.
            middle = Point(*(0.5 * (start + end)))
            if float(arms[1].boundary.distance(middle)) > 1e-9:
                continue
            if float(arms[0].boundary.distance(middle)) <= 1e-9:
                continue
            direction = (end - start) / edge.length
            normal = np.array([-direction[1], direction[0]])
            # The renderer's own cut is clipped to the section windows, so its stroke can
            # sit a hair off this record of the notch: what matters is that a stroke runs
            # *along* it, not that the two are the same line to the last bit. And only
            # where the visible material really changes across the line is a stroke owed —
            # where one region is on top of both sides, the line is inside its own fill.
            gaps = []
            for step in range(21):
                point = start + (end - start) * (step / 20.0)
                if any(
                    abs(float(np.dot((s_end - s_start) / np.hypot(*(s_end - s_start)),
                                     direction))) > 0.9
                    and float(LineString([s_start, s_end]).distance(Point(*point))) <= 1e-4
                    for s_start, s_end in strokes
                    if float(np.hypot(*(s_end - s_start))) > 1e-9
                ):
                    continue
                outer = owner(Point(*(point + normal * 1e-5)))
                inner = owner(Point(*(point - normal * 1e-5)))
                if outer is not None and inner is not None and outer != inner:
                    gaps.append(step / 20.0)
            assert not gaps, (crossing.crossing_id, edge.length, gaps)
            checked += 1
    assert checked, "no self-crossing notch was measured"


@pytest.mark.parametrize(
    ("name", "n", "levels", "star_type", "offset"),
    [
        ("n10 PA L1p2 o08", 10, (1, 2), "PA", 0.08),
        ("n7 CA L2 o10", 7, (2,), "CA", 0.10),
    ],
)
def test_the_boolean_backend_leaves_no_stroke_end_inside_the_ribbon(
    name, n, levels, star_type, offset
):
    """No stroke may stop in the middle of a strand.

    The report behind ``docs/ROSETTE_RIBBON_OUTLINE_TICKS.md`` §9 was a stroke that ran
    into the ribbon and stopped: the Boolean backend cut with a lens clipped to the
    section windows it works through, so the piece left over reached past the cut and no
    ring edge ran along the far end of the notch — the stroke had nothing to join and
    ended inside the fill. The measurement lives in ``benchmarks/weave_audit.py`` (the
    ``dangling`` column of ``make audit``) so the test and the report cannot drift apart.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
    from weave_audit import dangling_ends

    loops: list = []
    for level in levels:
        loops.extend(scene_rosette.rosette_loops(n, level, star_type))
    source = scene_rosette._loops_as_mobjects(loops)
    lace = Lace(
        source, offset=offset, render="ribbon", ribbon_backend="boolean",
        palette="ayame", stroke_color="#000000", stroke_width_px=2.0,
        fill_opacity=1.0, hole_color="#ffffff",
    )
    dangling = dangling_ends(lace.result.pieces)
    assert not dangling, (name, dangling)


def test_the_stroke_panel_wears_the_cards_strand_width() -> None:
    """The stroke channel's panel has to be the same input as the ribbon panels.

    The channel draws each cut piece as a *stroke*, so its strands are stroke widths
    rather than geometry: ``Mobject.scale`` — what fits a card into the frame — leaves
    stroke widths alone, and a fitted card's strands came out wider than the ribbon
    bands beside them (measured on ``RosetteWeave``: 22 px against 11 px). ``refit``
    re-strokes them for the scale the fit applied.

    The panel carries no border, deliberately: the cut pieces abut at every crossing, so
    a border there either merges with the neighbouring piece's body or outlines the
    abutting ends and reads as "both strands outlined, same layer".
    """
    panel = scene_gallery.StrokePanel(scene_gallery._two_strand_source(), 0.22)
    assert isinstance(panel, Lace)
    body = float(np.max(np.asarray(panel.ribbons[0].get_stroke_width())))
    assert body > 0.0
    panel.refit(0.4)
    assert float(np.max(np.asarray(panel.ribbons[0].get_stroke_width()))) == (
        pytest.approx(body * 0.4)
    )
    # No extra layers: what the channel emits is what the panel shows.
    assert len(panel.submobjects) == len(panel.ribbons)
    # The channel card's stroke panel is one of these.
    assert isinstance(dict(scene_gallery.build_backend_trio())["stroke"],
                      scene_gallery.StrokePanel)


def test_the_channel_card_renders_the_same_weave_in_every_backend() -> None:
    trio = dict(scene_gallery.build_backend_trio())
    seen = {
        channel: {
            crossing.crossing_id: lace.result.topology.assignments[crossing.crossing_id].over_side
            for crossing in lace.crossings
        }
        for channel, lace in trio.items()
    }
    assert seen["stroke"] == seen["boolean"] == seen["arrangement"]


#: The rosette weave cards beyond the first one, as ``(scene, n, levels, star_type,
#: offset)`` — read from the scenes' own ``SOURCE`` so the cards and this test cannot
#: drift apart. Each of these configurations used to draw a stroke inside its own
#: ribbon, or lose one, before the marking was fixed
#: (docs/ROSETTE_RIBBON_OUTLINE_TICKS.md §7).
WEAVE_CARDS = [
    (scene, *scene.SOURCE)
    for scene in (
        scene_rosette.RosetteWeaveCA7,
        scene_rosette.RosetteWeaveCR11,
        scene_rosette.RosetteWeaveThin,
    )
]


@pytest.mark.parametrize(("scene", "n", "levels", "star_type", "offset"), WEAVE_CARDS)
def test_the_weave_cards_paint_the_whole_ribbon_in_both_backends(
    scene, n, levels, star_type, offset
) -> None:
    """Every rosette weave card paints its ribbon whole, with nothing outside it.

    The invariants that caught the §7 bugs, measured per card configuration:

    * ``band_union - painted`` is empty: no paper shows through the strands. The fold
      bug dropped a 2.8e-3 wedge off a ring (n = 11 CR) and the arrangement's face
      union dropped a whole face (n = 7 CA) — both invisible to a fill test, both
      visible as paper inside the ribbon.
    * ``painted - band_union`` is empty: nothing is painted outside the ribbon, so a
      region's ring cannot claim material the band never had.
    * every hole with real area is covered by another region: an occlusion hole is
      painted in the paper colour, so it is only invisible while the strand that owns
      the footprint there is painted later. (Zero-area slivers are not checked — they
      paint nothing; the arrangement emits a few at miter tips.)

    The union is built from the region exteriors and holes the way the renderer draws
    them, and compared against the band union — the same comparison the accounting
    diagnostic makes. A single ``unary_union`` call can drop a part that only touches
    another along an edge; if it did here, this test would fail rather than pass
    quietly, which is the direction a regression test should err in.
    """
    loops: list = []
    for level in levels:
        loops.extend(scene_rosette.rosette_loops(n, level, star_type))
    source = scene_rosette._loops_as_mobjects(loops, color="#000000", width=2.0)
    for backend in ("boolean", "arrangement"):
        lace = Lace(
            source, offset=offset, render="ribbon", ribbon_backend=backend,
            palette="ayame", stroke_color="#000000", stroke_width_px=2.0,
            fill_opacity=1.0, hole_color="#ffffff",
        )
        regions = lace.result.pieces
        fills = {
            region.region_id: Polygon(
                np.asarray(region.exterior.points, dtype=float),
                [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
            )
            for region in regions
        }
        for region in regions:
            for hole in region.holes:
                ring = Polygon(np.asarray(hole.points, dtype=float))
                if ring.area <= 1e-12:
                    continue
                probe = ring.representative_point()
                assert any(fill.contains(probe) for fill in fills.values()), (
                    scene.__name__, backend, region.region_id, hole.role
                )
        bands, _ = build_bands(
            lace.engine.paths, offset=offset, cap_style="butt", join="miter",
            miter_limit=5.0, diagnostics=[],
        )
        painted = unary_union(list(fills.values()))
        band_union = unary_union(list(bands.values()))
        assert band_union.difference(painted).area < 1e-9, (scene.__name__, backend)
        assert painted.difference(band_union).area < 1e-9, (scene.__name__, backend)