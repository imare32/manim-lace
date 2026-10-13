"""玫瑰线几何生成与 ``StarRosette`` 的测试。"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from manim import Polygram

from manim_lace.interlacing import clear_paths
from manim_lace.rosette import (
    MIN_PETALS,
    STAR_TYPE_VALUES,
    StarRosette,
    cal_kernels,
    get_petals_by_kernel,
    merge_adjacent_petals,
    rosette,
    sort_petals,
    transform_reps,
)


class TestTransformReps:
    def test_single_rep_is_the_identity(self):
        coords = np.array([[1.0, 0.0], [2.0, 1.0]])
        reps = transform_reps(coords)
        assert len(reps) == 1
        np.testing.assert_allclose(reps[0], coords)

    def test_rotation_is_incremental(self):
        coords = np.array([[1.0, 0.0]])
        reps = transform_reps(coords, rotate=np.pi / 2, num=4)
        assert len(reps) == 4
        np.testing.assert_allclose(reps[0], [[1.0, 0.0]], atol=1e-12)
        np.testing.assert_allclose(reps[1], [[0.0, 1.0]], atol=1e-12)
        np.testing.assert_allclose(reps[2], [[-1.0, 0.0]], atol=1e-12)
        np.testing.assert_allclose(reps[3], [[0.0, -1.0]], atol=1e-12)

    def test_scale_is_geometric(self):
        coords = np.array([[1.0, 0.0]])
        reps = transform_reps(coords, scale=0.5, num=3)
        np.testing.assert_allclose([np.linalg.norm(rep[0]) for rep in reps], [1.0, 0.5, 0.25])

    def test_move_is_linear(self):
        coords = np.array([[0.0, 0.0]])
        reps = transform_reps(coords, move=(1.0, 2.0), num=3)
        np.testing.assert_allclose([rep[0] for rep in reps], [[0.0, 0.0], [1.0, 2.0], [2.0, 4.0]])

    def test_original_coordinates_are_not_mutated(self):
        coords = np.array([[1.0, 0.0]])
        before = coords.copy()
        transform_reps(coords, rotate=1.0, scale=2.0, move=(1.0, 1.0), num=3)
        np.testing.assert_allclose(coords, before)

    def test_num_must_be_positive(self):
        with pytest.raises(ValueError, match="num"):
            transform_reps(np.zeros((1, 2)), num=0)


class TestCalKernels:
    @pytest.mark.parametrize("star_type", STAR_TYPE_VALUES)
    @pytest.mark.parametrize("level", [0, 1, 2, 3, 5])
    def test_kernels_are_finite_and_anchored_on_the_x_axis(self, star_type, level):
        kernels = cal_kernels(9, level, star_type)
        assert len(kernels) == max(2, level + 1)
        for index, kernel in enumerate(kernels):
            assert kernel.shape == (2 if index < 2 else 3, 2)
            assert np.all(np.isfinite(kernel))
            assert np.all(kernel[:, 1] >= -1e-12)
            assert kernel[-1, 1] == pytest.approx(0.0, abs=1e-12)

    @pytest.mark.parametrize("index, angle", [(0, 1), (1, 2), (2, 3)])
    def test_first_points_lie_on_the_unit_circle(self, index, angle):
        theta = np.pi / 9
        kernel = cal_kernels(9, 2, "PA")[index]
        np.testing.assert_allclose(kernel[0], [np.cos(angle * theta), np.sin(angle * theta)])

    def test_star_types_produce_distinct_second_kernels(self):
        kernels = {star_type: cal_kernels(9, 2, star_type)[2] for star_type in STAR_TYPE_VALUES}
        # PA / PO / PR 共享起点但末端不同; CA / CR 使用另一套构造
        assert not np.allclose(kernels["PA"], kernels["PO"])
        assert not np.allclose(kernels["PA"], kernels["PR"])
        assert not np.allclose(kernels["PA"], kernels["CA"])
        np.testing.assert_allclose(kernels["CR"][:2], kernels["CA"][:2])

    def test_larger_levels_are_rotations_of_the_previous_kernel(self):
        kernels = cal_kernels(12, 4, "PA")
        theta = np.pi / 12
        c, s = np.cos(theta), np.sin(theta)
        rotation = np.array([[c, -s], [s, c]])
        np.testing.assert_allclose(kernels[3][:1], kernels[2][:1] @ rotation.T, atol=1e-12)

    @pytest.mark.parametrize("bad_n", [0, 1, 2, 3, -3])
    def test_n_too_small(self, bad_n):
        with pytest.raises(ValueError, match="n must be"):
            cal_kernels(bad_n)

    def test_min_petals_is_four(self):
        # n=3 时 xk0 = cosθ + sinθ/tan2θ = 0, 核退化成径向线段, 因此不再支持
        assert MIN_PETALS == 4
        with pytest.raises(ValueError, match="n must be >= 4"):
            cal_kernels(3)

    @pytest.mark.parametrize("bad_n", [3.0, "7", None, True])
    def test_n_must_be_an_integer(self, bad_n):
        with pytest.raises(TypeError, match="n must be an integer"):
            cal_kernels(bad_n)

    def test_level_must_be_non_negative(self):
        with pytest.raises(ValueError, match="level must be"):
            cal_kernels(9, -1)

    @pytest.mark.parametrize("bad_level", [1.5, "2", None])
    def test_level_must_be_an_integer(self, bad_level):
        with pytest.raises(TypeError, match="level must be an integer"):
            cal_kernels(9, bad_level)

    @pytest.mark.parametrize("bad_type", ["", "P", "XA", "CO", "pa"])
    def test_unknown_star_type(self, bad_type):
        with pytest.raises(ValueError, match="star_type"):
            cal_kernels(9, 2, bad_type)


class TestPetals:
    def test_petal_count_and_shape(self):
        kernel = cal_kernels(9, 2, "PA")[2]
        petals = get_petals_by_kernel(kernel, 9)
        assert len(petals) == 9
        for petal in petals:
            assert petal.shape == (2 * len(kernel) - 1, 2)

    def test_petal_is_mirrored_around_the_x_axis(self):
        kernel = cal_kernels(9, 2, "PA")[2]
        petal = get_petals_by_kernel(kernel, 9)[0]
        np.testing.assert_allclose(petal[0], kernel[0] * np.array([1.0, -1.0]))
        np.testing.assert_allclose(petal[-1], kernel[0])
        np.testing.assert_allclose(petal[len(kernel) - 1], kernel[-1])

    def test_petals_are_rotated_copies(self):
        kernel = cal_kernels(9, 2, "PA")[2]
        petals = get_petals_by_kernel(kernel, 9)
        angle = 2 * np.pi / 9
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[c, -s], [s, c]])
        np.testing.assert_allclose(petals[1], petals[0] @ rotation.T, atol=1e-12)

    def test_rosette_helper_matches_the_petal_generator(self):
        kernel = cal_kernels(7, 2, "PA")[2]
        from_helper = rosette(kernel, 7)
        from_generator = get_petals_by_kernel(kernel, 7)
        assert len(from_helper) == len(from_generator) == 7
        for helper_petal, generator_petal in zip(from_helper, from_generator):
            np.testing.assert_allclose(
                clear_paths([helper_petal])[0],
                clear_paths([generator_petal])[0],
            )

    @pytest.mark.parametrize("bad_n", [0, -2])
    def test_n_must_be_positive(self, bad_n):
        kernel = cal_kernels(9, 2, "PA")[2]
        with pytest.raises(ValueError, match="n must be"):
            get_petals_by_kernel(kernel, bad_n)
        with pytest.raises(ValueError, match="n must be"):
            rosette(kernel, bad_n)


class TestSortPetals:
    def test_empty_input(self):
        assert sort_petals([], 2) == []

    def test_result_is_a_permutation(self):
        petals = list(range(10))
        assert sorted(sort_petals(petals, 2)) == petals

    def test_uses_level_plus_one_as_the_step(self):
        assert sort_petals(list(range(10)), 2) == [0, 3, 6, 9, 2, 5, 8, 1, 4, 7]

    def test_splits_into_multiple_cycles(self):
        assert sort_petals(list(range(6)), 1) == [0, 2, 4, 1, 3, 5]

    def test_sorted_petals_can_be_merged_into_chains(self):
        petals = get_petals_by_kernel(cal_kernels(9, 2, "PA")[2], 9)
        merged = merge_adjacent_petals(sort_petals(petals, 2))
        assert 0 < len(merged) < len(petals)


class TestMergeAdjacentPetals:
    def test_empty_input(self):
        assert merge_adjacent_petals([]) == []

    def test_single_polygon_is_untouched(self):
        polygon = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
        merged = merge_adjacent_petals([polygon])
        assert len(merged) == 1
        np.testing.assert_allclose(merged[0], polygon)

    def test_detached_polygons_stay_separate(self):
        polygons = [
            np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]),
            np.array([[5.0, 5.0], [6.0, 5.0], [6.0, 6.0]]),
        ]
        assert len(merge_adjacent_petals(polygons)) == 2

    def test_touching_polygons_are_joined_without_duplicate_point(self):
        first = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
        second = np.array([[1.0, 1.0], [0.0, 1.0], [0.0, 0.0]])
        merged = merge_adjacent_petals([first, second])
        assert len(merged) == 1
        assert merged[0].shape == (4, 2)

    def test_closing_duplicate_point_is_removed(self):
        closed = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]])
        merged = merge_adjacent_petals([closed])
        assert merged[0].shape == (3, 2)


class TestStarRosette:
    def test_basic_properties(self):
        figure = StarRosette(10, 2, "CA", fill_opacity=0.5)
        assert isinstance(figure, Polygram)
        assert (figure.n, figure.level, figure.star_type) == (10, 2, "CA")
        assert figure.get_fill_opacity() == pytest.approx(0.5)

    def test_points_are_finite_and_flat(self):
        anchors = np.array(StarRosette(10, 2).get_anchors())
        assert anchors.ndim == 2
        assert anchors.shape[1] == 3
        assert len(anchors) > 0
        assert np.all(np.isfinite(anchors))
        np.testing.assert_allclose(anchors[:, 2], 0.0)

    def test_repr(self):
        assert "n=9" in repr(StarRosette(9, 2))

    def test_level_zero_is_supported(self):
        assert len(StarRosette(7, 0).get_anchors()) > 0

    @pytest.mark.parametrize("star_type", STAR_TYPE_VALUES)
    @pytest.mark.parametrize(("n", "level"), [(4, 0), (4, 1), (7, 2), (12, 3), (18, 4), (24, 5), (24, 6)])
    def test_all_parameter_combinations_produce_geometry(self, star_type, n, level):
        anchors = np.array(StarRosette(n, level, star_type).get_anchors())
        assert len(anchors) > 0
        assert np.all(np.isfinite(anchors))

    def test_more_petals_produce_more_points(self):
        few = np.array(StarRosette(6, 2).get_anchors())
        many = np.array(StarRosette(18, 2).get_anchors())
        assert len(many) > len(few)

    def test_kwargs_are_forwarded(self):
        figure = StarRosette(12, 2, stroke_width=7, fill_opacity=0.15)
        assert figure.get_stroke_width() == pytest.approx(7.0)
        assert figure.get_fill_opacity() == pytest.approx(0.15)

    def test_is_deterministic(self):
        np.testing.assert_allclose(
            np.array(StarRosette(9, 3).get_anchors()),
            np.array(StarRosette(9, 3).get_anchors()),
        )

    @pytest.mark.parametrize(("n", "level", "star_type"), [(2, 2, "PA"), (9, -1, "PA"), (9, 2, "ZZ")])
    def test_invalid_parameters(self, n, level, star_type):
        with pytest.raises(ValueError):
            StarRosette(n, level, star_type)

    def test_invalid_level_type(self):
        with pytest.raises(TypeError, match="level"):
            StarRosette(9, 1.5)


class TestUnrealizableLevels:
    """高阶骨架由"旋转 + 与 x 轴求交"迭代得到; 旋转后的线段与 x 轴平行时该阶不存在。

    早期实现会在 ``px_x = rx2 - ry2 * (rx3 - rx2) / (ry3 - ry2)`` 处除零, 产出
    ``inf`` / ``nan`` 坐标, 最终图形被缩放成无意义的米字线; 现在改为显式报错。
    """

    @pytest.mark.parametrize(
        ("star_type", "n", "level"),
        [
            ("PA", 6, 4),
            ("PA", 8, 5),
            ("CA", 10, 6),
            ("CR", 6, 5),
            ("PR", 8, 6),
            ("PO", 6, 7),
            ("PO", 4, 2),  # 封闭形式的第 2 阶即退化: tan(2θ) 发散
        ],
    )
    def test_unrealizable_level_raises(self, star_type, n, level):
        with pytest.raises(ValueError, match="not realizable"):
            cal_kernels(n, level, star_type)

    def test_message_names_n_and_star_type(self):
        with pytest.raises(ValueError, match="n=6, star_type='PA'"):
            cal_kernels(6, 4, "PA")

    def test_message_reports_the_largest_usable_level(self):
        with pytest.raises(ValueError, match=r"largest usable level for this \(n, star_type\) is 3"):
            cal_kernels(6, 4, "PA")

    def test_lower_levels_keep_working(self):
        for level in range(4):
            kernels = cal_kernels(6, level, "PA")
            assert np.all(np.isfinite(kernels[level]))

    def test_no_numpy_warning_leaks_out(self):
        # 修复前这里会先抛出 numpy 的 divide-by-zero 警告再产出 1e16 量级坐标
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(ValueError):
                cal_kernels(6, 4, "PA")

    def test_star_rosette_raises_too(self):
        with pytest.raises(ValueError, match="not realizable"):
            StarRosette(6, 4, "PA")

    def test_po_level_two_needs_four_petals(self):
        # PO 的 "O" 尖端在 n=4 时 tan(2θ) 发散, 第 2 阶不可实现, 但 0/1 阶依然可用,
        # 且不会因为"顺手构造第 2 阶"而返回 1e16 量级的坐标
        for level in (0, 1):
            kernels = cal_kernels(4, level, "PO")
            assert len(kernels) == 2
            assert all(np.all(np.isfinite(kernel)) for kernel in kernels)
            assert max(float(np.max(np.abs(kernel))) for kernel in kernels) < 100.0
        with pytest.raises(ValueError, match="not realizable"):
            cal_kernels(4, 2, "PO")

    @pytest.mark.parametrize("star_type", STAR_TYPE_VALUES)
    @pytest.mark.parametrize("n", [4, 6, 8, 10, 12, 16, 20])
    def test_supported_levels_stay_finite_and_bounded(self, n, star_type):
        built = 0
        for level in range(13):
            try:
                kernels = cal_kernels(n, level, star_type)
            except ValueError:
                break
            built += 1
            for kernel in kernels:
                assert np.all(np.isfinite(kernel))
                assert float(np.max(np.abs(kernel))) < 100.0
        assert built >= 1

    @pytest.mark.parametrize("star_type", STAR_TYPE_VALUES)
    def test_even_n_has_a_finite_level_budget(self, star_type):
        # 偶数 n 的迭代必然在若干阶后撞上"与 x 轴平行", 因此可行阶数有限
        levels = []
        for level in range(40):
            try:
                cal_kernels(12, level, star_type)
            except ValueError:
                break
            levels.append(level)
        assert levels
        assert levels[-1] < 39
