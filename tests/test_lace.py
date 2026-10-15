"""``Lace`` 渲染层的测试。"""

from __future__ import annotations

import numpy as np
import pytest
from manim import (
    BLACK,
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
    Polygon,
    Polygram,
    Square,
    VGroup,
    VMobject,
)

from manim_lace import HOLE_GROUP_METHODS, RIBBON_GROUP_METHODS, Lace
from manim_lace.interlacing import Interlacing, annulus_polygon
from manim_lace.lace import _annulus_loops, _signed_area, mobject_paths, to_3d
from tests.helpers import polygon_area, ring_path, square_ring
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


class TestAnnulusRibbonSubpaths:
    """无自交闭合路径的环形丝带: 渲染成"外环 + 内环"两个子路径, 描边无狭缝线。

    缺陷 1 修复后, 环形丝带由 :func:`~manim_lace.interlacing.annulus_polygon` 缝成
    **一条**轮廓(狭缝 = 两条零宽度重合边): 填充正确, 但描边会把狭缝画成一条横跨带子的
    线。现在渲染层把它拆回两个子路径(外环逆时针 / 内环顺时针), Manim 的 cairo 后端对
    每个子路径分别 ``close_path`` 再描边, 狭缝线消失; 几何点阵不变, 因此指纹与编织
    校验不受影响。
    """

    @staticmethod
    def crossing_lines() -> VGroup:
        return VGroup(Line([-1.0, -1.0, 0.0], [1.0, 1.0, 0.0]), Line([-1.0, 1.0, 0.0], [1.0, -1.0, 0.0]))

    def test_simple_closed_ribbon_has_two_subpaths(self, square):
        lace = Lace(square, offset=0.2)
        assert lace.num_ribbons == 1
        ribbon = lace.ribbons[0]
        assert isinstance(ribbon, Polygram)
        loops = ribbon.get_subpaths()
        assert len(loops) == 2
        for loop in loops:
            assert np.array_equal(loop[0], loop[-1])  # 每条子路径各自闭合
        areas = [_signed_area(loop[:, :2]) for loop in loops]
        assert areas[0] > 0 > areas[1]  # 外环逆时针 / 内环顺时针(非零绕数下内区为 0)

    def test_circle_ribbon_has_two_subpaths(self):
        # Circle 的环带顶点最密(32+), 结构识别不能依赖"边长"之类的启发式
        lace = Lace(Circle(radius=2.0), offset=0.2)
        assert lace.num_ribbons == 1
        assert len(lace.ribbons[0].get_subpaths()) == 2

    def test_annulus_ribbon_keeps_fill_and_stroke_kwargs(self, square):
        lace = Lace(square, offset=0.2, fill_color="#123456", stroke_color=BLACK, stroke_width=3)
        ribbon = lace.ribbons[0]
        assert ManimColor(ribbon.get_fill_color()).to_hex() == "#123456"
        assert ribbon.get_stroke_width() == pytest.approx(3)

    def test_woven_ribbons_stay_single_contour(self):
        lace = Lace(self.crossing_lines(), offset=0.2)
        assert lace.num_ribbons > 1
        for ribbon in lace.ribbons:
            assert len(ribbon.get_subpaths()) == 1
            assert isinstance(ribbon, Polygon)

    def test_open_path_strip_stays_single_contour(self):
        lace = Lace(Line(LEFT, RIGHT), offset=0.2)
        assert lace.num_ribbons == 1
        assert len(lace.ribbons[0].get_subpaths()) == 1

    def test_geometry_array_is_unchanged(self, square):
        # 几何层仍是带狭缝的单轮廓(matrix_digest / weave_checks 依赖这一点),
        # 只有 mobject 拆成两个子路径
        lace = Lace(square, offset=0.2)
        ribbon = lace.interlacing.ribbons[0]
        loops = _annulus_loops(ribbon)
        assert loops is not None
        outer, inner = loops
        assert np.array_equal(outer[0], ribbon[0])  # 外环从数组首点出发
        vertices = np.vstack([outer, inner])
        for point in ribbon:  # 原数组的每个顶点都来自拆开的两条环
            assert np.any((vertices == point).all(axis=1))
        for point in vertices:  # 反之亦然(没有凭空多出/丢掉顶点)
            assert np.any((ribbon == point).all(axis=1))

    def test_hole_under_the_annulus_is_still_visible(self, square):
        # 拆子路径不改变填充区域: 孔洞中心仍不在丝带内(缺陷 1 的回归不能破)
        lace = Lace(square, offset=0.2)
        hole_center = lace.interlacing.holes[0][:-1].mean(axis=0)
        assert not np.any(points_in_polygon(lace.interlacing.ribbons[0], hole_center[None, :]))


