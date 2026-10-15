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

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import scene_gallery  # noqa: E402
import scene_rosette  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from manim_lace import Lace  # noqa: E402
from manim_lace.render.regions import build_bands  # noqa: E402

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