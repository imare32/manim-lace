"""类二/类三/类四测试矩阵的**固化回归**(PROGRESS §3 P1-7)。

这三个类别的配置原先只活在 `media/` 的渲染矩阵与浏览页里(渲染产物不入库), 于是"哪些配置
合格、哪些必须诚实降级、哪些超出当前判据"这条结论**没有任何测试守着** —— 一旦有人改动
核心几何层, 结论可能悄悄失效而全套测试仍然全绿。本模块把它固化成三条断言线:

1. **合格配置**(`HEALTHY`): 不降级、无派生几何告警、无输入退化告警, 且可见性模型
   A/C/D/E/F 全过; 同时 pin 住 `(孔洞数, 丝带片段数)` —— 几何层的任何"顺手改动"都会在这里
   立刻暴露(PROGRESS §0 的收录门槛: 不降级无残差)。
2. **诚实降级**(`DEGRADED`): 相切 / 共顶点 / 共线共边 / 同点并发这类输入必须是
   **输入校验或派生几何自检挡下 + `UserWarning`**, 而不是静默产出错乱图形
   (项目的红线是"宁可不变好, 不可静默画错")。
3. **超出当前判据**(`LIMITATIONS`): 星形多边形自交、奇环(三圆链)这类"交替织法"本身
   无解或尚未覆盖的配置, 门禁不收 —— 但也不允许被当成合格。它们当前**不降级却画面不合格**,
   属于已知短板(§3 P1-6/P1-8/P1-9); 哪天真修好了, 这里会失败, 应当把它们移进 `HEALTHY`。

最后一条 **分类完整性** 测试断言每个配置恰好落进三类之一, 即"不许既不合格又没有任何交代"。

判定与渲染**同尺度**(见 `tests/cases.py` 的 `scaled`), 否则平铺/内接这类对浮点极敏感的
配置会得出与渲染相反的结论。
"""

from __future__ import annotations

import warnings
from functools import cache

import numpy as np
import pytest

from manim_lace.interlacing import Interlacing
from tests import cases
from tests.helpers import assert_closed_polygons, assert_is_counter_clockwise
from tests.weave_checks import check_picture

#: 合格配置的定案指标: ``名字 -> (孔洞数, 丝带片段数)``。
HEALTHY: dict[str, tuple[int, int]] = {
    # 类二: 闭合 × 闭合
    "Closed_two_circles": (3, 2),
    "Closed_concentric_rings": (4, 2),
    "Closed_square_rot45": (9, 8),
    "Closed_hexagon_rot30": (13, 12),
    "Closed_two_triangles": (7, 6),
    # 类三: 闭合 + 开放
    "Mixed_circle_plus_line": (4, 3),
    "Mixed_circle_plus_three_lines": (8, 9),
    "Mixed_hexagon_plus_lines": (8, 9),
    # 类四: 开放 + 开放
    "Open_weave_grid3": (16, 15),
    "Open_weave_grid4": (25, 24),
    "Open_weave_grid5": (36, 35),
    "Open_skew_lattice": (12, 15),
    "Open_diagonal_lattice": (12, 15),
    "Open_two_waves": (4, 3),
    "Open_crossing_pairs": (12, 15),
}

#: 必须"诚实降级"的配置(输入退化 / 派生几何不满足配对契约) —— 一律要有 `UserWarning`。
DEGRADED: set[str] = {
    "Closed_square_inscribed_circle",
    "Closed_square_inscribed_rot_square",
    "Closed_two_squares_shared_edge",
    "Closed_triangle_hexagon_shared_vertices",
    "Mixed_square_plus_skew_lines",
    "Mixed_triangle_plus_lines",
    "Mixed_touching_circle_plus_line",
    "Open_lattice3",
    "Open_braid_three",
    "Open_fan_concurrent",
    "Open_grid_plus_diagonals",
}

#: 超出当前判据(不降级但画面不合格)的已知短板 —— 见模块 docstring 第 3 条。
LIMITATIONS: set[str] = {
    "Closed_pentagram_plus_pentagon",
    "Closed_hexagon_plus_star_of_david",
    "Closed_nested_three",
    "Closed_star7_3_plus_circle",
    "Closed_three_circles_chain",
    "Mixed_circle_plus_two_chords",
    "Mixed_two_rings_plus_line",
    "Mixed_ring_plus_zigzag",
    "Mixed_ring_plus_crossing_chords",
    "Open_zigzag_pair",
}

#: 合格但**本来就没有交点**的配置: 同心双圆是无自交的环形带(缺陷 1/2 的修复对象),
#: "真的在编织"这条断言对它们不适用。
NO_CROSSING_HEALTHY: set[str] = {"Closed_concentric_rings"}

#: 采样步长(与渲染矩阵的门禁一致)。
SAMPLE_STEP_FACTOR = 0.05


@cache
def solve(name: str) -> tuple[Interlacing, bool]:
    """求解一个配置, 并回报是否发出了 `UserWarning`(降级 / 输入退化的诚实信号)。"""
    _name, _caption, paths = cases.by_name(name)
    scaled, offset = cases.scaled(paths)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        solver = Interlacing(scaled, offset)
    warned = any(issubclass(item.category, UserWarning) for item in caught)
    return solver, warned


@cache
def problems_of(name: str) -> tuple[str, ...]:
    """可见性模型 A/C/D/E/F 的问题列表(空元组 = 全过)。"""
    solver, _warned = solve(name)
    return tuple(check_picture(solver, sample_step_factor=SAMPLE_STEP_FACTOR))


def all_names() -> list[str]:
    return [case[0] for category in cases.CATEGORIES.values() for case in category]


