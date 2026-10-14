"""``Lace`` 渲染层的测试。"""

from __future__ import annotations

import numpy as np
import pytest
from manim import (
    BLUE,
    GREEN,
    LEFT,
    RIGHT,
    TAU,
    YELLOW,
    Circle,
    Dot,
    Line,
    ManimColor,
    ParametricFunction,
    Square,
    VGroup,
    VMobject,
)

from manim_lace import HOLE_GROUP_METHODS, RIBBON_GROUP_METHODS, Lace
from manim_lace.lace import mobject_paths, to_3d
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


def star_rosette(*args, **kwargs):
    """构造玫瑰线目标; 玫瑰线是**可选模块**, 缺失时相关用例自动跳过。"""
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    from manim_lace import StarRosette

    return StarRosette(*args, **kwargs)


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
        assert Lace(star_rosette(10, 2), offset=0.1).num_ribbons > 0

    def test_circle_target_is_not_blank(self):
        # 缺陷 2 回归: Circle 的子路径在闭合点处首尾边共线, 旧实现整体空输出
        lace = Lace(Circle(radius=2.0), offset=0.2)
        assert lace.num_holes == 1
        assert lace.num_ribbons == 1

    def test_level_zero_rosette_leaves_the_hole_visible(self):
        # 缺陷 1 回归: 无自交点的闭合图形应是环形丝带, 中间露出孔洞
        lace = Lace(star_rosette(7, 0, "PO"), offset=0.05)
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

    def test_unknown_ribbon_group_method(self, square):
        with pytest.raises(ValueError, match="ribbon_group_method"):
            Lace(square, offset=0.2, ribbon_group_method="by_magic")

    def test_empty_ribbon_swatch_is_rejected(self, square):
        with pytest.raises(ValueError, match="ribbon_swatch"):
            Lace(square, offset=0.2, ribbon_swatch=[])

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

    @staticmethod
    def fill_hexes(lace: Lace) -> set[str]:
        return {ManimColor(ribbon.get_fill_color()).to_hex() for ribbon in lace.ribbons}

    def test_without_a_swatch_every_ribbon_keeps_the_kwargs_colour(self, square):
        # 旧行为: 不传 ribbon_swatch 时不做分组着色
        lace = Lace(square, offset=0.2, fill_color="#123456")
        assert lace.ribbon_swatch is None
        assert self.fill_hexes(lace) == {"#123456"}

    def test_ribbon_swatch_cycles_adjacent_pieces(self):
        # 单块图形(如正方形环)只有一条丝带, 要看轮换得多片段图形
        lace = Lace(line_group(2), offset=0.1, ribbon_swatch=["#FF0000", "#00FF00"])
        hexes = [ManimColor(ribbon.get_fill_color()).to_hex() for ribbon in lace.ribbons]
        assert lace.num_ribbons > 2
        assert hexes == ["#FF0000" if index % 2 == 0 else "#00FF00" for index in range(lace.num_ribbons)]

    def test_ribbon_color_overrides_the_swatch(self, square):
        lace = Lace(square, offset=0.2, ribbon_color=YELLOW, ribbon_swatch=["#FF0000", "#00FF00"])
        assert self.fill_hexes(lace) == {ManimColor(YELLOW).to_hex()}

    def test_explicit_fill_color_wins_over_the_swatch(self, square):
        lace = Lace(square, offset=0.2, fill_color="#0000FF", ribbon_swatch=["#FF0000", "#00FF00"])
        assert self.fill_hexes(lace) == {"#0000FF"}

    def test_swatch_is_optional_for_grouped_methods(self, square):
        lace = Lace(square, offset=0.2, ribbon_swatch=["#FF0000", "#00FF00"], ribbon_group_method="by_distance")
        assert self.fill_hexes(lace) <= {"#FF0000", "#00FF00"}


