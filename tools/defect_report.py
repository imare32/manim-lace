"""缺陷对照报告: 为 `DEFECTS.md` 里的每条缺陷生成"修复前 / 修复后"渲染图, 汇总成一个网页。

做法: 每个用例都在**指定的历史源码树**里渲一遍(修复前), 再用当前工作区渲一遍(修复后) —— 两边
驱动同一段场景代码、同一套配色, 于是图的差异就是源码的差异。历史树由 `git archive` 取:

    v020      = 795a5bb (Release v0.2.0)      -> 缺陷 1/2/5 的"修复前"
    prestep3  = 7ede551 (tag pre-step3)       -> 缺陷 3/4/8 的"修复前"
    head      = ea1fea3 (本次改动前的 HEAD)    -> 缺陷 9/10 的"修复前"

"修复前"基线是按**实测**挑的(见 `media/_review/case_baseline_matrix.py`): 每个用例都验证过在该
树下确实表现出缺陷、在修复后确实变了, 避免拿一张"其实一样"的图充数。

部分用例还给出"中间态"(monkeypatch), 用来解释**为什么修复必须配套**:

    tolerance-only  只修端点容差、不加退化判据  -> 诚实降级会变成"静默画错"(已否决)
    no-guard        去掉重归属护栏(缺陷 6 修复前)-> 复现它要挡住的 KeyError

缺陷 7 是校验器误报, 不体现在画面上, 因此它的对照是**判定结果**(同一批配置在两棵树自带的
`tests/weave_checks.py` 下的失败条目数)。

用法::

    uv run python tools/defect_report.py                 # 渲染 + 生成 media/defect_report/index.html
    uv run python tools/defect_report.py --only d9-pa7l7 # 只渲这几个用例(调试)
    uv run python tools/defect_report.py --no-render     # 复用已有图片, 只重写网页
    uv run python tools/defect_report.py --force         # 已有图片也重渲
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TREE_DIR = REPO_ROOT / "media" / "_review" / "trees"
DEFAULT_OUT = REPO_ROOT / "media" / "defect_report"

#: 历史基线: 名称 -> (git ref, 人类可读说明)
BASELINES = {
    "v020": ("795a5bb", "Release v0.2.0"),
    "prestep3": ("7ede551", "tag pre-step3"),
    "head": ("ea1fea3", "本次改动前的 HEAD"),
}
CURRENT = "current"


# --------------------------------------------------------------------------------------
# 用例定义(父子进程共用; 必须自包含, 因为子进程要拿它去驱动另一棵源码树)
# --------------------------------------------------------------------------------------
@dataclass
class Case:
    """一个对照用例: 一段场景 + 丝带宽度 + "修复前"用哪棵源码树(可带 monkeypatch)。"""

    key: str
    title: str
    defects: tuple[str, ...]
    note: str
    before: tuple[str, str]  # (源码树, variant)
    build: object  # () -> (mobject, offset)
    intermediate: tuple[str, str] | None = None


def _rosette(family: str, n: int, level: int, factor: float):
    import numpy as np

    from manim_lace import StarRosette

    star = StarRosette(n, level, family)
    r_max = float(np.linalg.norm(star.get_all_points()[:, :2], axis=1).max())
    return star, factor * r_max


def _lissajous(step: float, offset: float = 0.05):
    import numpy as np
    from manim import TAU, ParametricFunction

    return (
        ParametricFunction(
            lambda t: np.array([np.sin(2 * t), np.sin(3 * t), 0.0]),
            t_range=(0, TAU, step),
            use_smoothing=False,
        ),
        offset,
    )


def _polygon(sides: int, radius: float = 2.0, offset: float = 0.05):
    import numpy as np
    from manim import Polygon

    angles = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    return Polygon(*[[radius * np.cos(a), radius * np.sin(a), 0.0] for a in angles]), offset


def _two_rings(offset: float = 0.015 * 2.3):
    from manim import LEFT, RIGHT, Circle, VGroup

    return VGroup(Circle(1.5).shift(LEFT * 0.8), Circle(1.5).shift(RIGHT * 0.8)), offset


def _square(size: float = 3.0, offset: float = 0.2):
    from manim import Square

    return Square(size), offset


def _hexagon(radius: float = 2.0, offset: float = 0.2):
    from manim import RegularPolygon

    return RegularPolygon(6, radius=radius), offset


def _circle(radius: float = 2.0, offset: float = 0.2):
    from manim import Circle

    return Circle(radius=radius), offset


ROSETTE = lambda family, n, level, factor: lambda: _rosette(family, n, level, factor)  # noqa: E731

CASES: tuple[Case, ...] = (
    Case(
        "d1-square",
        "缺陷 1 · 无自交闭合路径渲染成实心团块",
        ("1",),
        "正方形环 @ offset=0.2",
        ("v020", ""),
        _square,
    ),
    Case("d1-hexagon", "缺陷 1 · 同上(正六边形环)", ("1",), "正六边形环 @ 0.2", ("v020", ""), _hexagon),
    Case(
        "d2-circle",
        "缺陷 2 · `Lace(Circle)` 输出完全空白",
        ("2",),
        "Circle(2) @ 0.2(文档示例)",
        ("v020", ""),
        _circle,
    ),
    Case(
        "d3-circles",
        "缺陷 3a / 4 · 两圆相交不编织(上下压相位不自洽)",
        ("3", "4"),
        "两个圆(半径 1.5, 圆心相距 1.6)",
        ("prestep3", ""),
        _two_rings,
    ),
    Case(
        "d3-ca16l4",
        "缺陷 3b · CA 族逐段归属错位(已修)",
        ("3",),
        "StarRosette(16, 4, CA) @ 0.015·r_max",
        ("prestep3", ""),
        ROSETTE("CA", 16, 4, 0.015),
    ),
    Case(
        "d3-po5l2",
        "缺陷 3c · PO 族 miter 截断(未修: 两态都是诚实降级)",
        ("3",),
        "StarRosette(5, 2, PO) @ 0.05·r_max —— 左右'自交事件'数不等(140 vs 120), 属接头几何退化",
        ("prestep3", ""),
        ROSETTE("PO", 5, 2, 0.05),
    ),
    Case(
        "d5-dense-curve",
        "缺陷 5 · 点数密的曲线被静默删点 / 塌成直线",
        ("5",),
        "利萨如曲线 dt=0.01",
        ("v020", ""),
        lambda: _lissajous(0.01),
    ),
    Case(
        "d6-selfcross",
        "缺陷 6 · 自交事件重归属时 `KeyError`",
        ("6",),
        "利萨如曲线 dt=0.01: 去掉护栏即复现崩溃",
        ("head", "no-guard"),
        lambda: _lissajous(0.01),
    ),
    Case(
        "d8-dense-polyline",
        "缺陷 8 · 稠密折线的角点事件丢失(输出空白)",
        ("8",),
        "1024 边形环",
        ("prestep3", ""),
        lambda: _polygon(1024),
    ),
    Case(
        "d9-pa7l7",
        "缺陷 9 · 求解崩溃 · PA n=7 L7",
        ("9",),
        "StarRosette(7, 7, PA) @ 0.05·r_max —— 修好后出图但仍诚实降级(该配置属极端阶)",
        ("head", ""),
        ROSETTE("PA", 7, 7, 0.05),
    ),
    Case(
        "d9-cr19l4",
        "缺陷 9 · 求解崩溃 · CR n=19 L4",
        ("9",),
        "StarRosette(19, 4, CR) @ 0.05·r_max —— 修好后仍诚实降级",
        ("head", ""),
        ROSETTE("CR", 19, 4, 0.05),
    ),
    Case(
        "d9-ca12l6",
        "缺陷 9 · 求解崩溃 · CA n=12 L6(修好后能织出 164 条丝带, 但该阶本身仍有残差)",
        ("9",),
        "StarRosette(12, 6, CA) @ 0.05·r_max",
        ("head", ""),
        ROSETTE("CA", 12, 6, 0.05),
    ),
    Case(
        "d10-cr10l3",
        "缺陷 3c / 10 · 拐点交叉: 数据层面修好, 画面仍是诚实降级",
        ("3", "10"),
        "StarRosette(10, 3, CR) @ 0.05·r_max(中间态 = 只修容差、不加判据)",
        ("head", ""),
        ROSETTE("CR", 10, 3, 0.05),
        intermediate=(CURRENT, "tolerance-only"),
    ),
    Case(
        "d10-pa16l2",
        "缺陷 10 · 静默画错 → 诚实降级(PA n=16 L2)",
        ("10",),
        "StarRosette(16, 2, PA) @ 0.05·r_max",
        ("head", ""),
        ROSETTE("PA", 16, 2, 0.05),
    ),
)

#: 缺陷 7(校验器误报)是"判定口径"缺陷: 用同一批配置在**两棵树自带**的校验器下的结果对照。
VERDICT_CASES = (
    ("PA n=12 L2", "PA", 12, 2, 0.015),
    ("PA n=10 L3", "PA", 10, 3, 0.015),
    ("CA n=12 L4", "CA", 12, 4, 0.015),
    ("CA n=16 L4", "CA", 16, 4, 0.015),
    ("PA n=8 L4", "PA", 8, 4, 0.015),
    ("CR n=10 L3(真实损坏)", "CR", 10, 3, 0.05),
)


def tree_root(name: str) -> str:
    if name == CURRENT:
        return "."
    return str(TREE_DIR / name)


def tree_label(name: str) -> str:
    if name == CURRENT:
        return "当前工作区"
    ref, desc = BASELINES[name]
    return f"{ref} ({desc})"


# --------------------------------------------------------------------------------------
# 子进程: 在指定源码树里渲染一个用例 / 跑一次判定
# --------------------------------------------------------------------------------------
def child_render(root: str, case_key: str, variant: str, out_png: str) -> int:
    root_path = str(Path(root).resolve())
    sys.path.insert(0, root_path)
    case = next(c for c in CASES if c.key == case_key)

    from manim import BLACK, BLUE, GRAY_B, GREEN, RED, WHITE, Scene, tempconfig

    import manim_lace
    from manim_lace import Lace

    if variant == "tolerance-only":
        import manim_lace.interlacing as il

        il.Interlacing._has_joint_crossing = lambda self, i: False  # type: ignore[assignment]
    elif variant == "no-guard":
        import manim_lace.interlacing as il

        il.Interlacing._reservation_is_consistent = lambda self, i, left, right: True  # type: ignore[assignment]

    module_file = str(Path(getattr(manim_lace, "__file__", "")).resolve())
    info: dict = {
        "case": case_key,
        "root": root_path,
        "variant": variant,
        "manim_lace": module_file,
        "version": str(getattr(manim_lace, "__version__", "?")),
    }
    if not module_file.startswith(root_path):
        # 防呆: 请求的是某棵历史源码树, 却导入了别处的包 —— 那样"修复前"其实是"修复后", 必须报错。
        info.update({"ok": False, "error": f"导入了 {module_file}, 不是请求的源码树 {root_path}"})
        _write_crash_image(out_png, info["error"])
        Path(out_png).with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    try:
        mobject, offset = case.build()
        lace = Lace(
            mobject,
            offset=offset,
            stroke_color=BLACK,
            stroke_width=4,
            fill_color=GRAY_B,
            fill_opacity=1.0,
            hole_swatch=(BLUE, GREEN, RED),
            hole_opacity=1.0,
        )
        lace.move_to([0.0, 0.0, 0.0])
        if float(lace.height) > 0:
            lace.scale_to_fit_height(6.0)
        info.update({"offset": round(float(offset), 6)})
        info.update(_metrics(lace))

        class ReportScene(Scene):
            def construct(self):
                self.add(lace)

        media_dir = Path(out_png).parent / "_media" / Path(out_png).stem
        with tempconfig(
            {
                "quality": "medium_quality",
                "preview": False,
                "verbosity": "ERROR",
                "background_color": WHITE,
                "save_last_frame": True,
                "format": "png",
                "media_dir": str(media_dir),
                "output_file": Path(out_png).stem,
            },
        ):
            ReportScene().render()
        produced = sorted(media_dir.rglob(f"{Path(out_png).stem}*.png"))
        if not produced:
            raise RuntimeError("manim 没有产出图片")
        Path(out_png).write_bytes(produced[-1].read_bytes())
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001
        info["ok"] = False
        info["error"] = f"{type(exc).__name__}: {exc}"
        _write_crash_image(out_png, info["error"])
    Path(out_png).with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _metrics(lace) -> dict:
    """读取求解指标; 老版本(0.2.0)的 `interlacing` 可能没有这些字段, 读不到就只给组数。"""
    inter = getattr(lace, "interlacing", None)
    metrics: dict = {}
    try:
        metrics["holes"] = len(getattr(inter, "holes", None) or lace.holes)
        metrics["ribbons"] = len(getattr(inter, "ribbons", None) or lace.ribbons)
    except Exception:  # noqa: BLE001 - 指标是可选的
        return {}
    try:
        metrics["paths"] = len(inter.paths)
        metrics["intersections"] = len(inter.d_intersections)
        metrics["degraded"] = sorted(int(i) for i in getattr(inter, "_degraded_paths", set()))
        metrics["rail_issues"] = [str(x) for x in getattr(inter, "rail_issues", [])]
    except Exception:  # noqa: BLE001
        pass
    return metrics


def _write_crash_image(out_png: str, message: str) -> None:
    """崩溃状态没有画面 —— 画一张说明图(求解失败本身正是要展示的现象)。"""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 854, 480
    image = Image.new("RGB", (width, height), (253, 240, 241))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for path in ("C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            try:
                font = ImageFont.truetype(path, 20)
                break
            except OSError:  # pragma: no cover - 字体不可用
                continue
    draw.rectangle([20, 20, width - 20, height - 20], outline=(200, 60, 70), width=3)
    draw.text((44, 56), "solver raised / 求解失败", fill=(170, 30, 40), font=font)
    for index, line in enumerate(textwrap.wrap(message, width=62)[:10]):
        draw.text((44, 120 + index * 30), line, fill=(45, 45, 50), font=font)
    draw.text((44, height - 66), "此前没有任何输出: 整幅图的求解中途中断", fill=(130, 70, 80), font=font)
    image.save(out_png)


def child_verdict(root: str, family: str, n: int, level: int, factor: float) -> int:
    """在指定源码树里求解一个配置, 并用**该树自带**的校验器统计各检查项失败数。"""
    import numpy as np

    root_path = Path(root).resolve()
    sys.path.insert(0, str(root_path))
    sys.path.insert(0, str(root_path / "tests"))
    from weave_checks import check_picture

    import manim_lace
    from manim_lace import StarRosette
    from manim_lace.interlacing import Interlacing

    module_file = str(Path(manim_lace.__file__).resolve())
    if not module_file.startswith(str(root_path)):
        print(
            json.dumps(
                {"ok": False, "error": f"导入了 {module_file}, 不是请求的源码树 {root_path}"}, ensure_ascii=False
            )
        )
        return 1

    star = StarRosette(n, level, family)
    paths = [np.asarray(sub, dtype=float)[:, :2] for m in star.family_members_with_points() for sub in m.get_subpaths()]
    r_max = max(float(np.linalg.norm(p, axis=1).max()) for p in paths)
    info: dict = {"root": str(root_path), "family": family, "n": n, "level": level, "factor": factor, "symmetry": n}
    try:
        inter = Interlacing(paths, factor * r_max, validate="ignore")
        try:
            problems = check_picture(inter, symmetry=n, sample_step_factor=0.05)
        except TypeError:
            problems = check_picture(inter)
        info.update(
            {
                "ok": True,
                "total": len(problems),
                "by_kind": {k: sum(1 for p in problems if p.startswith(k)) for k in ("A", "C", "D", "E", "F", "G")},
                "samples": problems[:3],
                "holes": len(inter.holes),
                "ribbons": len(inter.ribbons),
            },
        )
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(info, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------------------
# 父进程: 组织渲染 + 生成网页
# --------------------------------------------------------------------------------------
def ensure_trees() -> None:
    for name, (ref, _) in BASELINES.items():
        target = TREE_DIR / name
        if (target / "manim_lace").is_dir():
            continue
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "archive", ref], cwd=REPO_ROOT, stdout=subprocess.PIPE, check=True)
        subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
        print(f"  extracted {name} <- {ref}")


def run_child(args: list[str]) -> None:
    env = dict(os.environ, _DEFECT_REPORT_CHILD="1", PYTHONIOENCODING="utf-8")
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900,
    )
    if completed.returncode != 0:
        tail = completed.stdout.decode("utf-8", "replace")[-1500:]
        print(f"    [子进程失败] {' '.join(args)}\n{tail}")


def collect_states(case: Case, out_dir: Path, only: set[str], no_render: bool, force: bool) -> dict:
    states: list[tuple[str, tuple[str, str]]] = [("before", case.before), ("after", (CURRENT, ""))]
    if case.intermediate:
        states.append(("intermediate", case.intermediate))
    entry: dict = {}
    for state, (tree, variant) in states:
        png = out_dir / "img" / f"{case.key}__{state}.png"
        meta_path = png.with_suffix(".json")
        need = force or not png.exists() or not meta_path.exists()
        if need and not no_render and (not only or case.key in only):
            print(f"    render {case.key}/{state} <- {tree_label(tree)}{' + ' + variant if variant else ''}")
            run_child(["--render", tree_root(tree), case.key, variant, str(png)])
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        entry[state] = {"png": png, "meta": meta, "tree": tree, "variant": variant}
    return entry


def state_columns(entry: dict) -> list[str]:
    return [s for s in ("before", "after", "intermediate") if s in entry]


def state_label(case: Case, state: str, entry: dict) -> str:
    item = entry[state]
    if state == "after":
        return "修复后 · 当前工作区"
    if state == "before":
        return f"修复前 · {tree_label(item['tree'])}"
    return f"中间态 · {item['variant']}(当前源码 + monkeypatch)"


def images_row(case: Case, entry: dict) -> str:
    cells = []
    for state in state_columns(entry):
        meta = entry[state]["meta"]
        if not meta:
            caption = "未渲染"
        elif not meta.get("ok"):
            caption = f"求解失败: {(meta.get('error') or '无输出')[:74]}"
        else:
            extra = ""
            if "intersections" in meta:
                extra = (
                    f" · 交点 {meta.get('intersections')} · 降级 {len(meta.get('degraded') or [])} · "
                    f"退化提示 {'有' if meta.get('rail_issues') else '无'}"
                )
            caption = f"孔洞 {meta.get('holes')} · 丝带 {meta.get('ribbons')}{extra}"
        cells.append(
            f"<figure class='panel'><a href='img/{case.key}__{state}.png' target='_blank'>"
            f"<img src='img/{case.key}__{state}.png' alt='{case.key} {state}'></a>"
            f"<figcaption><span class='tag'>{state_label(case, state, entry)}</span>"
            f"<span class='cap'>{caption}</span></figcaption></figure>",
        )
    return f"<div class='panels'>{''.join(cells)}</div>"


# --------------------------------------------------------------------------------------
# 文字说明: 直接解析 `DEFECTS.md`(单一事实来源, 报告不再另外维护一份文案)
# --------------------------------------------------------------------------------------
FIELD_NAMES = ("症状", "根因", "修法", "验收", "现状", "扫描规模", "判定方法", "证据")


def load_defect_text() -> dict[str, dict]:
    """从 `DEFECTS.md` 的 `## N. 标题` 小节里取状态与要点字段。

    每个字段只取该条目的**首段**(细节留在文档里, 由卡片链接回指), 这样两份文案不会各自漂移。
    """
    text = (REPO_ROOT / "DEFECTS.md").read_text(encoding="utf-8")
    defects: dict[str, dict] = {}
    current: dict | None = None
    field_key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None and field_key:
            value = " ".join(part for part in buffer if part).strip()
            if value:
                current["fields"].setdefault(field_key, value)
        buffer.clear()

    def nested_bullet(line: str) -> str | None:
        """嵌套条目 `  - **标签**: 正文` / `  - 正文` 的纯文本(条目本身没正文时用它当正文)。"""
        match = re.match(r"\s*[-*]\s*(.*)$", line)
        if match is None:
            return None
        body = match.group(1).strip()
        bold = re.match(r"\*\*([^:：*]+)\*\*[:：]?\s*(.*)$", body)
        return f"{bold.group(1).strip()}: {bold.group(2).strip()}" if bold else body

    for line in text.splitlines():
        heading = re.match(r"^## (\d+)\.\s*(.+)$", line)
        if heading:
            flush()
            field_key = None
            raw = heading.group(2).strip()
            status = "open"
            if "✅" in raw:
                status = "fixed"
            elif "⚠" in raw:
                status = "partial"
            current = {
                "title": re.sub(r"[（(]\s*[✅⚠❌][^）)]*[）)]\s*$", "", raw).strip(),
                "status": status,
                "fields": {},
            }
            defects[heading.group(1)] = current
            continue
        if line.startswith("## "):
            flush()
            field_key = None
            current = None
            continue
        if current is None:
            continue
        field = re.match(r"^- \*\*([^:：*]+)\*\*[:：]?\s*(.*)$", line)
        if field:
            flush()
            label = field.group(1).strip()
            # "根因分两类" / "修法 ① ..." 这类前缀也归到对应字段; 认不出来的按原标签留档
            key = next((name for name in FIELD_NAMES if label.startswith(name)), label)
            field_key = key if key not in current["fields"] else None
            if field_key:
                inline = field.group(2).strip()
                if inline:
                    buffer.append(inline)
            continue
        if not line.strip():
            flush()
            field_key = None
            continue
        if line.lstrip().startswith("- "):
            # 条目本身没有正文(例如 "- **根因分两类**:" 后直接跟子条目): 把子条目收进来当正文
            nested = nested_bullet(line) if field_key and not buffer else None
            if nested is not None:
                buffer.append(nested)
                continue
            flush()
            field_key = None
            continue
        if field_key:
            buffer.append(line.strip())
    flush()
    return defects


def clean(text: str) -> str:
    """去掉 markdown 强调符并压平空白(卡片里按纯文本展示)。"""
    return " ".join(text.replace("**", "").replace("`", "").split())


STATUS_BADGE = {
    "fixed": ("✅ 已修", "ok"),
    "partial": ("⚠️ 部分修复", "warn"),
    "open": ("❌ 未修", "bad"),
}


def defect_fields(meta: dict) -> dict[str, str]:
    """把解析到的 `DEFECTS.md` 字段映射成卡片要展示的 5 项(纯文本)。

    文档里每条缺陷的小节结构不完全一样(缺陷 3 是"根因分两类"、缺陷 7 是条目式), 所以每项都
    留了回退链; 全都取不到就留空(卡片会跳过这一项)。
    """
    fields = meta.get("fields", {})
    known = {name: fields.get(name, "") for name in FIELD_NAMES}
    # 未被字段表认出来的条目(缺陷 7 的 "C/D(浅角假阳性)" 等)拼成"根因"的回退
    extra = " ".join(value for key, value in fields.items() if key not in FIELD_NAMES)
    return {
        "symptom": clean(known["症状"] or fields.get("为什么算缺陷", "")),
        "cause": clean(known["根因"] or extra),
        "fix": clean(known["修法"] or fields.get("配套(必须同时有)", "")),
        "extent": clean(known["验收"] or known["现状"] or fields.get("重扫结果", "")),
        "evidence": clean(known["证据"]),
    }


def build_html(out_dir: Path, results: dict[str, dict], verdicts: list, only: set[str]) -> str:
    meta = load_defect_text()
    cards = []
    for case in CASES:
        if only and case.key not in only:
            continue
        entry = results[case.key]
        badges = "".join(
            f"<span class='badge {STATUS_BADGE[meta[d]['status']][1]}'>"
            f"缺陷 {d} · {STATUS_BADGE[meta[d]['status']][0]}</span>"
            for d in case.defects
            if d in meta
        )
        blocks = []
        for defect in case.defects:
            if defect not in meta:
                continue
            fields = defect_fields(meta[defect])
            rows = "".join(
                f"<div class='kv'><h4>{title}</h4><p>{fields.get(key, '')}</p></div>"
                for title, key in (
                    ("症状", "symptom"),
                    ("根因", "cause"),
                    ("修法", "fix"),
                    ("修复到什么程度 / 仍缺什么", "extent"),
                    ("证据", "evidence"),
                )
                if fields.get(key)
            )
            if rows:
                blocks.append(
                    f"<div class='block'><h5>缺陷 {defect} · {meta[defect]['title']}</h5>{rows}</div>",
                )
        detail = "".join(blocks)
        statuses = ",".join(meta[d]["status"] for d in case.defects if d in meta)
        cards.append(
            f"""
  <section class="card" id="{case.key}" data-status="{statuses}">
    <header>
      <h3>{case.title}</h3>
      <div class="badges">{badges}<span class="tag">{case.note}</span></div>
    </header>
    {images_row(case, entry)}
    <div class="detail">{detail}</div>
  </section>""",
        )

    rows = []
    for defect, text in sorted(meta.items(), key=lambda item: int(item[0])):
        keys = [c.key for c in CASES if defect in c.defects and (not only or c.key in only)]
        label, css = STATUS_BADGE[text["status"]]
        baselines = sorted(
            {tree_label(c.before[0]) for c in CASES if defect in c.defects and (not only or c.key in only)}
        )
        anchor = keys[0] if keys else "d7"
        rows.append(
            f"<tr class='{css}'><td><b>{defect}</b></td><td><a href='#{anchor}'>{text['title']}</a></td>"
            f"<td><span class='badge {css}'>{label}</span></td>"
            f"<td>{defect_fields(text)['cause'][:72]}…</td>"
            f"<td class='mono'>{' / '.join(baselines)}</td></tr>",
        )

    verdict_rows = "".join(
        f"<tr><td>{label}</td><td class='mono'>{_verdict_text(before)}</td>"
        f"<td class='mono'>{_verdict_text(after)}</td></tr>"
        for label, before, after in verdicts
    )
    verdict_block = ""
    if verdicts:
        fields = defect_fields(meta.get("7", {"fields": {}}))
        detail = "".join(
            f"<div class='kv'><h4>{title}</h4><p>{fields.get(key, '')}</p></div>"
            for title, key in (
                ("症状", "symptom"),
                ("根因", "cause"),
                ("修法", "fix"),
                ("修复到什么程度 / 仍缺什么", "extent"),
                ("证据", "evidence"),
            )
            if fields.get(key)
        )
        verdict_block = f"""
  <section class="card" id="d7">
    <header><h3>缺陷 7 · 校验器 C/D/G 的系统性误报(判定口径对照)</h3>
      <div class="badges"><span class="badge ok">✅ 已修</span>
        <span class="tag">不体现在画面上, 对照的是判定结果</span></div></header>
    <p class="hint">同一批配置分别在 <code>{BASELINES["prestep3"][0]}</code> 与当前工作区<b>自带的</b>
       校验器下打分, 列出各检查项(A/C/D/E/F/G)的失败条目数(对称阶取 n)。修复前把正常编织判成
       未编织 / 不对称 —— 那正是当时"哪些配置合格"结论失真的根源。</p>
    <table class="verdict"><thead><tr><th>配置</th>
      <th>修复前 · {BASELINES["prestep3"][0]}</th><th>修复后 · 当前工作区</th></tr></thead>
      <tbody>{verdict_rows}</tbody></table>
    <div class="detail">{detail}</div>
  </section>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>manim-lace 缺陷对照报告</title>
