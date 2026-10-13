"""``Lace`` 渲染层的测试。"""

from __future__ import annotations

import numpy as np
import pytest
from manim import (
    BLUE,
    GREEN,
    LEFT,
    RIGHT,
    YELLOW,
    Circle,
    Dot,
    Line,
    ManimColor,
    Square,
    VGroup,
    VMobject,
)

from manim_lace import HOLE_GROUP_METHODS, Lace, StarRosette
from manim_lace.lace import to_3d
from tests.helpers import polygon_area
from tests.weave_checks import points_in_polygon


def line_group(n: int = 3, spacing: float = 1.0, overhang: float = 0.5) -> VGroup:
    """用 Manim ``Line`` 搭一个 ``n×n`` 编织网格。"""
    end = (n - 1) * spacing
    lines = []
    for i in range(n):
        lines.append(Line([-overhang, i * spacing, 0.0], [end + overhang, i * spacing, 0.0]))
        lines.append(Line([i * spacing, -overhang, 0.0], [i * spacing, end + overhang, 0.0]))
    return VGroup(*lines)


@pytest.fixture
def square() -> Square:
    return Square(side_length=3.0)


class TestTo3D:
    def test_pads_missing_z(self):
        padded = to_3d(np.array([[1.0, 2.0], [3.0, 4.0]]))
        np.testing.assert_allclose(padded, [[1.0, 2.0, 0.0], [3.0, 4.0, 0.0]])

    def test_keeps_existing_z(self):
        coords = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        np.testing.assert_allclose(to_3d(coords), coords)

    @pytest.mark.parametrize("coords", [np.zeros(3), np.zeros((2, 4)), np.zeros((2, 2, 2))])
    def test_rejects_unexpected_shapes(self, coords):
        with pytest.raises(ValueError, match="coords"):
            to_3d(coords)


class TestConstruction:
    def test_is_vgroup_with_holes_and_ribbons(self, square):
        lace = Lace(square, offset=0.2)
        assert isinstance(lace, VGroup)
        assert lace.submobjects[0] is lace.holes
        assert lace.submobjects[1] is lace.ribbons
        assert lace.num_holes == len(lace.holes) > 0
        assert lace.num_ribbons == len(lace.ribbons) > 0

    def test_repr_reports_counts(self, square):
        text = repr(Lace(square, offset=0.2))
        assert text.startswith("Lace(")
        assert "holes=" in text

    def test_offset_is_exposed(self, square):
        assert Lace(square, offset=0.35).offset == pytest.approx(0.35)

    def test_empty_target_mobject(self):
        lace = Lace(VGroup(), offset=0.2)
        assert lace.num_holes == 0
        assert lace.num_ribbons == 0
        assert lace.hole_groups == {}

    def test_point_less_target_mobject(self):
        assert Lace(VMobject(), offset=0.2).num_ribbons == 0

    def test_single_dot_target(self):
        assert Lace(Dot(), offset=0.1).num_ribbons >= 0

    def test_line_target_has_no_holes(self):
        lace = Lace(Line(LEFT, RIGHT), offset=0.2)
        assert lace.num_holes == 0
        assert lace.hole_groups == {}

    def test_star_rosette_target(self):
        assert Lace(StarRosette(10, 2), offset=0.1).num_ribbons > 0

    def test_circle_target_is_not_blank(self):
        # 缺陷 2 回归: Circle 的子路径在闭合点处首尾边共线, 旧实现整体空输出
        lace = Lace(Circle(radius=2.0), offset=0.2)
        assert lace.num_holes == 1
        assert lace.num_ribbons == 1

    def test_level_zero_rosette_leaves_the_hole_visible(self):
        # 缺陷 1 回归: 无自交点的闭合图形应是环形丝带, 中间露出孔洞
        lace = Lace(StarRosette(7, 0, "PO"), offset=0.05)
        assert lace.num_ribbons == 1
        assert lace.num_holes == 1
        hole_center = lace.interlacing.holes[0][:-1].mean(axis=0)
        assert not np.any(points_in_polygon(lace.interlacing.ribbons[0], hole_center[None, :]))

    def test_grid_target_hole_count(self):
        assert Lace(line_group(3), offset=0.1).num_holes == 16

    @staticmethod
    def overlapping_lines() -> VGroup:
        """两条同向共线、部分重叠的线: 退化输入。"""
        return VGroup(Line([0.0, 0.0, 0.0], [2.0, 0.0, 0.0]), Line([0.5, 0.0, 0.0], [2.5, 0.0, 0.0]))

    def test_degenerate_target_warns_by_default(self):
        with pytest.warns(UserWarning, match="退化输入"):
            lace = Lace(self.overlapping_lines(), offset=0.2)
        assert len(lace.interlacing.path_issues) == 1

    def test_degenerate_target_can_be_rejected(self):
        with pytest.raises(ValueError, match="退化输入"):
            Lace(self.overlapping_lines(), offset=0.2, validate="raise")

    def test_degenerate_target_can_be_ignored(self):
        lace = Lace(self.overlapping_lines(), offset=0.2, validate="ignore")
        assert lace.interlacing.path_issues == []

    def test_normal_target_has_no_issues(self, square):
        assert Lace(square, offset=0.2).interlacing.path_issues == []