class TestRibbonGroups:
    @pytest.mark.parametrize("method", RIBBON_GROUP_METHODS)
    def test_every_method_covers_all_ribbons(self, method):
        lace = Lace(line_group(3), offset=0.1, ribbon_swatch=["#FF0000", "#00FF00"], ribbon_group_method=method)
        groups = lace.ribbon_groups
        assert groups
        assert sum(len(indices) for indices in groups.values()) == lace.num_ribbons
        assert list(groups) == sorted(groups)
        assert sorted(index for indices in groups.values() for index in indices) == list(range(lace.num_ribbons))

    @pytest.mark.parametrize("method", RIBBON_GROUP_METHODS)
    def test_groups_are_cached(self, method):
        lace = Lace(line_group(3), offset=0.1, ribbon_group_method=method)
        assert lace.ribbon_groups is lace.ribbon_groups

    def test_by_ribbon_index_creates_one_group_per_piece(self, square):
        lace = Lace(square, offset=0.2, ribbon_group_method="by_ribbon_index")
        assert len(lace.ribbon_groups) == lace.num_ribbons
        assert all(len(indices) == 1 for indices in lace.ribbon_groups.values())

    def test_by_vertex_count_keys_match_piece_vertices(self, square):
        lace = Lace(square, offset=0.2, ribbon_group_method="by_vertex_count")
        assert lace.ribbon_groups
        for count, indices in lace.ribbon_groups.items():
            assert all(len(lace.interlacing.ribbons[index]) - 1 == count for index in indices)

    def test_by_distance_is_ordered_by_radius(self):
        lace = Lace(line_group(4), offset=0.1, ribbon_group_method="by_distance")

        def center(index: int) -> np.ndarray:
            coords = np.asarray(lace.interlacing.ribbons[index], dtype=float)[:-1, :2]
            return np.mean(coords, axis=0)

        groups = list(lace.ribbon_groups.values())
        assert len(groups) > 1
        centers = [center(index) for indices in groups for index in indices]
        global_center = np.mean(centers, axis=0)
        distances = [
            float(np.mean([np.linalg.norm(center(index) - global_center) for index in indices])) for indices in groups
        ]
        assert distances == sorted(distances)

    def test_by_path_separates_the_two_crossing_lines(self):
        lines = [Line([-1.0, -1.0, 0.0], [1.0, 1.0, 0.0]), Line([-1.0, 1.0, 0.0], [1.0, -1.0, 0.0])]
        lace = Lace(VGroup(*lines), offset=0.2, ribbon_swatch=["#FF0000", "#00FF00"], ribbon_group_method="by_path")
        groups = lace.ribbon_groups
        assert len(groups) == 2
        # 每条线的丝带各自同色, 两条线颜色不同
        hexes = [
            {ManimColor(lace.ribbons[index].get_fill_color()).to_hex() for index in indices}
            for indices in groups.values()
        ]
        assert all(len(group_hexes) == 1 for group_hexes in hexes)
        assert len({next(iter(group_hexes)) for group_hexes in hexes}) == 2

    def test_no_ribbons_yields_empty_mapping(self):
        assert Lace(VGroup(), offset=0.2, ribbon_swatch=["#FF0000"]).ribbon_groups == {}


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