class TestCrossingGroups:
    """阶段 1 的只读前置: 按中心线交叉给轨记录分组(不参与任何决策)。"""

    @staticmethod
    def crossing_lines() -> list[np.ndarray]:
        return [
            np.array([[-1.0, 0.0], [1.0, 0.0]]),
            np.array([[0.0, -1.0], [0.0, 1.0]]),
        ]

    def test_crossing_lines_group_cleanly(self):
        inter = Interlacing(self.crossing_lines(), 0.2, validate="ignore")
        groups = inter._crossing_groups(0)
        assert groups is not None
        assert len(groups) == 1  # 一个交叉
        attribution = inter._crossing_attribution(0)
        assert attribution is not None
        assert attribution[4] == 2  # 两侧轨道各 2 个角点 = 2 对

    def test_healthy_config_has_clean_groups_for_every_path(self):
        inter = Interlacing(self.crossing_lines(), 0.2, validate="ignore")
        for i in range(len(inter.paths)):
            assert inter._crossing_groups(i) is not None
            assert inter._crossing_attribution(i) is not None

    def test_dense_lissajous_merges_coincident_crossings(self):
        # (2,3) 利萨如的采样点正好落在交叉上(离散化使然) → 同一位置被两条相邻线段对各枚举一次,
        # 出现两个几乎重合的锚点; `_merge_crossings` 必须把它们并成一组, 否则记录会"命中两个锚点"
        # 而被判歧义(见 PROGRESS §3 P0-5)。
        #
        # ⚠️ 采样密度的选取很关键: ``dt=0.05`` 时**没有**重合锚点(实测最小间距 15.9×offset),
        # 真正重合的是 ``dt=0.02``(最小间距 1.4e-10 = 采样顶点恰好落在交叉上)。
        # 缺陷 11 修复前, ``dt=0.05`` 那个"相距 1.7e-5 的锚点对"其实来自闭合路径起始顶点上的
        # **幻影自交**(利萨如的起点正好是原点、且曲线多次穿过原点), 不是离散化。
        curve = ParametricFunction(
            lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0]),
            t_range=(0, TAU, 0.02),
            use_smoothing=False,
        )
        inter = Interlacing(mobject_paths(curve), 0.05, validate="ignore")
        crossings = inter._centerline_crossings(0)
        points = np.array([crossing["point"] for crossing in crossings])
        gaps = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
        np.fill_diagonal(gaps, np.inf)
        assert gaps.min() < 0.1 * inter.offset  # 存在两个几乎重合的锚点
        anchors, _limits, merged = inter._merge_crossings(crossings)
        assert len(anchors) < len(crossings)  # 合并后锚点变少
        assert any(len(group) > 1 for group in merged)  # 确实合并了

    def test_coarse_lissajous_has_no_coincident_crossings(self):
        # 缺陷 11 的回归(反面): 去掉幻影之后, dt=0.05 的 7 个交叉两两相距很远(> 10×offset),
        # 不再有"贴着起点"的假锚点。
        curve = ParametricFunction(
            lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0]),
            t_range=(0, TAU, 0.05),
            use_smoothing=False,
        )
        inter = Interlacing(mobject_paths(curve), 0.05, validate="ignore")
        crossings = inter._centerline_crossings(0)
        assert len(crossings) == 7
        points = np.array([crossing["point"] for crossing in crossings])
        gaps = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
        np.fill_diagonal(gaps, np.inf)
        assert gaps.min() > 10 * inter.offset

    def test_dense_lissajous_is_degraded_and_groups_cleanly(self):
        # 新路径的启用前提: ① 现行实现确实降级; ② 分组干净(合并 + 绕回感知分簇之后)。
        # ⚠️ "归属算得出来"在测试进程里不是稳定的性质(几何对枚举顺序敏感), 所以不断言;
        # 更要紧的是: **画面判定(C/D/E)仍不过** —— 缺口在 `_set_ribbons` 的片段构造,
        # 因此这条新路径**不接入决策路径**(见 PROGRESS §3 P0-5)。
        curve = ParametricFunction(
            lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0]),
            t_range=(0, TAU, 0.05),
            use_smoothing=False,
        )
        inter = Interlacing(mobject_paths(curve), 0.05, validate="ignore")
        assert inter._degraded_paths == {0}
        assert inter._crossing_groups(0) is not None

    def test_healthy_configs_are_not_degraded(self):
        # 阶段 1 的启用条件是"现行实现会降级", 健康配置根本不会走到新路径
        inter = Interlacing(self.crossing_lines(), 0.2, validate="ignore")
        assert inter._degraded_paths == set()
        assert inter.rail_issues == []


