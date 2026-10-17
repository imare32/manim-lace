"""Grouping, style policies and the "style never touches geometry" contract (M6)."""

import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.style import (
    GROUPING_KINDS,
    PieceOrderingPolicy,
    StylePolicy,
    apply_style,
    build_groups,
    get_palette,
)


def _two_strand(**kwargs):
    paths = [
        np.array([[-2.0, 0.0], [2.0, 0.0]]),
        np.array([[0.0, -2.0], [0.0, 2.0]]),
    ]
    return LaceEngine(paths, offset=0.2, **kwargs).solve()


def _busy_path_result():
    """One vertical strand crossing two horizontals: degrees 2, 1, 1."""
    paths = [
        np.array([[0.0, -2.0], [0.0, 2.0]]),
        np.array([[-2.0, -1.0], [2.0, -1.0]]),
        np.array([[-2.0, 1.0], [2.0, 1.0]]),
    ]
    return LaceEngine(paths, offset=0.2).solve()


def _dense_result(offset: float = 0.05):
    """A horizontal strand crossed eight times inside a small x window."""
    zigzag = np.array([
        [0.35, -0.4], [0.35, 0.4], [0.5, -0.4], [0.5, 0.4], [0.65, -0.4],
        [0.65, 0.4], [0.8, -0.4], [0.8, 0.4], [0.95, -0.4],
    ])
    paths = [np.array([[-2.0, 0.0], [2.0, 0.0]]), zigzag]
    return LaceEngine(paths, offset=offset).solve()


def _snapshot(result):
    """Everything a style policy must not be able to change."""
    return (
        [(c.crossing_id, c.kind, c.point, c.s_a, c.s_b) for c in result.crossings],
        {
            crossing_id: (a.over_side, a.under_side, a.source)
            for crossing_id, a in result.topology.assignments.items()
        },
        [
            (p.piece_id, p.path_id, p.arc_start, p.arc_end, p.draw_index, p.points.tolist())
            for p in result.pieces
        ],
    )


def test_grouping_kinds_are_the_documented_four():
    assert GROUPING_KINDS == ("path", "piece", "layer", "degree")


def test_groups_by_path_cover_every_piece_and_keep_empty_paths():
    result = _busy_path_result()
    groups = build_groups(result, "path")
    assert [group.group_id for group in groups] == [path.path_id for path in result.paths]
    assert [group.index for group in groups] == [0, 1, 2]
    assert sum(group.size for group in groups) == len(result.pieces)
    assert all(group.path_ids == (group.group_id,) for group in groups)
    assert build_groups(result, "path") == groups


def test_groups_by_piece_gives_one_group_per_visible_piece():
    result = _two_strand()
    groups = build_groups(result, "piece")
    assert len(groups) == len(result.pieces)
    assert {group.piece_ids[0] for group in groups} == {p.piece_id for p in result.pieces}
    assert all(group.size == 1 for group in groups)
    # Finest grouping follows the geometry's own draw order.
    expected = [
        p.piece_id for p in sorted(result.pieces, key=lambda item: (item.draw_index, item.piece_id))
    ]
    assert [group.group_id for group in groups] == expected