class TestParameterValidation:
    @pytest.mark.parametrize("offset", [0, -1.0, float("nan"), float("inf")])
    def test_offset_must_be_positive(self, square, offset):
        with pytest.raises(ValueError, match="offset"):
            Lace(square, offset=offset)

    @pytest.mark.parametrize("opacity", [-0.1, 1.1, float("nan")])
    def test_hole_opacity_must_be_a_ratio(self, square, opacity):
        with pytest.raises(ValueError, match="hole_opacity"):
            Lace(square, offset=0.2, hole_opacity=opacity)

    def test_unknown_group_method(self, square):
        with pytest.raises(ValueError, match="hole_group_method"):
            Lace(square, offset=0.2, hole_group_method="by_magic")

    def test_empty_swatch_is_rejected(self, square):
        with pytest.raises(ValueError, match="hole_swatch"):
            Lace(square, offset=0.2, hole_swatch=[])

    def test_unknown_kwarg_is_rejected(self, square):
        with pytest.raises(TypeError):
            Lace(square, offset=0.2, definitely_not_a_kwarg=1)


class TestHoleStyling:
    def test_hole_color_override(self, square):
        lace = Lace(square, offset=0.2, hole_color=BLUE, hole_opacity=0.4, hole_swatch=["#FF0000"])
        assert lace.num_holes > 0
        for hole in lace.holes:
            assert ManimColor(hole.get_fill_color()).to_hex() == ManimColor(BLUE).to_hex()
            assert hole.get_fill_opacity() == pytest.approx(0.4)

    def test_hole_stroke_is_disabled(self, square):
        lace = Lace(square, offset=0.2, hole_swatch=["#FF0000"])
        assert all(hole.get_stroke_width() == pytest.approx(0.0) for hole in lace.holes)

    def test_single_color_swatch(self, square):
        lace = Lace(square, offset=0.2, hole_swatch=["#FF0000"])
        assert {ManimColor(hole.get_fill_color()).to_hex() for hole in lace.holes} == {"#FF0000"}

    def test_swatch_is_resolved_to_a_tuple(self, square):
        assert Lace(square, offset=0.2, hole_swatch=["#FF0000", "#00FF00"]).hole_swatch == ("#FF0000", "#00FF00")

    def test_default_swatch_comes_from_the_builtin_palette(self, square):
        from manim_lace.swatches import swatches

        assert list(Lace(square, offset=0.2).hole_swatch) in swatches

    def test_swatch_palette_spreads_across_groups(self):
        lace = Lace(line_group(4), offset=0.1, hole_swatch=["#FF0000", "#00FF00", "#0000FF"])
        used = {ManimColor(hole.get_fill_color()).to_hex() for hole in lace.holes}
        assert len(used) > 1

    def test_hole_opacity_is_forwarded(self, square):
        lace = Lace(square, offset=0.2, hole_opacity=0.25)
        assert all(hole.get_fill_opacity() == pytest.approx(0.25) for hole in lace.holes)


