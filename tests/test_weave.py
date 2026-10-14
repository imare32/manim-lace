"""编织(交错)可见性模型的回归测试。

按画家顺序(先 ``holes`` 再 ``ribbons``)重建最终可见图形, 检验 ``tests/weave_checks.py``
里的 A/C/D/E/F/G 性质。这些用例是修复 `_set_ribbons` 时的安全网: 任何"配对错位 /
双带同绘 / 背景破洞 / 孔洞被盖死 / 对称破坏"都会在这里暴露。
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from manim_lace.interlacing import Interlacing
from tests.helpers import (
    crossing_lines,
    level_zero_rosette_paths,
    ring_path,
    rosette_paths,
    square_ring,
    weave_grid_paths,
)
from tests.weave_checks import (
    check_alternation,
    check_centerline_coverage,
    check_crossings_pressed,
    check_holes_visible,
    check_picture,
    check_rotational_symmetry,
)


def build(paths, offset: float, suppress: bool = True) -> Interlacing:
    """构造求解器。``suppress=False`` 保留告警, 供 ``pytest.warns`` 捕获。"""
    if not suppress:
        return Interlacing(paths, offset)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Interlacing(paths, offset)


def visibility_problems(interlacing: Interlacing, symmetry: int | None = None) -> list[str]:
    """返回一幅图违反编织性质的全部问题(空列表表示通过)。"""
    return check_picture(interlacing, symmetry=symmetry, sample_step_factor=0.05)


def assert_clean(name: str, paths, offset: float, symmetry: int | None = None) -> Interlacing:
    """断言一幅图通过全部可见性检查。"""
    solver = build(paths, offset)
    problems = visibility_problems(solver, symmetry)
    assert problems == [], f"{name} 违反了编织性质:\n" + "\n".join(f"  - {p}" for p in problems)
    return solver


class TestKnownGoodWeaves:
    """这些配置在修复前后都应满足 A/C/D/E/F/G。"""

    def test_x_crossing(self):
        assert_clean("X 形两线", crossing_lines(2.0), 0.2)

    def test_weave_grid_three(self):
        assert_clean("3x3 编织网格", weave_grid_paths(3), 0.1)

    def test_pa_n12_l2(self):
        paths, offset = rosette_paths(12, 2, "PA")
        assert_clean("PA n=12 L2", paths, offset, symmetry=12)

    def test_ca_n9_l1(self):
        paths, offset = rosette_paths(9, 1, "CA")
        assert_clean("CA n=9 L1", paths, offset, symmetry=9)

    def test_pa_n8_l4(self):
        paths, offset = rosette_paths(8, 4, "PA")
        assert_clean("PA n=8 L4", paths, offset, symmetry=8)


class TestSimpleClosedCurves:
    """缺陷 1/2 的端到端可见性: 环形丝带 + 可见孔洞。"""

    @pytest.mark.parametrize(
        ("name", "paths", "offset"),
        [
            ("正方形环", [square_ring(3.0)], 0.2),
            ("17 边形环", [ring_path(17)], 0.2),
            ("65 边形环", [ring_path(65)], 0.2),
            ("PO n=7 L0", level_zero_rosette_paths(7, "PO"), 0.05),
            ("PA n=9 L0", level_zero_rosette_paths(9, "PA"), 0.05),
        ],
    )
    def test_is_a_visible_annulus(self, name, paths, offset):
        solver = assert_clean(name, paths, offset)
        assert len(solver.ribbons) == 1
        assert len(solver.holes) == 1

    def test_centerline_is_covered_everywhere(self):
        problems: list[str] = []
        check_centerline_coverage(build([square_ring(3.0)], 0.2), problems)
        assert problems == []


class TestConcentricRosetteAlignment:
    """缺陷 3: 同心玫瑰线(CR)的左右偏移线交点应逐事件对齐。"""

    def test_rail_event_counts_match_on_the_defective_segment(self):
        paths, offset = rosette_paths(10, 3, "CR")
        solver = build(paths, offset)
        left = solver.d_seg_intersects[(0, 1, 0)]
        right = solver.d_seg_intersects[(0, 2, 0)]
        assert len(left) == len(right)
        # 补回来的近失交点要紧跟着它的配对事件
        missing = (1, 2, 10)
        assert left.index(missing) == left.index((1, 1, 10)) + 1

    def test_polygons_stay_finite_and_closed(self):
        # 对齐只补交点, 不应产出非有限坐标或未闭合的多边形
        paths, offset = rosette_paths(10, 3, "CR")
        solver = build(paths, offset)
        for polygon in (*solver.holes, *solver.ribbons):
            arr = np.asarray(polygon, dtype=float)
            assert np.all(np.isfinite(arr))
            np.testing.assert_allclose(arr[0], arr[-1])

    def test_unaligned_segments_are_reported_once(self):
        # 派生几何不满足配对契约时不再静默, 但也不逐段刷屏(整幅图只警告一次)
        paths, offset = rosette_paths(10, 3, "CR")
        with pytest.warns(UserWarning, match="配对契约"):
            solver = build(paths, offset, suppress=False)
        assert len(solver.rail_issues) == len(solver.paths)
        assert all(issue.startswith("路径 ") for issue in solver.rail_issues)

    def test_affected_paths_degrade_to_plain_bands(self):
        # 降级渲染: 受影响的路径不再切成错乱片段, 而是各出一条"不编织"的整条丝带
        paths, offset = rosette_paths(10, 3, "CR")
        solver = build(paths, offset)
        assert solver.rail_issues
        assert len(solver.ribbons) == len(solver.paths)
        for ribbon in solver.ribbons:
            assert len(ribbon) > len(solver.paths_l[0])  # 整带 = 外轮廓 + 内轮廓

    def test_clean_config_has_no_rail_issues(self):
        paths, offset = rosette_paths(12, 2, "PA")
        solver = build(paths, offset)
        assert solver.rail_issues == []
        assert solver.ribbons  # 仍然正常编织


class TestRailAttributionNormalization:
    """缺陷 3 的 CA 分支: 接缝弧长不同造成的"逐段错位"重归属后必须恢复编织。

    这些配置的两条轨道**事件总数完全相等**(cross/self/corner 三类都相等), 只是同一个
    交叉的两侧交点被登记到了相邻线段上; 重归属后逐段计数相等, 路径不再降级。
    """

    #: (n, level): 修复前每条线段左右计数都不等的 CA 配置
    NORMALIZED = [(9, 5), (15, 5), (16, 4), (16, 5)]

    @pytest.mark.parametrize(("n", "level"), NORMALIZED)
    def test_paths_are_woven_again(self, n, level):
        paths, offset = rosette_paths(n, level, "CA")
        solver = build(paths, offset)
        assert solver.rail_issues == []
        assert solver._degraded_paths == set()
        # 真的被切成很多片段(降级时只有"每条路径一段")
        assert len(solver.ribbons) > 10 * len(paths)
        assert len(solver.holes) > 0

    @pytest.mark.parametrize(("n", "level"), NORMALIZED)
    def test_left_and_right_event_counts_match(self, n, level):
        paths, offset = rosette_paths(n, level, "CA")
        solver = build(paths, offset)
        for i in range(len(solver.paths)):
            for j in range(len(solver.paths_l[i]) - 1):
                assert len(solver.d_seg_intersects[(i, 1, j)]) == len(solver.d_seg_intersects[(i, 2, j)])

    @pytest.mark.parametrize(("n", "level"), NORMALIZED)
    def test_each_crossing_is_covered_by_exactly_one_ribbon(self, n, level):
        paths, offset = rosette_paths(n, level, "CA")
        solver = build(paths, offset)
        problems: list[str] = []
        assert check_crossings_pressed(solver, problems) == 0, problems
        # 中心线上不应出现背景破洞(该连的地方都连上了), 孔洞也不应被丝带盖死
        assert check_centerline_coverage(solver, [], step_factor=0.05)["holes"] == 0
        assert check_holes_visible(solver, []) == 0

    def test_clean_config_is_left_untouched(self):
        # 逐段计数本来就相等的路径不参与重归属 —— 正常输入输出不变的保证
        paths, offset = rosette_paths(12, 4, "CA")
        solver = build(paths, offset)
        assert solver.rail_issues == []
        assert (len(solver.holes), len(solver.ribbons)) == (49, 48)
        problems: list[str] = []
        assert check_alternation(solver, problems) == 0


class TestClosedConfigurationFlags:
    """闭合曲线组合的上下压自洽: 起始 flag 必须令每个交叉恰好一方压上。

    闭合路径的 ``paths_flag`` 一律为 ``True``, 两条只相交两次的闭合曲线(两圆相交)因此
    在交叉处**同时**下压、丝带根本不切分(ribbons 只剩两条整环)。``_fix_path_flags()``
    只在"当前取值不自洽"时才动手, 所以对既有正常输入零影响。

    注意: 判定"真的在编织"必须在交点本身取探针(只取两侧远端探针会把被压方误判成连续),
    见 :meth:`test_two_overlapping_rings_are_woven`。
    """

    def test_two_overlapping_rings_are_woven(self):
        """两圆相交: 两个交叉处必须一压一让(交替编织)。

        每个交叉在各自轨道只登记 2 个事件, 所以两条丝带各自仍是**一个 132 顶点的多边形**
        (在环的另一侧连通) —— 但被压方在交点附近确实断开了: 上交点黄带断、下交点青带断
        (渲染证据 `media/images/audit_rings_zoom/RingsTop.png` / `RingsBottom.png`)。

        ⚠️ 判定这一点**必须**在交点本身取探针: 只看交点两侧的远端探针时, 被压方的两截
        属于同一个多边形, 会被误判成"连续穿过"(2026-10-14 踩过这个坑)。
        """
        left = ring_path(64, 1.5) + np.array([-0.8, 0.0])
        right = ring_path(64, 1.5) + np.array([0.8, 0.0])
        offset = 0.015 * 2.3  # 外接半径 ≈ 2.3
        solver = build([left, right], offset)
        assert solver.rail_issues == []
        assert solver._degraded_paths == set()
        assert solver.paths_flag[0] != solver.paths_flag[1]  # 约束解得"一压一让"
        problems: list[str] = []
        assert check_crossings_pressed(solver, problems) == 0, problems
        assert check_centerline_coverage(solver, [], step_factor=0.05)["holes"] == 0

    def test_flags_are_left_alone_when_already_consistent(self):
        # X 形两线本就自洽([True, False]), 修正步骤必须原样保留
        solver = build(crossing_lines(2.0), 0.1)
        assert solver.paths_flag == [True, False]

    def test_concentric_rings_need_no_flag_change(self):
        paths = [ring_path(64, 2.0), ring_path(48, 1.2)]
        solver = build(paths, 0.03)
        assert solver.paths_flag == [True, True]  # 无交叉, 没有约束可解
        assert len(solver.ribbons) == 2


class TestCheckerSelfConsistency:
    """校验脚本自身的健全性检查。"""

    def test_clean_picture_on_empty_input(self):
        assert visibility_problems(build([], 0.1)) == []

    def test_rotational_symmetry_is_a_noop_without_polygons(self):
        problems: list[str] = []
        check_rotational_symmetry(build([], 0.1), 6, problems)
        assert problems == []

    def test_rotational_symmetry_flags_asymmetric_input(self):
        # 10 重对称的图形不应通过 2π/3 对称检查
        paths, offset = rosette_paths(10, 2, "PA")
        problems: list[str] = []
        check_rotational_symmetry(build(paths, offset), 3, problems)
        assert problems

    def test_reports_problems_for_a_solid_disc(self):
        # 手工构造"内圆盘盖死孔洞"的坏图, 确认 E/F 检查会报警
        solver = build([square_ring(3.0)], 0.2)
        solver.ribbons.append(np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0], [0.0, 0.0]]))
        problems = visibility_problems(solver)
        assert any(problem.startswith("F") for problem in problems)
