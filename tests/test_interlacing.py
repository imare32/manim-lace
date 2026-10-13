"""``Interlacing`` 求解器的行为测试。

覆盖空输入、参数校验、路径预处理、交点计算、孔洞与丝带提取等核心流程。
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pytest

from manim_lace.interlacing import Interlacing, right_handed
from tests.helpers import (
    assert_closed_polygons,
    assert_is_counter_clockwise,
    crossing_lines,
    lattice_paths,
    polygon_area,
    ring_path,
    ring_with_collinear_seam,
    square_ring,
    weave_grid_paths,
)
from tests.weave_checks import points_in_polygon, top_ribbon


class TestEmptyInput:
    def test_no_paths(self):
        solver = Interlacing([], 0.1)
        assert solver.is_empty is True
        assert solver.paths == []
        assert solver.holes == []
        assert solver.ribbons == []
        assert solver.overlaps == []
        assert solver.d_segments == {}
        assert solver.d_intersections == {}
        assert solver.d_seg_intersects == {}

    def test_degenerate_paths_are_dropped(self):
        assert Interlacing([np.array([[0.0, 0.0]])], 0.1).is_empty is True
        assert Interlacing([np.array([[2.0, 2.0], [2.0, 2.0]])], 0.1).is_empty is True

    def test_repr_reports_state(self):
        text = repr(Interlacing([], 0.1))
        assert "paths=0" in text
        assert "holes=0" in text

    @pytest.mark.parametrize("offset", [0, -0.5, float("nan"), float("inf"), float("-inf")])
    def test_invalid_offset(self, offset):
        with pytest.raises(ValueError, match="offset"):
            Interlacing([square_ring()], offset)


class TestPathPreparation:
    def test_open_paths_have_alternating_flags(self):
        paths = [np.array([[0.0, y], [1.0, y]]) for y in (0.0, 1.0, 2.0)]
        solver = Interlacing(paths, 0.1)
        assert solver.paths_closed == [False, False, False]
        assert solver.paths_flag == [True, False, True]

    def test_closed_path_flag_is_always_true(self):
        # 路径会按起点坐标排序: 两条开放线(x=-1)在前, 闭合正方形(x=0)在后
        paths = [
            square_ring(2.0),
            np.array([[-1.0, 5.0], [1.0, 5.0]]),
            np.array([[-1.0, 6.0], [1.0, 6.0]]),
        ]
        solver = Interlacing(paths, 0.1)
        assert solver.paths_closed == [False, False, True]
        assert solver.paths_flag == [True, False, True]

    def test_closing_point_is_normalized(self):
        ring = square_ring(3.0)
        ring[-1] += 5e-7  # 容差之内的误差, 应被识别为闭合路径并抹平
        solver = Interlacing([ring], 0.1)
        assert solver.paths_closed == [True]
        np.testing.assert_allclose(solver.paths[0][0], solver.paths[0][-1], atol=1e-15)

    def test_offsets_match_path_count(self):
        solver = Interlacing(lattice_paths(3), 0.1)
        assert len(solver.paths) == len(solver.paths_l) == len(solver.paths_r) > 0

    def test_segments_cover_all_three_tracks(self):
        solver = Interlacing([np.array([[0.0, 0.0], [1.0, 0.0]])], 0.1)
        assert sorted(solver.d_segments) == [(0, 0, 0), (0, 1, 0), (0, 2, 0)]

    def test_segment_count_grows_with_path_length(self):
        solver = Interlacing([square_ring(3.0)], 0.1)
        # 4 条边 × 3 条轨道
        assert len(solver.d_segments) == 12


class TestIntersections:
    def test_crossing_lines_produce_intersections(self):
        solver = Interlacing(crossing_lines(), 0.1)
        assert solver.d_intersections

    def test_midlines_are_excluded_from_intersection_search(self):
        solver = Interlacing(weave_grid_paths(3), 0.1)
        for key in solver.d_intersections:
            for seg_id in key:
                if isinstance(seg_id, tuple):
                    assert seg_id[1] in (1, 2), "中线(type=0) 不应参与求交"

    def test_intersections_are_sorted_by_distance_from_segment_start(self):
        solver = Interlacing(weave_grid_paths(4), 0.1)
        assert solver.d_seg_intersects
        for seg_id, tgt_ids in solver.d_seg_intersects.items():
            start = solver.d_segments[seg_id][0]
            dists = [float(np.linalg.norm(solver.d_intersections[frozenset((seg_id, tgt))] - start)) for tgt in tgt_ids]
            assert dists == sorted(dists), f"{seg_id} 上的交点未按距离排序"

    def test_intersections_are_symmetric(self):
        solver = Interlacing(crossing_lines(), 0.1)
        for seg_id, tgt_ids in solver.d_seg_intersects.items():
            for tgt in tgt_ids:
                if isinstance(tgt, tuple):
                    assert seg_id in solver.d_seg_intersects[tgt]

    def test_multi_segment_intersection_warns(self):
        solver = Interlacing([np.array([[0.0, 0.0], [1.0, 0.0]])], 0.1)
        # 手工注入三条共点的偏移线段(水平、垂直、45 度), 触发多线共点告警
        solver.d_segments = {
            (0, 1, 0): (np.array([-1.0, 0.0]), np.array([1.0, 0.0])),
            (1, 1, 0): (np.array([0.0, -1.0]), np.array([0.0, 1.0])),
            (2, 1, 0): (np.array([-1.0, -1.0]), np.array([1.0, 1.0])),
        }
        solver.d_intersections.clear()
        solver.d_seg_intersects = defaultdict(list)

        with pytest.warns(UserWarning, match="Multi-segment intersection"):
            solver._cal_intersections()

        assert len(solver.d_intersections) == 3


class TestHolesAndRibbons:
    def test_crossing_lines_produce_holes_and_ribbons(self):
        solver = Interlacing(crossing_lines(2.0), 0.2)
        assert len(solver.holes) >= 3
        assert len(solver.ribbons) >= 1
        assert_closed_polygons(solver.holes, min_vertices=3)
        assert_closed_polygons(solver.ribbons, min_vertices=3)

    def test_closed_square_produces_a_single_hole(self):
        solver = Interlacing([square_ring(3.0)], 0.2)
        assert len(solver.holes) == 1
        assert_closed_polygons(solver.holes, min_vertices=3)

    def test_polygons_are_counter_clockwise(self):
        solver = Interlacing(weave_grid_paths(4), 0.1)
        assert_is_counter_clockwise(solver.holes)
        assert_is_counter_clockwise(solver.ribbons)

    @pytest.mark.parametrize("n", [3, 4, 5])
    def test_weave_grid_yields_a_complete_lattice_of_holes(self, n):
        solver = Interlacing(weave_grid_paths(n), 0.1)
        assert len(solver.holes) == (n + 1) ** 2
        assert len(solver.ribbons) == len(solver.holes) - 1
        assert_closed_polygons(solver.holes, min_vertices=3)

    def test_lattice_with_asymmetric_offset_intersections(self):
        # 回归: 外环的内侧偏移线与十字线相交、外侧不相交, 同一线段左右交点数不等,
        # 旧实现会在 _set_ribbons 中抛出 IndexError。
        solver = Interlacing(lattice_paths(3), 0.1)
        assert len(solver.paths) == 3
        assert_closed_polygons(solver.ribbons, min_vertices=3)

    def test_results_are_deterministic(self):
        first = Interlacing(weave_grid_paths(4), 0.1)
        second = Interlacing(weave_grid_paths(4), 0.1)
        assert len(first.holes) == len(second.holes)
        assert len(first.ribbons) == len(second.ribbons)
        for left, right in zip(first.holes, second.holes):
            np.testing.assert_allclose(left, right)
        for left, right in zip(first.ribbons, second.ribbons):
            np.testing.assert_allclose(left, right)

    def test_ribbon_count_is_stable_when_paths_are_reordered(self):
        paths = weave_grid_paths(3)
        shuffled = [paths[i] for i in (3, 1, 5, 0, 4, 2)]
        assert len(Interlacing(paths, 0.1).holes) == len(Interlacing(shuffled, 0.1).holes)


class TestSimpleClosedRibbon:
    """缺陷 1 回归: 无自交点的闭合路径必须产出环形丝带, 而不是实心团块。"""

    def test_closed_ring_produces_a_single_annulus(self):
        solver = Interlacing([square_ring(3.0)], 0.2)
        assert len(solver.holes) == 1
        assert len(solver.ribbons) == 1

    def test_annulus_area_is_the_ribbon_band(self):
        # 外环 3.4² - 内环 2.6² = 4.8
        ribbon = Interlacing([square_ring(3.0)], 0.2).ribbons[0]
        assert polygon_area(ribbon) == pytest.approx(4.8)

    def test_hole_stays_visible_under_the_ribbon(self):
        solver = Interlacing([square_ring(3.0)], 0.2)
        hole_center = solver.holes[0][:-1].mean(axis=0)
        assert top_ribbon(solver.ribbons, hole_center) is None
        # 环形带上仍然有丝带
        assert np.any(points_in_polygon(solver.ribbons[0], np.array([[1.5, -0.1]])))

    @pytest.mark.parametrize("sides", [17, 32, 65])
    def test_polygonal_ring_is_not_a_solid_disc(self, sides):
        solver = Interlacing([ring_path(sides)], 0.2)
        assert len(solver.holes) == 1
        assert len(solver.ribbons) == 1
        assert np.any(points_in_polygon(solver.ribbons[0], np.array([[0.0, 2.0]])))

    def test_ring_with_collinear_seam_is_not_empty(self):
        # 缺陷 2 回归: 首尾边共线的闭合路径曾整体空输出
        solver = Interlacing([ring_with_collinear_seam(3.0)], 0.2)
        assert len(solver.holes) == 1
        assert len(solver.ribbons) == 1


class TestRailAlignment:
    """缺陷 3 回归: 左右偏移线的交点必须按交叉事件配对, 而不是按排序后的索引。"""

    def test_group_crossings_pairs_the_two_rails_of_one_crossing(self):
        groups = Interlacing._group_crossings([(1, 1, 0), (1, 2, 0), (2, 1, 3), (3, 1, 1)])
        assert groups == [((1, 1, 0), (1, 2, 0)), ((2, 1, 3), None), ((3, 1, 1), None)]

    def test_group_crossings_rejects_same_track_pair(self):
        # 同一侧的两条偏移线不算一次交叉
        assert Interlacing._group_crossings([(1, 1, 0), (1, 1, 1)]) == [((1, 1, 0), None), ((1, 1, 1), None)]

    def test_align_rail_events_restores_a_missing_crossing(self):
        solver = Interlacing(weave_grid_paths(3), 0.1)
        seg_a, seg_b = (0, 1, 0), (0, 2, 0)
        partner, missing = (3, 1, 0), (3, 2, 0)

        # 模拟"右侧轨道登记了交点、左侧漏登记"的情形(近失 / 共线端点)
        solver.d_seg_intersects[seg_a] = [tgt for tgt in solver.d_seg_intersects[seg_a] if tgt != missing]
        solver.d_seg_intersects[missing].remove(seg_a)
        del solver.d_intersections[frozenset((seg_a, missing))]

        solver._align_rail_events(solver.d_seg_intersects[seg_a], solver.d_seg_intersects[seg_b], seg_a, seg_b)
        aligned = solver.d_seg_intersects[seg_a]
        assert missing in aligned
        assert aligned.index(missing) == aligned.index(partner) + 1


class TestValidatePolicy:
    """第 1 步: ``Interlacing(validate=...)`` 对退化输入的三种处理方式。"""

    @staticmethod
    def degenerate_paths() -> list[np.ndarray]:
        return [np.array([[0.0, 0.0], [2.0, 0.0]]), np.array([[0.5, 0.0], [2.5, 0.0]])]

    def test_normal_input_has_no_issues(self):
        solver = Interlacing(weave_grid_paths(3), 0.1)
        assert solver.path_issues == []

    def test_warn_mode_is_the_default(self):
        with pytest.warns(UserWarning, match="退化输入"):
            solver = Interlacing(self.degenerate_paths(), 0.2)
        assert len(solver.path_issues) == 1
        assert solver.ribbons  # 仍然继续求解

    def test_raise_mode_rejects_the_input(self):
        with pytest.raises(ValueError, match="退化输入"):
            Interlacing(self.degenerate_paths(), 0.2, validate="raise")

    def test_ignore_mode_skips_the_check(self):
        solver = Interlacing(self.degenerate_paths(), 0.2, validate="ignore")
        assert solver.path_issues == []

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="validate"):
            Interlacing([], 0.1, validate="strict")


class TestRailContract:
    """第 2 步: 派生几何自检 + 降级渲染。

    输入: ``lattice_paths(3)`` 是已知会让"同一线段左右偏移线交点数不等"的回归输入
    (外环内侧与竖线相交、外侧不相交)。
    """

    def test_clean_input_has_no_rail_issues(self):
        assert Interlacing(weave_grid_paths(3), 0.1).rail_issues == []

    def test_contract_break_is_reported(self):
        with pytest.warns(UserWarning, match="配对契约"):
            solver = Interlacing(lattice_paths(3), 0.1)
        assert len(solver.rail_issues) == 1
        assert "交点数不等" in solver.rail_issues[0]
        assert solver.rail_issues[0].startswith("路径 0: 4/4")

    def test_only_affected_paths_degrade(self):
        with pytest.warns(UserWarning):
            solver = Interlacing(lattice_paths(3), 0.1)
        # 1 条降级整带 + 其余两条路径的编织片段
        assert len(solver.rail_issues) == 1
        assert len(solver.ribbons) == 5
        assert_closed_polygons(solver.ribbons, min_vertices=3)

    def test_degraded_band_is_counter_clockwise(self):
        with pytest.warns(UserWarning):
            solver = Interlacing(lattice_paths(3), 0.1)
        assert_is_counter_clockwise(solver.ribbons)

    def test_input_level_degeneracy_is_separate(self):
        # 共线重叠属于输入退化(第 1 步), 由 validate 负责报, 不在派生几何自检范围内
        with pytest.warns(UserWarning, match="退化输入"):
            solver = Interlacing(
                [np.array([[0.0, 0.0], [2.0, 0.0]]), np.array([[0.5, 0.0], [2.5, 0.0]])],
                0.2,
            )
        assert solver.rail_issues == []


class TestOverlaps:
    def test_overlaps_are_opt_in(self):
        assert Interlacing(weave_grid_paths(4), 0.1).overlaps == []

    def test_overlaps_are_quads(self):
        solver = Interlacing(weave_grid_paths(4), 0.1, compute_overlaps=True)
        assert len(solver.overlaps) == 9
        assert_closed_polygons(solver.overlaps, min_vertices=4)

    def test_overlaps_do_not_change_holes_or_ribbons(self):
        plain = Interlacing(weave_grid_paths(4), 0.1)
        with_overlaps = Interlacing(weave_grid_paths(4), 0.1, compute_overlaps=True)
        assert len(plain.holes) == len(with_overlaps.holes)
        assert len(plain.ribbons) == len(with_overlaps.ribbons)

    def test_overlaps_are_counter_clockwise(self):
        solver = Interlacing(weave_grid_paths(3), 0.1, compute_overlaps=True)
        assert solver.overlaps
        for overlap in solver.overlaps:
            assert right_handed(overlap) is True
