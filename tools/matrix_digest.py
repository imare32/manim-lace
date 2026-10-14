"""全矩阵指纹: 对一批固定配置输出求解结果的 md5, 用于证明"改动对既有配置零影响"。

`tools/ab_render.py` 只能证明**示例场景**逐字节不变; 覆盖不到的角落(极端阶、稠密曲线、
退化组合)由本工具兜底: 改动前后各跑一次, 逐行 diff, 就能说清"哪些配置的输出变了、变成
什么样"(而不是只知道自己没弄坏那几个样板)。

覆盖: 5 种花型 × n=5~20 × 各阶 × 两种丝带宽度(0.015 / 0.05 × `r_max`) + `Circle` /
`Square` / 两档采样的利萨如曲线。

用法::

    uv run python tools/matrix_digest.py media/_review/digest_before.txt   # 改动前
    uv run python tools/matrix_digest.py media/_review/digest_after.txt    # 改动后
    # 逐行 diff 两个文件即可(行内是 "配置 h= r= deg= issues= md5")

说明: 玫瑰线 (`manim_lace.rosette`) 是**可选模块**, 本工具在它缺失时自动跳过那一部分,
只跑曲线/闭合图形那几行。
"""

from __future__ import annotations

import hashlib
import sys
import warnings
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from manim import TAU, Circle, ParametricFunction, Square  # noqa: E402

from manim_lace.interlacing import Interlacing  # noqa: E402
from manim_lace.lace import mobject_paths  # noqa: E402

#: 花型与 n 的范围(level 从 1 起, 直到该 (花型, n) 数学上不存在为止)。
FAMILIES = ("PA", "CA", "PR", "CR", "PO")
N_RANGE = range(5, 21)
MAX_LEVEL = 8
#: 丝带半宽按整体最大半径的比例给: 0.015 是测试口径, 0.05 与验收脚本一致。
OFFSET_FACTORS = (0.015, 0.05)


def digest(inter: Interlacing) -> str:
    """把孔洞 / 丝带片段 / 降级情况的全部坐标揉成一个短十六进制指纹。"""
    hasher = hashlib.md5()
    for group in (inter.holes, inter.ribbons):
        hasher.update(str(len(group)).encode())
        for polygon in group:
            hasher.update(np.asarray(polygon, dtype=float).round(9).tobytes())
    hasher.update(str(sorted(inter._degraded_paths)).encode())
    hasher.update(str(inter.rail_issues).encode())
    return hasher.hexdigest()[:12]


def line_for(tag: str, paths, offset: float) -> str:
    """求解并格式化一行; 求解抛异常时把异常写进这一行(它同样是"输出", 必须能对比)。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            inter = Interlacing(paths, offset, validate="ignore")
    except Exception as exc:  # noqa: BLE001 - 任何异常都当作"该配置的输出"
        return f"{tag:28s} ERROR {type(exc).__name__}: {exc}"
    return (
        f"{tag:28s} h={len(inter.holes):4d} r={len(inter.ribbons):4d} "
        f"deg={len(inter._degraded_paths):2d} issues={len(inter.rail_issues):2d} {digest(inter)}"
    )


def rosette_lines() -> list[str]:
    """玫瑰线矩阵(可选模块缺失时返回空列表)。"""
    try:
        from manim_lace.rosette import StarRosette
    except ImportError:  # pragma: no cover - 可选模块
        return []

    lines: list[str] = []
    for family in FAMILIES:
        for n in N_RANGE:
            for level in range(1, MAX_LEVEL + 1):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        rosette = StarRosette(n, level, family)
                except (ValueError, TypeError):
                    break  # 该阶在数学上不存在(或参数非法), 后面的阶同样不存在
                paths = [
                    np.asarray(subpath, dtype=float)[:, :2]
                    for member in rosette.family_members_with_points()
                    for subpath in member.get_subpaths()
                ]
                if not paths:
                    continue
                r_max = max(float(np.linalg.norm(path, axis=1).max()) for path in paths)
                for factor in OFFSET_FACTORS:
                    lines.append(line_for(f"{family} n={n} L={level} ({factor}R)", paths, factor * r_max))
    return lines


def curve_lines() -> list[str]:
    """非玫瑰线的固定输入: 简单闭合图形 + 两档采样密度的自交曲线。"""
    lissajous = lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0])  # noqa: E731
    cases = [
        ("Circle r=2", Circle(radius=2), 0.1),
        ("Square 3", Square(3), 0.1),
        ("利萨如 dt=0.05", ParametricFunction(lissajous, t_range=(0, TAU, 0.05)), 0.1),
        ("利萨如 dt=0.02", ParametricFunction(lissajous, t_range=(0, TAU, 0.02)), 0.1),
    ]
    return [line_for(tag, mobject_paths(mobj), offset) for tag, mobj, offset in cases]


def main() -> int:
    lines = [*rosette_lines(), *curve_lines()]
    text = "\n".join(lines)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8")
        print(f"\nwrote {sys.argv[1]} ({len(lines)} 行)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
