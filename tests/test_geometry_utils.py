"""``manim_lace.interlacing`` 中纯几何工具函数的单元测试。

本模块不依赖 Manim, 因此可以直接导入 ``manim_lace.interlacing`` 以获得更快的
测试速度。
"""

from __future__ import annotations

import networkx
import numpy as np
import pytest

from manim_lace.interlacing import (
    MITER_LIMIT,
    VALIDATE_MODES,
    annulus_polygon,
    clear_paths,
    generate_offset_lines,
    is_cycle,
    is_open_walk,
    longest_chain,
    merge_paths,
    right_handed,
    validate_paths,
    vectorized_intersection,
)
from tests.helpers import (
    crossing_lines,
    lattice_paths,
    polygon_area,
    ring_path,
    ring_with_collinear_seam,
    square_ring,
    square_segments,
    weave_grid_paths,
)
from tests.weave_checks import points_in_polygon


def segment(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """一条两点线段(便于构造退化输入)。"""
    return np.array([[x0, y0], [x1, y1]], dtype=float)


class TestValidatePaths:
    """第 1 步: 输入合法性检查。"""

    @pytest.mark.parametrize(
        ("name", "paths"),
        [
            ("十字交叉", crossing_lines(2.0)),
            ("3x3 编织网格", weave_grid_paths(3)),
            ("4x4 编织网格", weave_grid_paths(4)),
            ("3x3 线阵(端点重合)", lattice_paths(3)),
            ("正方形环", [square_ring(3.0)]),
            ("首尾边共线的环", [ring_with_collinear_seam(3.0)]),
            ("65 边形环", [ring_path(65)]),
        ],
    )
    def test_normal_inputs_pass(self, name, paths):
        assert validate_paths(paths) == [], name

    def test_self_intersection_is_not_a_problem(self):
        # 8 字形路径自交, 但本库大量依赖自交的曲线, 不应被判为退化
        figure_eight = [np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])]
        assert validate_paths(figure_eight) == []

    def test_detects_same_direction_overlap(self):
        issues = validate_paths([segment(0, 0, 2, 0), segment(0.5, 0, 2.5, 0)])
        assert len(issues) == 1
        assert issues[0].startswith("共线重叠")
        assert "相同方向" in issues[0]

    def test_detects_exact_duplicate(self):
        issues = validate_paths([segment(0, 0, 2, 0), segment(0, 0, 2, 0)])
        assert len(issues) == 1
        assert "100%" in issues[0]

    def test_detects_hairpin(self):
        issues = validate_paths([segment(0, 0, 2, 0), segment(2, 0, 0.2, 0)])
        assert len(issues) == 1
        assert "相反方向" in issues[0]

    def test_ignores_collinear_segments_that_do_not_overlap(self):
        assert validate_paths([segment(0, 0, 1, 0), segment(2, 0, 3, 0)]) == []

    def test_ignores_parallel_but_offset_segments(self):
        assert validate_paths([segment(0, 0, 2, 0), segment(0, 0.5, 2, 0.5)]) == []

    def test_detects_three_segments_at_one_point(self):
        issues = validate_paths(
            [segment(-1.5, 0, 1.5, 0), segment(0, 0, 0.8, 1.2), segment(0, 0, -0.8, -1.2)],
        )
        assert len(issues) == 1
        assert issues[0].startswith("多线共点")
        assert "(0, 0)" in issues[0]

    def test_two_segments_at_one_point_is_fine(self):
        # 十字交叉 / 共享端点都是正常的
        assert validate_paths(crossing_lines(2.0)) == []
        assert validate_paths([segment(0, 0, 2, 0), segment(2, 0, 2, 2)]) == []

    def test_reports_the_segment_locations(self):
        issues = validate_paths([segment(0, 0, 2, 0), segment(0.5, 0, 2.5, 0)])
        assert "(路径0, 段0)" in issues[0]
        assert "(路径1, 段0)" in issues[0]

    @pytest.mark.parametrize("paths", [[], [np.array([[0.0, 0.0]])], [segment(0, 0, 1, 0)]])
    def test_degenerate_or_empty_input_passes(self, paths):
        assert validate_paths(paths) == []

    def test_validate_modes_are_exported(self):
        assert VALIDATE_MODES == ("ignore", "warn", "raise")


