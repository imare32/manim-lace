"""包级公开接口的测试。"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

import manim_lace

#: 可选模块 `manim_lace.rosette` 的公开名(拆走时连同 `__all__` 里这几项一起删)。
ROSETTE_EXPORTS = ("STAR_TYPE", "STAR_TYPE_VALUES", "StarRosette", "cal_kernels")


def test_all_exports_exist():
    assert manim_lace.__all__
    has_rosette = importlib.util.find_spec("manim_lace.rosette") is not None
    for name in manim_lace.__all__:
        if name in ROSETTE_EXPORTS and not has_rosette:
            continue
        assert hasattr(manim_lace, name), f"{name} 在 __all__ 中声明但未导出"


def test_importing_the_package_does_not_load_the_optional_rosette():
    """``import manim_lace`` 不应把可选模块 `manim_lace.rosette` 拉进内存。

    玫瑰线只依赖 numpy 与 manim, 与核心的"任意路径 → 编织丝带"无关; 惰性转发(PEP 562)保证
    将来把它拆成独立包时, 核心不需要改任何别的代码。用子进程测, 避免同一次会话里别的用例
    已经导入过它。
    """
    result = subprocess.run(
        [sys.executable, "-c", "import manim_lace, sys; print('manim_lace.rosette' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.stdout.strip() == "False"
    # 但按名字取用仍然可用(惰性加载)
    assert manim_lace.StarRosette is not None


def test_version_looks_like_a_release():
    assert re.match(r"^\d+\.\d+\.\d+", manim_lace.__version__)


def test_public_api_objects_are_identical_to_module_attributes():
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    from manim_lace.interlacing import Interlacing
    from manim_lace.lace import Lace
    from manim_lace.rosette import StarRosette

    assert manim_lace.Lace is Lace
    assert manim_lace.Interlacing is Interlacing
    assert manim_lace.StarRosette is StarRosette


def test_hole_group_methods_are_documented_constants():
    assert set(manim_lace.HOLE_GROUP_METHODS) == {"by_area", "by_distance", "by_hole_index", "by_vertex_count"}


def test_star_type_values():
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    assert set(manim_lace.STAR_TYPE_VALUES) == {"PA", "PO", "PR", "CA", "CR"}


def test_top_level_workflow():
    """端到端流程: 生成玫瑰线 → 编织 → 得到可渲染的分组。"""
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    from manim import ManimColor, VGroup

    figure = manim_lace.StarRosette(10, 2, "PA")
    lace = manim_lace.Lace(figure, offset=0.1, hole_swatch=["#FF0000", "#00FF00", "#0000FF"])

    assert isinstance(lace, VGroup)
    assert lace.num_holes > 0
    assert lace.num_ribbons > 0
    assert sum(len(holes) for holes in lace.hole_groups.values()) == lace.num_holes
    assert all(ManimColor(hole.get_fill_color()).to_hex() in {"#FF0000", "#00FF00", "#0000FF"} for hole in lace.holes)
