"""第二条通道("中心线 + ``stroke_width`` + 顺序")的回归测试。

守住三件事:

1. **切口几何**: 每个交叉处"压上方"的弧长仍落在它的片段内, 而"被压方"的弧长落在断口里
   —— 这正是"切开就保证可见性"的几何含义, 与不透明度无关;
2. **硬约束**: 线宽必须严格对应 ``offset``、必须不透明 —— 端头残差靠"不透明 + 顺序"兜住,
   冲突的 kwargs 必须被忽略并告警(见 `PROGRESS.md` §3 P0-6);
3. **默认通道不动**: ``render="ribbon"`` 与默认值产出完全相同的片段数据。
"""

from __future__ import annotations

import numpy as np
import pytest
from manim import VGroup, VMobject

from manim_lace import Lace
from manim_lace.stroke import STROKE_UNITS_PER_WIDTH, StrokeWeave, centerline_crossings
from tests.helpers import lissajous_paths, ring_path

X_PATHS = [
    np.array([[-2.0, 0.0], [2.0, 0.0]]),
    np.array([[0.0, -1.6], [0.0, 1.6]]),
]


def weave(paths, offset: float = 0.2) -> StrokeWeave:
    return StrokeWeave(paths, offset)


def paths_mobject(paths) -> VGroup:
    """把折线包成"全是直线段"的 mobject(走与 `Lace` 相同的输入通道)。"""
    group = VGroup()
    for path in paths:
        coordinates = np.asarray(path, dtype=float)[:, :2]
        mobject = VMobject()
        mobject.set_points_as_corners(np.column_stack([coordinates, np.zeros(len(coordinates))]))
        group.add(mobject)
    return group


class TestCenterlineCrossings:
    """中心线求交(路径之间 + 自交)本身。"""

    def test_two_lines_cross_once(self):
        crossings = centerline_crossings(X_PATHS)
        assert len(crossings) == 1
        crossing = crossings[0]
        assert (crossing["i"], crossing["j"]) == (0, 1)
        np.testing.assert_allclose(crossing["point"], [0.0, 0.0], atol=1e-9)
        np.testing.assert_allclose([crossing["s_i"], crossing["s_j"]], [2.0, 1.6], atol=1e-9)

    def test_dense_lissajous_has_seven_self_crossings(self):
        crossings = centerline_crossings(lissajous_paths(0.01))
        assert len(crossings) == 7
        assert all(crossing["i"] == crossing["j"] == 0 for crossing in crossings)

    def test_adjacent_segments_are_not_crossings(self):
        # 折线的相邻线段共享角点, 不能当成自交(否则每条折线都"处处交叉")
        assert centerline_crossings([ring_path(9, 1.0)]) == []

    def test_three_lines_meeting_at_one_point_are_deduplicated(self):
        # 三线共点: 同一位置被枚举 3 次, 只保留一个(那里的"谁压谁"没有定义)
        paths = [
            np.array([[-1.0, 0.0], [1.0, 0.0]]),
            np.array([[0.0, -1.0], [0.0, 1.0]]),
            np.array([[-1.0, -1.0], [1.0, 1.0]]),
        ]
        assert len(centerline_crossings(paths)) == 1

    def test_circles_cross_twice(self):
        left = ring_path(65, 1.0)
        right = ring_path(65, 1.0) + np.array([1.2, 0.0])
        assert len(centerline_crossings([left, right])) == 2


class TestAlternation:
    """过/欠的交替赋值与它的边界。"""

    def test_crossing_lines_alternate(self):
        solver = weave(X_PATHS, 0.2)
        assert solver.flags is not None
        assert solver.upper_path(0) in {(0, 1), (1, 0)}

    def test_dense_lissajous_alternates(self):
        solver = weave(lissajous_paths(0.01), 0.05)
        assert solver.flags is not None
        # 单条闭合路径被 7 个交叉各切一刀 → 7 段
        assert solver.num_segments == 7

    def test_conflicting_alternation_has_no_solution(self):
        # 两条互相交叉又各自自交的闭合曲线: 约束互相冲突 —— 可能报"路径间奇环", 也可能报
        # "同一条路径上两次通过的位置差为偶数"(两者都是交替无解), 无论哪种都不该硬猜
        curve = lissajous_paths(0.01)[0]
        rotated = np.column_stack([curve[:, 1], curve[:, 0]])
        solver = weave([curve, rotated], 0.05)
        assert solver.flags is None
        assert solver.segments == []
        assert solver.issues

    def test_three_pairwise_crossing_lines_alternate(self):
        # 三条线段两两在内部相交: 三个交叉、每条线段两次通过 —— "位置奇偶"提供的自由度足够,
        # **有解**。真正无解的是"同一条路径上两次通过的位置差为偶数"那一类(见上面的两条利萨如)。
        paths = [
            np.array([[-2.0, 0.0], [2.0, 0.0]]),
            np.array([[0.0, -1.5], [1.5, 1.5]]),
            np.array([[-1.5, -1.0], [1.5, 1.0]]),
        ]
        solver = weave(paths, 0.1)
        assert len(solver.crossings) == 3
        assert solver.flags is not None
        for index in range(len(solver.crossings)):
            upper, lower = solver.upper_path(index)
            assert upper != lower