class TestRightHanded:
    def test_counter_clockwise_triangle(self):
        assert right_handed(np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])) is True

    def test_clockwise_triangle(self):
        assert right_handed(np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0]])) is False

    def test_fewer_than_three_points_is_accepted(self):
        assert right_handed(np.array([[0.0, 0.0]])) is True
        assert right_handed(np.array([[0.0, 0.0], [1.0, 1.0]])) is True

    def test_repeated_closing_point_is_ignored(self):
        assert right_handed(square_ring(2.0)) is True
        assert right_handed(square_ring(2.0, clockwise=True)) is False

    def test_degenerate_polygon_is_not_right_handed(self):
        assert right_handed(np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])) is False

    def test_degenerate_after_removing_the_closing_point(self):
        # 去掉重复的闭合点后只剩两个点, 视为退化并返回 True
        assert right_handed(np.array([[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]])) is True


class TestClearPaths:
    def test_removes_consecutive_duplicates(self):
        cleared = clear_paths([np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]])])
        assert len(cleared) == 1
        np.testing.assert_allclose(cleared[0], [[0.0, 0.0], [1.0, 0.0]])

    def test_removes_collinear_points(self):
        cleared = clear_paths([np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [2.0, 2.0]])])
        np.testing.assert_allclose(cleared[0], [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]])

    def test_drops_degenerate_paths(self):
        assert clear_paths([np.array([[1.0, 1.0]])]) == []
        assert clear_paths([np.array([[1.0, 1.0], [1.0, 1.0]])]) == []

    def test_accepts_plain_python_lists(self):
        cleared = clear_paths([[[0, 0], [1, 1], [2, 0]]])
        assert len(cleared) == 1
        assert cleared[0].dtype == np.float64

    def test_ignores_the_z_coordinate(self):
        cleared = clear_paths([np.array([[0.0, 0.0, 5.0], [1.0, 0.0, 9.0]])])
        assert cleared[0].shape == (2, 2)

    def test_empty_input(self):
        assert clear_paths([]) == []

    def test_removes_wrap_around_collinear_point(self):
        # 缺陷 2 回归: 闭合点处的前后边共线, 冗余顶点必须被删除
        cleared = clear_paths([ring_with_collinear_seam(3.0)])
        assert len(cleared) == 1
        assert len(cleared[0]) == 5
        np.testing.assert_allclose(cleared[0][0], cleared[0][-1])

    def test_keeps_genuine_corners_of_a_closed_ring(self):
        # 正方形四个角都不共线, 不能被误删
        assert len(clear_paths([square_ring(3.0)])[0]) == 5

    def test_drops_fully_degenerate_closed_path(self):
        collinear = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 0.0]])
        assert clear_paths([collinear]) == []

    def test_keeps_a_dense_curve_whose_segments_are_short(self):
        # 共线判据必须尺度无关: 以前比较"叉积的绝对量", 点很密的曲线每一段都被判成共线,
        # 整条曲线会被删到只剩首尾两点(渲染成一条直线)。
        angles = np.linspace(0.0, np.pi / 2.0, 800)
        dense = np.column_stack([np.cos(angles), np.sin(angles)])
        assert len(clear_paths([dense])[0]) == 800

    def test_keeps_every_vertex_of_a_dense_closed_ring(self):
        # 更密时会整条路径被删空(输出空白): 1024 边形环以前返回空列表
        cleared = clear_paths([ring_path(1024, 2.0)])
        assert len(cleared) == 1
        assert len(cleared[0]) == 1025
        np.testing.assert_allclose(cleared[0][0], cleared[0][-1])

    def test_still_drops_exactly_collinear_vertices_inside_a_dense_curve(self):
        # 尺度无关之后, "真正共线"的冗余顶点仍然要被删掉
        angles = np.linspace(0.0, np.pi / 2.0, 400)
        dense = np.column_stack([np.cos(angles), np.sin(angles)])
        with_midpoint = np.insert(dense, 11, (dense[10] + dense[11]) / 2.0, axis=0)
        assert len(clear_paths([with_midpoint])[0]) == len(dense)