def test_groups_by_layer_cuts_the_draw_order_into_buckets():
    result = _dense_result()
    groups = build_groups(result, "layer", buckets=3)
    assert len(groups) == 3
    assert [group.group_id for group in groups] == ["layer00", "layer01", "layer02"]
    assert sum(group.size for group in groups) == len(result.pieces)
    first_layer = {
        p.piece_id for p in sorted(result.pieces, key=lambda item: item.draw_index)[: len(result.pieces) // 3]
    }
    assert set(groups[0].piece_ids) == first_layer


def test_groups_by_degree_puts_the_busiest_strand_first():
    result = _busy_path_result()
    groups = build_groups(result, "degree")
    assert groups[0].group_id == "P0000"  # the vertical strand crosses twice
    assert [group.index for group in groups] == [0, 1, 2]
    assert sum(group.size for group in groups) == len(result.pieces)


def test_grouping_rejects_unknown_kinds_and_bad_bucket_counts():
    result = _two_strand()
    with pytest.raises(ValueError, match="grouping kind"):
        build_groups(result, "colour")
    with pytest.raises(ValueError, match="buckets"):
        build_groups(result, "layer", buckets=0)
    with pytest.raises(ValueError, match="buckets"):
        build_groups(result, "layer", buckets=True)


def test_apply_style_paints_each_path_with_its_own_palette_colour():
    result = _two_strand()
    policy = StylePolicy(palette="haru", group_by="path")
    plan = apply_style(result, policy)
    palette = get_palette("haru")
    assert len(plan.groups) == 2
    assert set(plan.colors()) == set(palette.colors[:2])
    for path in result.paths:
        colours = {
            assignment.color
            for assignment in plan.assignments
            if assignment.path_id == path.path_id
        }
        assert len(colours) == 1
    assert plan.assignment_for(result.pieces[0].piece_id) is not None
    assert plan.assignment_for_path(result.paths[0].path_id) is not None
    assert plan.assignment_for_path("missing") is None
    assert plan.color_for("nope") is None
    assert plan.ordered()[0].object_id in {p.piece_id for p in result.pieces}


def test_apply_style_without_a_palette_uses_the_single_colour_and_paper():
    result = _two_strand()
    plan = apply_style(result, StylePolicy(color="#123456"))
    assert plan.colors() == ("#123456",)
    assert plan.background == "#ffffff"
    assert StylePolicy(color="#123456").has_paper
    plain = apply_style(result, StylePolicy(palette="wabi"))
    assert plain.background == get_palette("wabi").background
    no_paper = StylePolicy(palette="wabi", background="none")
    assert not no_paper.has_paper
    assert no_paper.background_color == "#ffffff"


def test_apply_style_colour_modes_are_deterministic():
    result = _dense_result()
    shuffled = apply_style(result, StylePolicy(palette="matsuri", group_by="piece", color_mode="shuffle", seed=3))
    again = apply_style(result, StylePolicy(palette="matsuri", group_by="piece", color_mode="shuffle", seed=3))
    assert shuffled.colors() == again.colors()
    even = apply_style(result, StylePolicy(palette="matsuri", group_by="piece", color_mode="even"))
    assert len(even.colors()) > 1
    assert set(even.colors()) <= set(get_palette("matsuri").colors)


def test_apply_style_never_changes_crossings_assignments_or_geometry():
    result = _dense_result()
    before = _snapshot(result)
    piece_objects = tuple(result.pieces)
    for policy in (
        StylePolicy(palette="haru"),
        StylePolicy(palette="natsu", group_by="piece"),
        StylePolicy(palette="aki", group_by="layer", buckets=2),
        StylePolicy(color="#00ff00", group_by="degree", opacity=0.4),
    ):
        apply_style(result, policy)
    assert _snapshot(result) == before
    assert tuple(result.pieces) == piece_objects


def test_piece_ordering_override_is_reported_not_silent():
    result = _two_strand()
    quiet = apply_style(result, StylePolicy(palette="haru", piece_order="geometry"))
    assert quiet.diagnostics == ()
    loud = apply_style(result, StylePolicy(palette="haru", piece_order="path"))
    assert [diagnostic.code for diagnostic in loud.diagnostics] == ["STYLE-DRAW-ORDER-OVERRIDE"]
    diagnostic = loud.diagnostics[0]
    assert diagnostic.details["mode"] == "path"
    assert diagnostic.details["piece_count"] == len(result.pieces)
    assert loud.order == tuple(
        piece.piece_id
        for piece in sorted(result.pieces, key=lambda item: (item.path_id, item.arc_start))
    )


def test_piece_ordering_policy_validates_its_mode():
    with pytest.raises(ValueError, match="draw order mode"):
        PieceOrderingPolicy("top-first")
    assert PieceOrderingPolicy("geometry").order([]) == []


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"group_by": "colour"}, "group_by"),
        ({"color_mode": "rainbow"}, "color_mode"),
        ({"opacity": 0.0}, "opacity"),
        ({"opacity": 1.5}, "opacity"),
        ({"fill_opacity": -0.1}, "fill_opacity"),
        ({"buckets": 0}, "buckets"),
        ({"piece_order": "shuffle"}, "piece_order"),
        ({"color": "not-a-colour"}, "color"),
        ({"outline_color": "#12"}, "color"),
        ({"palette": "no-such-palette"}, "unknown palette"),
    ],
)
def test_style_policy_validates_every_field(kwargs, match):
    with pytest.raises(ValueError, match=match):
        StylePolicy(**kwargs)


def test_apply_style_rejects_non_policies():
    with pytest.raises(ValueError, match="StylePolicy"):
        apply_style(_two_strand(), {"palette": "haru"})