class TestDenseCurves:
    """回归: 曲线输入必须**忠实**且不能被静默毁掉。

    背景: ``clear_paths`` 的共线判据以前比较"叉积的绝对量"(随边长平方缩小), 于是点很密的
    曲线**每一段**都被判成共线 —— ``Lace(ParametricFunction(...))``(Manim 默认采样)会把曲线
    塌成首尾两点(渲染成一条直线), 采样更密时整条路径被删空(输出空白)。示例脚本一直没暴露
    这个问题, 只是因为 ``Circle`` 只有 32 个点、Lissajous 例子写死了很粗的 ``t_range``。

    现在曲线还会先按贝塞尔重采样(见 :func:`manim_lace.lace.mobject_paths`), 不再是"把控制点
    当折线": 采样点落在真正的曲线上(``Circle`` 的半径回到 2.0), 直线输入则保持不变。
    """

    @staticmethod
    def lissajous(step: float | None = None) -> ParametricFunction:
        func = lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0])  # noqa: E731
        if step is None:
            return ParametricFunction(func)
        return ParametricFunction(func, t_range=(0, TAU, step), use_smoothing=False)

    def test_default_sampled_curve_keeps_its_shape(self):
        lace = Lace(self.lissajous(), offset=0.05, validate="ignore")
        path = lace.interlacing.paths[0]
        # 修复前这里只剩 2 个点(整条曲线变成一条直线)
        assert len(path) > 100
        assert len(lace.interlacing.d_intersections) > 0

    def test_curve_polyline_lies_on_the_curve(self):
        # 采样点必须落在真正的曲线上(修复前是"控制点多边形", 偏差随采样密度失控)
        lace = Lace(self.lissajous(), offset=0.05, validate="ignore")
        path = lace.interlacing.paths[0][:, :2]
        params = np.linspace(0.0, 1.0, 20001)  # manim 的 ParametricFunction 默认 t_range=[0, 1]
        curve = np.column_stack([np.sin(2 * params), np.sin(3 * params)])
        distance = np.min(np.linalg.norm(path[:, None, :] - curve[None, :, :], axis=2), axis=1)
        assert distance.max() < 1e-3

    def test_circle_is_sampled_on_the_true_circle(self):
        # 控制点多边形时代 Circle 是半径 2.069 的 17 边形; 现在每个采样点都在半径 2 附近
        # (1e-5 的偏差来自 Manim 自己的八段贝塞尔近似, 不是本库的误差)
        lace = Lace(Circle(radius=2.0), offset=0.2, validate="ignore")
        path = lace.interlacing.paths[0]
        np.testing.assert_allclose(np.linalg.norm(path[:, :2], axis=1), 2.0, atol=1e-4)
        assert len(path) > 32  # 不再是 17 个控制点
        assert (lace.num_holes, lace.num_ribbons) == (1, 1)

    def test_straight_inputs_are_left_unchanged(self):
        # 直线段采样后全部共线, 会被共线清理还原 —— 既有输入的几何不变(A/B 基线依赖这一点)
        square = Lace(Square(side_length=3.0), offset=0.2, validate="ignore")
        assert [len(path) for path in square.interlacing.paths] == [5]
        star = Lace(self.lissajous(0.1), offset=0.05, validate="ignore")
        assert star.num_ribbons + star.num_holes > 0

    def test_very_dense_curve_still_produces_output(self):
        # 采样更密时以前会整条路径被删空(Lace 空输出); 现在必须仍然有可见产物
        lace = Lace(self.lissajous(0.01), offset=0.05, validate="ignore")
        assert lace.num_ribbons + lace.num_holes > 0
        # 点数 ≈ 锚点数(未平滑的 ParametricFunction 每段都是直线, 采样出的点会共线还原)
        assert len(lace.interlacing.paths[0]) > 600

    def test_dense_curve_polygons_are_finite_and_closed(self):
        lace = Lace(self.lissajous(0.005), offset=0.05, validate="ignore")
        polygons = [*lace.interlacing.holes, *lace.interlacing.ribbons]
        assert polygons
        for coords in polygons:
            assert np.all(np.isfinite(coords))
            np.testing.assert_allclose(coords[0], coords[-1])

    def test_mobject_paths_rejects_too_few_samples(self):
        with pytest.raises(ValueError, match="samples"):
            mobject_paths(Circle(radius=1.0), samples=1)

    def test_mobject_paths_returns_one_polyline_per_subpath(self):
        circle = mobject_paths(Circle(radius=1.0))
        segment = mobject_paths(Line(LEFT, RIGHT))
        assert len(circle) == 1 and len(segment) == 1
        assert circle[0].shape[1] == 3
        np.testing.assert_allclose(segment[0][[0, -1], :2], [[-1.0, 0.0], [1.0, 0.0]])
