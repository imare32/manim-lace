"""包级公开接口的测试。"""

from __future__ import annotations

import re

import manim_lace


def test_all_exports_exist():
    assert manim_lace.__all__
    for name in manim_lace.__all__:
        assert hasattr(manim_lace, name), f"{name} 在 __all__ 中声明但未导出"


def test_version_looks_like_a_release():
    assert re.match(r"^\d+\.\d+\.\d+", manim_lace.__version__)


def test_public_api_objects_are_identical_to_module_attributes():
    from manim_lace.interlacing import Interlacing
    from manim_lace.lace import Lace
    from manim_lace.rosette import StarRosette

    assert manim_lace.Lace is Lace
    assert manim_lace.Interlacing is Interlacing
    assert manim_lace.StarRosette is StarRosette


def test_hole_group_methods_are_documented_constants():
    assert set(manim_lace.HOLE_GROUP_METHODS) == {"by_area", "by_distance", "by_hole_index", "by_vertex_count"}


def test_star_type_values():
    assert set(manim_lace.STAR_TYPE_VALUES) == {"PA", "PO", "PR", "CA", "CR"}


def test_top_level_workflow():
    """端到端流程: 生成玫瑰线 → 编织 → 得到可渲染的分组。"""
    from manim import ManimColor, VGroup

    figure = manim_lace.StarRosette(10, 2, "PA")
    lace = manim_lace.Lace(figure, offset=0.1, hole_swatch=["#FF0000", "#00FF00", "#0000FF"])

    assert isinstance(lace, VGroup)
    assert lace.num_holes > 0
    assert lace.num_ribbons > 0
    assert sum(len(holes) for holes in lace.hole_groups.values()) == lace.num_holes
    assert all(ManimColor(hole.get_fill_color()).to_hex() in {"#FF0000", "#00FF00", "#0000FF"} for hole in lace.holes)