class TestAnnulusPolygon:
    def test_area_is_outer_minus_inner(self):
        coords = annulus_polygon(square_ring(2.0), square_ring(4.0))
        assert polygon_area(coords) == pytest.approx(16.0 - 4.0)
        np.testing.assert_allclose(coords[0], coords[-1])

    def test_hollow_center_is_not_filled(self):
        coords = annulus_polygon(square_ring(2.0), square_ring(4.0))
        assert not points_in_polygon(coords, np.array([[1.0, 1.0]]))[0]
        assert points_in_polygon(coords, np.array([[3.0, 1.0]]))[0]

    def test_ring_order_does_not_matter(self):
        inner_first = annulus_polygon(square_ring(2.0), square_ring(4.0))
        outer_first = annulus_polygon(square_ring(4.0), square_ring(2.0))
        assert polygon_area(inner_first) == pytest.approx(polygon_area(outer_first))

    def test_rejects_degenerate_rings(self):
        with pytest.raises(ValueError, match="annulus_polygon"):
            annulus_polygon(np.array([[0.0, 0.0]]), square_ring(2.0))


class TestMergePaths:
    def test_empty_input(self):
        assert merge_paths([]) == []

    def test_rejects_non_positive_atol(self):
        with pytest.raises(ValueError, match="atol"):
            merge_paths([np.array([[0.0, 0.0], [1.0, 0.0]])], atol=0)

    def test_single_open_segment_is_preserved(self):
        merged = merge_paths([np.array([[0.0, 0.0], [1.0, 0.0]])])
        assert len(merged) == 1
        assert merged[0].shape == (2, 2)
        assert {tuple(point) for point in merged[0]} == {(0.0, 0.0), (1.0, 0.0)}

    def test_connected_segments_are_joined(self):
        merged = merge_paths(
            [
                np.array([[0.0, 0.0], [1.0, 0.0]]),
                np.array([[1.0, 0.0], [2.0, 0.0]]),
            ],
        )
        assert len(merged) == 1
        assert merged[0].shape == (3, 2)
        assert {tuple(point) for point in merged[0]} == {(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)}

    def test_disconnected_segments_stay_separate(self):
        merged = merge_paths(
            [
                np.array([[0.0, 0.0], [1.0, 0.0]]),
                np.array([[5.0, 5.0], [6.0, 5.0]]),
            ],
        )
        assert len(merged) == 2
        assert all(path.shape == (2, 2) for path in merged)

    def test_closed_loop_is_normalized(self):
        merged = merge_paths(square_segments())
        assert len(merged) == 1
        loop = merged[0]
        assert loop.shape == (5, 2)
        np.testing.assert_allclose(loop[0], loop[-1])
        assert right_handed(loop) is True

    def test_clockwise_loop_is_flipped(self):
        merged = merge_paths(square_segments(clockwise=True))
        assert len(merged) == 1
        np.testing.assert_allclose(merged[0][0], merged[0][-1])
        assert right_handed(merged[0]) is True

    def test_duplicate_input_points_are_tolerated(self):
        merged = merge_paths([square_ring(2.0)])
        assert len(merged) == 1
        assert merged[0].shape == (5, 2)


class TestLongestChain:
    def test_empty_input(self):
        assert longest_chain([]) == []

    def test_simple_path(self):
        assert longest_chain([(0, 1), (1, 2), (2, 3)]) == [0, 1, 2, 3]

    def test_cycle_has_no_duplicate_start(self):
        chain = longest_chain([(0, 1), (1, 2), (2, 0)])
        assert len(chain) == 3
        assert set(chain) == {0, 1, 2}

    def test_single_edge(self):
        assert longest_chain([(7, 3)]) == [7, 3]


class TestGraphPredicates:
    @staticmethod
    def _graph(edges):
        graph = networkx.Graph()
        graph.add_edges_from(edges)
        return graph

    def test_is_cycle(self):
        graph = self._graph([(0, 1), (1, 2), (2, 0)])
        assert is_cycle(graph, [0, 1, 2]) is True
        assert is_cycle(self._graph([(0, 1), (1, 2)]), [0, 1, 2]) is False

    def test_is_open_walk(self):
        graph = self._graph([(0, 1), (1, 2)])
        assert is_open_walk(graph, [0, 1, 2]) is True
        # 只有两个节点时始终视为开放路径
        assert is_open_walk(graph, [0, 1]) is True

    def test_cycle_is_not_an_open_walk(self):
        graph = self._graph([(0, 1), (1, 2), (2, 0)])
        assert is_open_walk(graph, [0, 1, 2]) is False


