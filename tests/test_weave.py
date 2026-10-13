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
    check_centerline_coverage,
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