def is_honestly_reported(name: str) -> bool:
    """该配置是否给出了"这条输入有问题"的显式信号(输入退化 / 降级 / 派生几何告警)。"""
    solver, _warned = solve(name)
    return bool(solver.path_issues or solver._degraded_paths or solver.rail_issues)


def test_every_case_is_classified():
    """每个配置恰好落进 合格 / 诚实降级 / 已知短板 三类之一, 不许"既不画对也不吭声"。"""
    misclassified: list[str] = []
    for name in all_names():
        _solver, warned = solve(name)
        if name in HEALTHY:
            expected = "healthy"
        elif name in DEGRADED:
            expected = "degraded"
        elif name in LIMITATIONS:
            expected = "limitation"
        else:
            misclassified.append(f"{name}: 未在 HEALTHY/DEGRADED/LIMITATIONS 任何一张表里")
            continue
        if expected == "healthy":
            wrong = is_honestly_reported(name) or problems_of(name)
        elif expected == "degraded":
            wrong = not (warned and is_honestly_reported(name))
        else:
            wrong = is_honestly_reported(name) or warned or not problems_of(name)
        if wrong:
            detail = (
                f"告警={warned} 降级={sorted(_solver._degraded_paths)} "
                f"issues={list(_solver.rail_issues)[:2]} path_issues={list(_solver.path_issues)[:2]} "
                f"可见性={'全过' if not problems_of(name) else sorted({p.split(':')[0] for p in problems_of(name)})}"
            )
            misclassified.append(f"{name}: 实际状态与 `{expected}` 不符({detail})")
    assert misclassified == [], "矩阵分类与实际不符:\n" + "\n".join(f"  - {item}" for item in misclassified)


def test_tables_cover_every_case():
    """三张表合起来必须覆盖矩阵里的全部配置(新增候选时要一并归档)。"""
    declared = set(HEALTHY) | DEGRADED | LIMITATIONS
    assert declared == set(all_names())


class TestHealthyConfigurations:
    """合格配置: 不降级 + 无告警 + 可见性全过 + 指标不变。"""

    @pytest.mark.parametrize(("name", "counts"), sorted(HEALTHY.items()))
    def test_no_degradation_and_no_warning(self, name, counts):
        solver, warned = solve(name)
        assert not warned, f"{name} 不该发出降级告警"
        assert solver.path_issues == []
        assert solver.rail_issues == []
        assert solver._degraded_paths == set()
        assert solver._woven_paths == {}  # 健康配置不进"按交叉身份"的新路径

    @pytest.mark.parametrize(("name", "counts"), sorted(HEALTHY.items()))
    def test_visibility_model_passes(self, name, counts):
        assert problems_of(name) == ()

    @pytest.mark.parametrize(("name", "counts"), sorted(HEALTHY.items()))
    def test_polygon_counts_are_pinned(self, name, counts):
        solver, _warned = solve(name)
        assert (len(solver.holes), len(solver.ribbons)) == counts

    @pytest.mark.parametrize(("name", "counts"), sorted(HEALTHY.items()))
    def test_output_polygons_are_valid(self, name, counts):
        solver, _warned = solve(name)
        assert_closed_polygons(solver.holes, min_vertices=3)
        assert_closed_polygons(solver.ribbons, min_vertices=3)
        assert_is_counter_clockwise(solver.holes)
        assert_is_counter_clockwise(solver.ribbons)

    @pytest.mark.parametrize("name", sorted(set(HEALTHY) - NO_CROSSING_HEALTHY))
    def test_curves_actually_cross(self, name):
        """合格配置必须真的在编织(有交点), 否则"全过"是空跑。"""
        from tests.weave_checks import crossing_count

        solver, _warned = solve(name)
        between, within = crossing_count(solver.paths)
        assert between + within > 0


class TestHonestDegradation:
    """退化输入: 必须显式报告(告警 + 结构化信号), 且不产出非有限坐标。"""

    @pytest.mark.parametrize("name", sorted(DEGRADED))
    def test_warns_instead_of_drawing_silently(self, name):
        _solver, warned = solve(name)
        assert warned, f"{name} 必须发出 UserWarning(诚实降级)"

    @pytest.mark.parametrize("name", sorted(DEGRADED))
    def test_reports_a_structured_reason(self, name):
        solver, _warned = solve(name)
        assert solver.path_issues or solver.rail_issues, f"{name} 应当给出可查的原因"

    @pytest.mark.parametrize("name", sorted(DEGRADED))
    def test_degraded_output_is_still_finite_and_closed(self, name):
        solver, _warned = solve(name)
        for polygon in (*solver.holes, *solver.ribbons):
            arr = np.asarray(polygon, dtype=float)
            assert np.all(np.isfinite(arr))
            np.testing.assert_allclose(arr[0], arr[-1])


class TestKnownLimitations:
    """已知短板: 不降级但画面不合格 —— 固化现状, 修好后应移进 `HEALTHY`。"""

    @pytest.mark.parametrize("name", sorted(LIMITATIONS))
    def test_is_not_silently_claimed_healthy(self, name):
        _solver, warned = solve(name)
        assert not warned
        assert not is_honestly_reported(name)
        assert problems_of(name), f"{name} 的短板似乎被修好了 —— 请把它移进 HEALTHY 并 pin 指标"

    @pytest.mark.parametrize("name", sorted(LIMITATIONS))
    def test_polygons_stay_wellformed(self, name):
        solver, _warned = solve(name)
        assert_closed_polygons(solver.ribbons, min_vertices=3)
        assert_is_counter_clockwise(solver.ribbons)