class TestPhantomStartCrossing:
    """缺陷 11: 闭合路径的**首末相邻段**共享起始顶点, 不该被登记成自交(幻影锚点)。

    ``_centerline_crossings`` 的跳过条件原先写成"``not closed`` 才跳过", 恰好写反了:

    * 闭合路径的首段与末段共享起始顶点(``path[-1] == path[0]``), 是相邻的, 必须跳过 ——
      原先却登记成自交, 于是**每条闭合路径**的起始顶点上都多出一个幻影锚点。它在交叉分组里
      是一个**空组**, 让"按交叉身份"的切分无条件放弃(``_crossing_attribution`` /
      ``_crossing_layout`` 遇空组返回 ``None``), 并把附近真实交叉的轨记录判成"歧义";
    * 开放路径的 0 号与末号段不相邻, 必须保留 —— 原先反而跳过, 漏掉真实自交。

    证据: ``media/_review/phantom_start_crossing_probe.py``(逐配置列出落在起始顶点上的假自交)、
    ``phantom_matrix_probe.py``(全矩阵 1166 行的真实影响面)。
    """

    @pytest.mark.parametrize(
        ("name", "path"),
        [
            ("正方形环", square_ring(3.0)),
            ("65 边形环", ring_path(65)),
            ("矩形环", np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 2.0], [0.0, 2.0], [0.0, 0.0]])),
        ],
    )
    def test_closed_paths_have_no_self_crossing_at_the_start(self, name, path):
        inter = Interlacing([path], 0.2, validate="ignore")
        assert inter.paths_closed[0]
        self_crossings = [crossing for crossing in inter._centerline_crossings(0) if crossing["q"] == 0]
        assert self_crossings == [], f"{name} 不该有任何自交(包括起始顶点上的幻影)"

    def test_open_path_counts_the_first_last_segment_pair(self):
        # 开放路径的首末段不相邻: 它们的真实自交**必须**被登记(原先被误跳过)
        path = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [2.0, 3.0], [2.0, -1.0]])
        inter = Interlacing([path], 0.2, validate="ignore")
        assert not inter.paths_closed[0]
        pairs = {(crossing["i_seg"], crossing["q_seg"]) for crossing in inter._centerline_crossings(0)}
        assert (0, 3) in pairs
        crossing = next(item for item in inter._centerline_crossings(0) if (item["i_seg"], item["q_seg"]) == (0, 3))
        np.testing.assert_allclose(crossing["point"], [2.0, 0.0])


class TestAnnulusLoops:
    """``_annulus_loops`` 的结构识别: 只认 ``annulus_polygon`` 的产物。"""

    @staticmethod
    def restitch(outer: np.ndarray, inner: np.ndarray) -> np.ndarray:
        """按 annulus_polygon 的公式把两条环缝回一条轮廓。

        ``inner`` 是**遍历方向**(顺时针)的内环, 缝回去要先换回逆时针起点环。
        """
        ccw = np.roll(inner[::-1], 1, axis=0)
        return np.vstack([outer, outer[:1], ccw[:1], ccw[:0:-1], ccw[:1], outer[:1]])

    def test_round_trips_annulus_polygon(self):
        outer = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]])
        inner = np.array([[1.0, 1.0], [1.0, 3.0], [3.0, 3.0], [3.0, 1.0]])  # 顺时针
        ribbon = annulus_polygon(outer, inner)
        loops = _annulus_loops(ribbon)
        assert loops is not None
        split_outer, split_inner = loops
        np.testing.assert_array_equal(self.restitch(split_outer, split_inner), ribbon)
        assert _signed_area(split_outer) > 0 > _signed_area(split_inner)
        assert _signed_area(split_outer) > -_signed_area(split_inner)

    def test_round_trips_dense_ring(self):
        outer = ring_path(65, 2.0)
        inner = ring_path(65, 1.8)[::-1]
        ribbon = annulus_polygon(outer, inner)
        loops = _annulus_loops(ribbon)
        assert loops is not None
        split_outer, split_inner = loops
        np.testing.assert_array_equal(self.restitch(split_outer, split_inner), ribbon)

    def test_rejects_plain_closed_polygon(self):
        triangle = np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 2.0], [0.0, 0.0]])
        assert _annulus_loops(triangle) is None

    def test_rejects_open_path_strip(self):
        left = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
        right = np.array([[0.0, 0.3], [1.0, 0.3], [2.0, 0.3]])
        strip = np.vstack([left, right[::-1], left[:1]])
        assert _annulus_loops(strip) is None

    def test_rejects_same_winding_inner_loop(self):
        # 内环与外环同向时非零绕数填不出孔洞, 必须退回单轮廓狭缝多边形
        outer = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]])
        inner = np.array([[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]])
        assert _annulus_loops(np.vstack([outer, inner, outer[:1]])) is None

    def test_rejects_inner_loop_larger_than_outer(self):
        # "内环"比外环还大时不是环形带, 同样退回单轮廓狭缝多边形
        outer = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]])
        inner = np.array([[0.5, 0.5], [0.5, 3.0], [3.0, 3.0], [3.0, 0.5], [0.5, 0.5]])
        assert _annulus_loops(np.vstack([outer, inner, outer[:1]])) is None