<style>
  :root {{ --ink:#1d2026; --muted:#5f6a78; --line:#e3e7ee; --bg:#f5f7fa;
           --ok:#1f8a4c; --warn:#b47700; --bad:#c0392b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.75 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  main {{ max-width:1560px; margin:0 auto; padding:26px 20px 90px; }}
  h1 {{ font-size:26px; margin:0 0 6px; }}
  h3 {{ font-size:17px; margin:0; }}
  h4 {{ margin:0 0 2px; font-size:13px; color:var(--muted); font-weight:600; }}
  p {{ margin:0 0 8px; }}
  a {{ color:#2f6df6; }}
  code, .mono {{ font-family:"Cascadia Code", Consolas, monospace; font-size:12.5px; }}
  .lead {{ color:var(--muted); max-width:1050px; }}
  .hint {{ color:var(--muted); font-size:13px; }}
  .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; margin:18px 0 10px; align-items:center; }}
  .toolbar button {{ border:1px solid var(--line); background:#fff; border-radius:999px;
                     padding:6px 14px; cursor:pointer; font-size:13px; }}
  .toolbar button.active {{ border-color:#2f6df6; color:#2f6df6; font-weight:600; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 20px;
           margin:16px 0; box-shadow:0 1px 2px rgba(20,30,50,.05); }}
  .card > header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; }}
  .badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .badge {{ font-size:12px; padding:2px 9px; border-radius:999px; border:1px solid transparent; white-space:nowrap; }}
  .badge.ok {{ background:#e8f6ee; color:var(--ok); border-color:#bfe5cd; }}
  .badge.warn {{ background:#fff6e5; color:var(--warn); border-color:#f0dcae; }}
  .badge.bad {{ background:#fdecea; color:var(--bad); border-color:#f3c4bf; }}
  .tag {{ font-size:12px; color:var(--muted); background:#f2f4f7; border-radius:6px; padding:2px 8px; }}
  .panels {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:14px; margin:16px 0 6px; }}
  .panel {{ margin:0; border:1px solid var(--line); border-radius:10px; overflow:hidden; background:#fff; }}
  .panel img {{ display:block; width:100%; height:auto; }}
  figcaption {{ padding:6px 10px 8px; display:flex; flex-direction:column; gap:3px; }}
  .cap {{ color:var(--muted); font-size:12px; }}
  .detail {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:10px 22px;
             border-top:1px dashed var(--line); padding-top:12px; margin-top:6px; }}
  .block {{ border-left:3px solid var(--line); padding-left:12px; }}
  .block h5 {{ margin:0 0 6px; font-size:13.5px; }}
  table {{ border-collapse:collapse; width:100%; margin:10px 0 4px; background:#fff; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }}
  thead th {{ background:#f7f9fc; font-weight:600; }}
  tr.ok td:first-child {{ border-left:4px solid var(--ok); }}
  tr.warn td:first-child {{ border-left:4px solid var(--warn); }}
  tr.bad td:first-child {{ border-left:4px solid var(--bad); }}
</style>
</head>
<body>
<main>
  <h1>manim-lace 缺陷对照报告</h1>
  <p class="lead">为 <code>DEFECTS.md</code> 里的每条缺陷生成<b>修复前 / 修复后</b>渲染图: 同一段场景代码
     分别在 <code>git archive</code> 取出的<b>历史源码树</b>与<b>当前工作区</b>里各渲一遍, 图的差异就是
     源码的差异; 每张图下面标出求解结果(孔洞 / 丝带 / 交点 / 降级路径数 / 退化提示), 崩溃的配置直接
     展示错误信息。基线是按<b>实测</b>挑的 —— 每个用例都验证过在该树下确实表现出缺陷、修复后确实变了。
     图片可点击放大, 顶部可按状态筛选。</p>
  <p class="hint">基线源码树:
      {", ".join(f"<code>{name}</code> = {ref} ({desc})" for name, (ref, desc) in BASELINES.items())}</p>
  <p class="hint"><b>怎么读数据</b>: <code>降级 N</code> = 被判定为"派生几何不满足配对契约"的路径数 ——
     这些路径**不参与编织**, 渲染成一条完整的丝带(并有 <code>UserWarning</code> + <code>rail_issues</code>
     说明原因)。因此降级图里的 <code>C</code> 检查必然报"交点处不是恰好一条丝带": 那是降级的**定义**,
     不是新缺陷。相反, "编织"≠"正确" —— 有残差的配置(如各花型的极端阶)会织出图但仍有 C/E/F 失败,
     这类配置不属于"已知良好"名单。</p>

  <div class="toolbar">
    <button data-filter="all" class="active">全部</button>
    <button data-filter="fixed">✅ 已修</button>
    <button data-filter="partial">⚠️ 部分修复</button>
    <button data-filter="open">❌ 未修</button>
    <span class="hint">生成: <code>uv run python tools/defect_report.py</code></span>
  </div>

  <section class="card">
    <header><h3>状态一览</h3></header>
    <table><thead><tr><th>#</th><th>缺陷</th><th>状态</th><th>根因要点</th><th>修复前基线</th></tr></thead>
    <tbody>{"".join(rows)}</tbody></table>
  </section>
{verdict_block}
{"".join(cards)}

  <section class="card">
    <header><h3>全局回归底线(任何改动都必须逐字节守住的部分)</h3></header>
    <ul>
      <li><b>A/B 渲染底线</b>: <code>tools/ab_render.py</code> 用 <code>{BASELINES["v020"][0]}</code> 与当前
          工作区各渲一遍 <code>examples/lace_scenes.py</code> 的前 4 个场景, 两边图片 md5 必须
          <b>4/4 逐字节一致</b>。</li>
      <li><b>全矩阵指纹</b>: <code>tools/matrix_digest.py</code> 覆盖 5 花型 × n=5..20 × 各阶 × 两种丝带宽度
          + 曲线 / 闭合图形, 共 1166 行; 判据是"两态都是 <code>deg=0</code> 的配置必须逐字节不变"。</li>
      <li>本次会话(缺陷 9/10)的数字: 崩溃 <b>7 → 0</b>; 两态 <code>deg=0</code> 的 510 组里 <b>510 组不变</b>
          (另有 6 组改动前就违反可见性检查的配置切得更细); <b>0 组</b>失去编织; 54 组从"静默画错"
          转成"诚实降级"(逐组核对过它们改动前就已违反检查, 0 误伤)。</li>
      <li><code>uv run pytest -q</code> → 448 passed; <code>ruff check</code> /
          <code>ruff format --check</code> 全绿。</li>
    </ul>
  </section>
</main>
<script>
  const buttons = [...document.querySelectorAll('.toolbar button')];
  const cards = [...document.querySelectorAll('section.card[id]')];
  buttons.forEach(btn => btn.addEventListener('click', () => {{
    buttons.forEach(b => b.classList.toggle('active', b === btn));
    const want = btn.dataset.filter;
    cards.forEach(card => {{
      const statuses = (card.dataset.status || '').split(',').filter(Boolean);
      card.style.display = (want === 'all' || statuses.includes(want)) ? '' : 'none';
    }});
  }}));
</script>
</body>
</html>
"""


def _verdict_text(info: dict) -> str:
    if not info:
        return "—"
    if not info.get("ok"):
        return f"求解失败: {info.get('error', '')[:60]}"
    kinds = ", ".join(f"{k}={v}" for k, v in info["by_kind"].items() if v)
    return f"失败 {info['total']} 处({kinds or '无'}) · h={info['holes']} r={info['ribbons']}"


#: 缺陷 7 的"修复前"基线树(校验器口径变更发生在 pre-step3 之后)
BASE_ROOT_FOR_VERDICT = str(TREE_DIR / "prestep3")


def main() -> int:
    parser = argparse.ArgumentParser(description="缺陷对照报告(渲染 + 网页)")
    parser.add_argument("--render", nargs=4, metavar=("ROOT", "CASE", "VARIANT", "OUT"))
    parser.add_argument("--verdict", nargs=5, metavar=("ROOT", "FAMILY", "N", "LEVEL", "FACTOR"))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--only", default="", help="只渲/只写这些用例(key 逗号分隔)")
    parser.add_argument("--no-render", action="store_true", help="复用已有图片, 只重写网页")
    parser.add_argument("--force", action="store_true", help="已有图片也重渲一遍")
    args, _unknown = parser.parse_known_args()

    if os.environ.get("_DEFECT_REPORT_CHILD") and args.render:
        return child_render(*args.render)
    if os.environ.get("_DEFECT_REPORT_CHILD") and args.verdict:
        return child_verdict(
            args.verdict[0],
            args.verdict[1],
            int(args.verdict[2]),
            int(args.verdict[3]),
            float(args.verdict[4]),
        )

    out_dir = Path(args.out)
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    only = {k.strip() for k in args.only.split(",") if k.strip()}

    print("1) 准备历史源码树")
    ensure_trees()

    print("2) 渲染对照图")
    results = {case.key: collect_states(case, out_dir, only, args.no_render, args.force) for case in CASES}

    print("3) 缺陷 7 的判定口径对照")
    verdicts = []
    for label, family, n, level, factor in VERDICT_CASES:
        pair = []
        for root, tag in ((BASE_ROOT_FOR_VERDICT, "before"), (".", "after")):
            cache = out_dir / "img" / f"verdict_sym{n}__{family}{n}L{level}__{tag}.json"
            if cache.exists():
                pair.append(json.loads(cache.read_text(encoding="utf-8")))
                continue
            env = dict(os.environ, _DEFECT_REPORT_CHILD="1", PYTHONIOENCODING="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--verdict",
                    root,
                    family,
                    str(n),
                    str(level),
                    str(factor),
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=900,
            )
            lines = completed.stdout.decode("utf-8", "replace").strip().splitlines()
            info = json.loads(lines[-1]) if lines else {}
            cache.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            pair.append(info)
        print(f"    {label}: {_verdict_text(pair[0])}  ->  {_verdict_text(pair[1])}")
        verdicts.append((label, pair[0], pair[1]))

    print("4) 写网页")
    index = out_dir / "index.html"
    index.write_text(build_html(out_dir, results, verdicts, only), encoding="utf-8")
    print(f"   {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