class TestCutGeometry:
    """切口的不变量: 压上方连续、被压方断开。"""

    def test_upper_is_covered_and_lower_is_cut(self):
        solver = weave(X_PATHS, 0.2)
        for index in range(len(solver.crossings)):
            upper, lower = solver.upper_path(index)
            arcs = dict(solver.crossing_ends(index))
            assert solver.covers(upper, arcs[upper])
            assert not solver.covers(lower, arcs[lower])

    def test_self_crossing_cuts_only_the_lower_pass(self):
        solver = weave(lissajous_paths(0.01), 0.05)
        for index in range(len(solver.crossings)):
            (path_a, arc_a), (path_b, arc_b) = solver.crossing_ends(index)
            upper_a = solver.is_upper(path_a, solver.pass_position(index, 0))
            upper_b = solver.is_upper(path_b, solver.pass_position(index, 1))
            assert upper_a != upper_b, "同一次穿越必须一压一被压"
            assert solver.covers(path_a, arc_a) == upper_a
            assert solver.covers(path_b, arc_b) == upper_b

    def test_segments_stay_inside_the_path(self):
        solver = weave(lissajous_paths(0.01), 0.05)
        length = float(solver._tables[0]["cumulative"][-1])
        for segment in solver.segments:
            assert segment["path"] == 0
            assert 0.0 <= segment["start"] < length
            assert segment["span"] > 0.0
            assert len(segment["points"]) >= 2


class TestStrokeRendering:
    """`Lace(render="stroke")` 的装配与硬约束。"""

    def test_opaque_width_matches_offset_and_no_holes(self):
        lace = Lace(paths_mobject(X_PATHS), offset=0.2, render="stroke")
        assert lace.num_holes == 0
        assert lace.num_ribbons == 3  # 压上方一整条 + 被压方两段
        width = 2.0 * 0.2 / STROKE_UNITS_PER_WIDTH
        for mobject in lace.ribbons:
            assert np.isclose(mobject.stroke_width, width)
            assert np.isclose(mobject.stroke_opacity, 1.0)
            assert np.isclose(mobject.fill_opacity, 0.0)

    def test_ribbon_swatch_by_path_colours_the_pieces(self):
        from manim import BLUE, GREEN

        lace = Lace(
            paths_mobject(X_PATHS),
            offset=0.2,
            render="stroke",
            ribbon_swatch=(BLUE, GREEN),
            ribbon_group_method="by_path",
        )
        # 片段按"所属路径"取色: 路径 0 的片段一个色, 路径 1 的两个片段另一个色
        assert lace.weave.segments[0]["path"] == 0
        colours = [mobject.get_stroke_color().to_hex() for mobject in lace.ribbons]
        assert len(set(colours)) == 2

    def test_conflicting_kwargs_are_ignored_with_warning(self):
        with pytest.warns(UserWarning, match="stroke_width"):
            lace = Lace(paths_mobject(X_PATHS), offset=0.2, render="stroke", stroke_width=7)
        assert np.isclose(lace.ribbons[0].stroke_width, 2.0 * 0.2 / STROKE_UNITS_PER_WIDTH)

    def test_conflicting_alternation_falls_back_to_plain_paths(self):
        curve = lissajous_paths(0.01)[0]
        rotated = np.column_stack([curve[:, 1], curve[:, 0]])
        with pytest.warns(UserWarning, match="交替无解|奇环"):
            lace = Lace(paths_mobject([curve, rotated]), offset=0.05, render="stroke")
        assert lace.num_ribbons == 2  # 退化成两根完整描边(不编织但形状正确)

    def test_unknown_render_is_rejected(self):
        with pytest.raises(ValueError):
            Lace(paths_mobject(X_PATHS), offset=0.2, render="twisted")

    def test_ribbon_channel_is_the_default_and_unchanged(self):
        default = Lace(paths_mobject(X_PATHS), offset=0.2)
        explicit = Lace(paths_mobject(X_PATHS), offset=0.2, render="ribbon")
        assert default.num_ribbons == explicit.num_ribbons
        assert default.num_holes == explicit.num_holes
        for left, right in zip(default.ribbons, explicit.ribbons):
            np.testing.assert_allclose(left.points, right.points)