class TestRibbonStyling:
    def test_kwargs_are_forwarded(self, square):
        lace = Lace(square, offset=0.2, stroke_color="#000000", stroke_width=3, fill_color=YELLOW, fill_opacity=0.25)
        assert lace.num_ribbons > 0
        for ribbon in lace.ribbons:
            assert ribbon.get_stroke_width() == pytest.approx(3.0)
            assert ManimColor(ribbon.get_stroke_color()).to_hex() == "#000000"
            assert ManimColor(ribbon.get_fill_color()).to_hex() == ManimColor(YELLOW).to_hex()
            assert ribbon.get_fill_opacity() == pytest.approx(0.25)

    def test_stroke_color_drives_the_default_color(self, square):
        lace = Lace(square, offset=0.2, stroke_color=GREEN)
        assert lace.num_ribbons > 0
        for ribbon in lace.ribbons:
            assert ManimColor(ribbon.get_stroke_color()).to_hex() == ManimColor(GREEN).to_hex()

    def test_color_kwarg_does_not_conflict(self, square):
        lace = Lace(square, offset=0.2, color=BLUE)
        assert lace.num_ribbons > 0
        for ribbon in lace.ribbons:
            assert ManimColor(ribbon.get_stroke_color()).to_hex() == ManimColor(BLUE).to_hex()


class TestHoleGroups:
    @pytest.mark.parametrize("method", HOLE_GROUP_METHODS)
    def test_every_method_covers_all_holes(self, method):
        lace = Lace(line_group(3), offset=0.1, hole_group_method=method)
        groups = lace.hole_groups
        assert groups
        assert sum(len(holes) for holes in groups.values()) == lace.num_holes
        assert list(groups) == sorted(groups)

    @pytest.mark.parametrize("method", HOLE_GROUP_METHODS)
    def test_groups_are_cached(self, method):
        lace = Lace(line_group(3), offset=0.1, hole_group_method=method)
        assert lace.hole_groups is lace.hole_groups

    def test_by_area_keys_match_vertex_count_and_area(self):
        lace = Lace(line_group(3), offset=0.1, hole_group_method="by_area")
        assert lace.hole_groups
        for (num_verts, area), holes in lace.hole_groups.items():
            assert num_verts >= 3
            for hole in holes:
                assert len(hole) - 1 == num_verts
                assert round(polygon_area(hole), 4) == pytest.approx(area)

    def test_by_vertex_count(self):
        lace = Lace(line_group(3), offset=0.1, hole_group_method="by_vertex_count")
        assert lace.hole_groups
        for count, holes in lace.hole_groups.items():
            assert all(len(hole) - 1 == count for hole in holes)

    def test_by_hole_index_creates_one_group_per_hole(self):
        lace = Lace(line_group(3), offset=0.1, hole_group_method="by_hole_index")
        assert len(lace.hole_groups) == lace.num_holes
        assert all(len(holes) == 1 for holes in lace.hole_groups.values())

    def test_by_distance_is_ordered_by_radius(self):
        lace = Lace(line_group(4), offset=0.1, hole_group_method="by_distance")
        groups = lace.hole_groups
        assert len(groups) > 1
        centers = np.array([np.mean(hole[:-1], axis=0) for holes in groups.values() for hole in holes])
        global_center = np.mean(centers, axis=0)
        group_distances = [
            float(np.mean([np.linalg.norm(np.mean(hole[:-1], axis=0) - global_center) for hole in holes]))
            for holes in groups.values()
        ]
        assert group_distances == sorted(group_distances)

    def test_no_holes_yields_empty_mapping(self):
        assert Lace(Line(LEFT, RIGHT), offset=0.2).hole_groups == {}


class TestDebugHelpers:
    def test_draw_path_follows_the_given_corners(self, square):
        lace = Lace(square, offset=0.2)
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
        drawn = lace.draw_path(coords)
        assert isinstance(drawn, VMobject)
        anchors = np.array(drawn.get_anchors())
        assert anchors.shape[1] == 3
        for corner in coords:
            assert any(np.allclose(anchor[:2], corner) for anchor in anchors)

    def test_draw_path_accepts_3d_input(self, square):
        lace = Lace(square, offset=0.2)
        coords = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 1.0]])
        anchors = np.array(lace.draw_path(coords).get_anchors())
        np.testing.assert_allclose(anchors[0], coords[0])
        np.testing.assert_allclose(anchors[-1], coords[-1])