class TestGenerateOffsetLines:
    def test_straight_open_path(self):
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
        left, right = generate_offset_lines(coords, 0.5)
        np.testing.assert_allclose(left, [[0.0, 0.5], [1.0, 0.5], [2.0, 0.5]])
        np.testing.assert_allclose(right, [[0.0, -0.5], [1.0, -0.5], [2.0, -0.5]])
        np.testing.assert_allclose((left + right) / 2, coords)

    def test_closed_path_stays_closed(self):
        ring = square_ring(3.0)
        left, right = generate_offset_lines(ring, 0.25)
        assert left.shape == ring.shape
        assert right.shape == ring.shape
        np.testing.assert_allclose(left[0], left[-1])
        np.testing.assert_allclose(right[0], right[-1])

    def test_left_is_inside_and_right_is_outside_for_counter_clockwise(self):
        ring = square_ring(3.0)
        left, right = generate_offset_lines(ring, 0.25)
        assert polygon_area(left) < polygon_area(ring) < polygon_area(right)

    def test_near_reversal_is_finite(self):
        # 接近 180 度的折返: 未做保护时法向量计算会崩掉
        coords = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1e-3]])
        left, right = generate_offset_lines(coords, 0.1)
        assert np.all(np.isfinite(left))
        assert np.all(np.isfinite(right))
        assert np.linalg.norm(left[1] - coords[1]) <= MITER_LIMIT * 0.1 + 1e-9

    def test_miter_spike_is_clamped(self):
        # 尖锐 V 形: 未限制时 miter 长度会远超 offset
        coords = np.array([[1.0, 0.0], [0.0, 0.0], [1.0, 0.2]])
        left, right = generate_offset_lines(coords, 0.1)
        vertex = coords[1]
        assert np.linalg.norm(left[1] - vertex) == pytest.approx(MITER_LIMIT * 0.1)
        assert np.linalg.norm(right[1] - vertex) == pytest.approx(MITER_LIMIT * 0.1)

    def test_zero_length_segment_does_not_produce_nan(self):
        coords = np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]])
        left, right = generate_offset_lines(coords, 0.1)
        assert np.all(np.isfinite(left))
        assert np.all(np.isfinite(right))

    def test_scale_with_offset(self):
        coords = np.array([[0.0, 0.0], [1.0, 0.0]])
        thin_left, _ = generate_offset_lines(coords, 0.1)
        thick_left, _ = generate_offset_lines(coords, 1.0)
        np.testing.assert_allclose(thin_left[0] * 10, thick_left[0])


class TestVectorizedIntersection:
    P1 = np.array([0.0, 0.0])
    P2 = np.array([2.0, 0.0])

    def test_crossing_segment(self):
        points, mask = vectorized_intersection(
            self.P1,
            self.P2,
            np.array([[1.0, -1.0]]),
            np.array([[1.0, 1.0]]),
        )
        assert mask.tolist() == [True]
        np.testing.assert_allclose(points[0], [1.0, 0.0])

    def test_parallel_segments_are_rejected(self):
        _, mask = vectorized_intersection(
            self.P1,
            self.P2,
            np.array([[0.0, 1.0]]),
            np.array([[2.0, 1.0]]),
        )
        assert mask.tolist() == [False]

    def test_non_overlapping_is_rejected(self):
        _, mask = vectorized_intersection(
            self.P1,
            self.P2,
            np.array([[5.0, -1.0]]),
            np.array([[5.0, 1.0]]),
        )
        assert mask.tolist() == [False]

    def test_mixed_candidates(self):
        points, mask = vectorized_intersection(
            self.P1,
            self.P2,
            np.array([[1.0, -1.0], [0.0, 1.0], [1.0, 1.0]]),
            np.array([[1.0, 1.0], [2.0, 1.0], [1.0, -1.0]]),
        )
        assert mask.tolist() == [True, False, True]
        np.testing.assert_allclose(points[0], [1.0, 0.0])
        np.testing.assert_allclose(points[2], [1.0, 0.0])

    def test_empty_candidate_set(self):
        points, mask = vectorized_intersection(
            self.P1,
            self.P2,
            np.empty((0, 2)),
            np.empty((0, 2)),
        )
        assert mask.shape == (0,)
        assert points.shape == (0, 2)
