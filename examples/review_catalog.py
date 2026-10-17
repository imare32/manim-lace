"""The case catalog behind the human review page (``examples/build_review.py``).

Every case is one picture a person is asked to look at, plus the programmatic
expectation it should meet. The catalog is the single place a review case is defined:
the page, the tests and the probe mode all read it, so a case can never be described
twice and drift.

Six categories, deliberately covering different risks:

``spec``
    The four input classes SPEC §10.2 requires for benchmarking — the geometry the
    performance harness already uses (``manim_lace.benchmarks``), so a reviewer looks
    at exactly the shapes whose timings are quoted.
``index``
    The nine candidate-index scenarios from ``tests/test_index.py``, where the pruned
    grid and the brute-force oracle must agree event for event.
``degenerate``
    Hand-built shapes that aim at one classification each: tangency, endpoint contact,
    collinear overlap, multiway coincidence, a zero-length path, a fully cut strand, a
    collapsed offset, and the three offset-join styles.
``adapter``
    Real Manim objects, so the extraction layer is reviewed too — recursion, dedup,
    Bezier sampling, and the two inputs that must *fail* loudly.
``gallery``
    The published showcase patterns. Their source geometry is taken back out of the
    builder the gallery scene uses (``Lace.target_mobject``), so the review page and the
    status gallery can never drift apart.
``rosette``
    Star-rosette weaves: the densest real input, including two configurations known to
    sit on documented degenerate ground.

Cases state what must be true of them (``expect_diagnostics``, crossing counts) and
``tests/test_review_catalog.py`` asserts it, so the page's expectations are tested
rather than trusted.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from manim_lace import PolylinePath, sample_implicit

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
TESTS = ROOT / "tests"


def _examples_path() -> None:
    """Make the sibling example modules importable the way the scenes do."""
    for entry in (EXAMPLES, TESTS):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))


@dataclass(frozen=True, slots=True)
class Source:
    """What a case hands to the renderer.

    Exactly one of ``paths`` / ``mobject`` is set. ``offset`` and ``weave_mode`` default
    to the case's own fields but a source may override them — the gallery patterns each
    carry their published width and mode, and overriding them would review a different
    weave than the card shows.
    """

    paths: list[Any] | None = None
    mobject: Any = None
    offset: float | None = None
    weave_mode: str | None = None
    #: Subdivision summaries for sources that sampled their own curve, forwarded to the
    #: engine so input-stage diagnostics are not lost when a case builds its own paths.
    sampling_trace: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class Case:
    """One review case: geometry, how to render it, and what must hold."""

    key: str
    category: str
    title: str
    prose: str
    kind: str  # "paths" | "manim" | "error"
    source: Callable[[], Source]
    offset: float = 0.12
    weave_mode: str = "alternating"
    channels: tuple[str, ...] = ("stroke", "boolean", "arrangement")
    engine: dict[str, Any] = field(default_factory=dict)
    expect_diagnostics: tuple[str, ...] = ()
    expect_any_diagnostics: tuple[str, ...] = ()
    forbid_diagnostics: tuple[str, ...] = ()
    expect_crossings: int | None = None
    expect_min_crossings: int | None = None
    expect_self_crossings: int | None = None
    expect_error: str | None = None
    #: Channels this round deliberately does not run, each with the measured reason. Used
    #: when a channel is pathologically expensive on a case: the page then says so instead
    #: of quietly showing fewer panels, and the reason carries the numbers behind it.
    omitted: tuple[tuple[str, str], ...] = ()
    #: Optional zoom window ``(centre_x, centre_y, span)`` for a case whose interesting
    #: geometry is tiny compared to its extent — a near-tangent needs a strand thousands of
    #: units long to make sinθ ≤ 1e-7, and framing on the full bounding box would draw the
    #: crossing as a single pixel. ``span`` is the world height of the window.
    focus: tuple[float, float, float] | None = None
    look_for: str = ""
    tags: tuple[str, ...] = ()
    annotate: bool = True


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    title: str
    subtitle: str
    what: str


CATEGORIES: tuple[Category, ...] = (
    Category(
        "spec", "SPEC §10.2 基准集",
        "需求书要求覆盖的四类输入，性能基准用的就是这一份几何",
        "看的是「最基本的情形对不对」：直线交叉、密采样平滑曲线的候选剪枝、"
        "单条自交曲线的两次经过、多路径网络的互不误判。这四类也是 make bench 报时的那四类，"
        "如果有人要质疑性能数字，先看这里的图。",
    ),
    Category(
        "index", "候选索引场景（tests/test_index.py）",
        "网格剪枝与暴力枚举必须逐事件、逐诊断、逐片段一致",
        "看的是「剪枝有没有悄悄改变结果」：平行长细段让网格退化、共点扇让聚类爆量、"
        "随机游走与重复点制造退化输入、尺度悬殊考验容差。这些场景在测试里只比对指纹，"
        "页面让你直接看它们长什么样。",
    ),
    Category(
        "degenerate", "退化与特殊事件",
        "每个图形瞄准一种事件分类或一种几何风险",
        "看的是「不该硬猜的地方有没有硬猜」：相切与端点接触是否被如实分类、共线重叠是否被拒绝发明交叉、"
        "多线共点是否拒绝给出唯一上下顺序、零长路径与整条被切是否上报、"
        "薄楔与塌陷偏移是否被诊断而不是画出畸形。这里也放了三段连接策略的对照。",
    ),
    Category(
        "adapter", "Manim 输入适配层",
        "真实 Manim 对象：递归提取、去重、贝塞尔采样、必须失败的两类输入",
        "看的是「从 Manim 拿到的东西对不对」：圆弧是否按贝塞尔采样而不是把控制柄当顶点、"
        "嵌套 VGroup 是否重复收集、五角星这种手工折线是否被当折线、"
        "非共面与无几何对象是否明确报错而不是画出一张空图。",
    ),
    Category(
        "gallery", "状态画廊图案",
        "源几何直接取自画廊卡片的 builder，两处不会漂移",
        "看的是「已发布的图案在统一风格下是否仍然正确」：画廊卡片各自带自己的配色与线宽，"
        "这里换成同一套配色与线宽，三通道并排，方便比出切口、遮挡与上下关系是否一致。",
    ),
    Category(
        "implicit", "隐式曲线提取（SPEC FR-008）",
        "独立等值线提取器：多分支拆分、分支来源、朝向规则、误差控制，以及它做不到的两件事",
        "看的是「从方程直接拿到的曲线对不对」：一条闭合分支要看起来就是个圆、"
        "一个水平集的两个连通分支要各成一条股线、开曲线端点要停在盒子边界。"
        "同时把两件**做不到**的事摆出来让人眼判：自触水平集的交点会丢失"
        "（八字的结点、十字的原点），以及极点会被插值造出一条假等值线。"
        "这两件事都有明确的程序信号（0 交叉 / 残差超标），但「能不能接受」需要人判。",
    ),
    Category(
        "rosette", "玫瑰线编织",
        "最密的真实输入：单条闭合自交股线、几十个交叉",
        "看的是「密集自交下还站得住吗」：玫瑰线是本仓库最重的真实输入（70 交叉 / 20 处自交），"
        "其中 n5 CA 与 n5 PO 是文档承认的共点交叉退化配置，两张图就是给人眼去判它到底错在哪。",
    ),
)

CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}

#: Categories whose source geometry needs Manim to build (real Manim objects, the gallery
#: builders, or the rosette support module). The others are pure NumPy paths, which is why
#: the default test run can assert their expectations without Manim installed.
MANIM_CATEGORIES = frozenset({"adapter", "gallery", "rosette"})

#: Sources are pure functions of their arguments and are read-only once built (the
#: extraction adapter only reads points), so the same geometry is reused instead of being
#: rebuilt and re-solved for every channel: the review page, the probe and the tests all
#: ask for the same case several times.
_SOURCE_CACHE: dict[str, Source] = {}


def _cached(key: str, factory: Callable[[], Source]) -> Source:
    if key not in _SOURCE_CACHE:
        _SOURCE_CACHE[key] = factory()
    return _SOURCE_CACHE[key]


# ---------------------------------------------------------------------------
# spec: the four benchmark classes
# ---------------------------------------------------------------------------


def _benchmark(name: str) -> Source:
    return _cached(f"benchmark:{name}", lambda: _benchmark_source(name))


def _benchmark_source(name: str) -> Source:
    from manim_lace.benchmarks import scenarios

    return Source(paths=scenarios()[name])


# ---------------------------------------------------------------------------
# index: the candidate-index scenarios
# ---------------------------------------------------------------------------


def _index_scenarios() -> dict[str, list[Any]]:
    """The real scenarios from ``tests/test_index.py``.

    Loaded from the test module by path rather than re-typed here: the review page is
    supposed to show the inputs the equivalence tests actually run, and a copy would
    agree with them only until someone edits one of the two.
    """
    _examples_path()
    path = TESTS / "test_index.py"
    name = "_review_test_index"
    if name in sys.modules:
        return sys.modules[name]._scenarios()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - file is in the repo
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module._scenarios()


def _index(name: str) -> Source:
    return _cached(f"index:{name}", lambda: Source(paths=_index_scenarios()[name]))


# ---------------------------------------------------------------------------
# degenerate: one targeted shape per classification
# ---------------------------------------------------------------------------


def _deg_bow() -> Source:
    """A bow-tie: one open path crossing itself once."""
    return Source(paths=[PolylinePath(
        np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]]),
        path_id="bow", closed=False,
    )])


def _deg_figure_eight() -> Source:
    """A closed figure eight: one self-crossing, seam away from it."""
    theta = np.linspace(0.0, 2.0 * np.pi, 361)
    points = np.column_stack((np.sin(theta), np.sin(2.0 * theta)))
    return Source(paths=[PolylinePath(points, path_id="eight", closed=True)])


def _deg_pentagram() -> Source:
    """The star polygon {5/2}: five self-crossings, strictly alternatable."""
    angles = [np.pi / 2.0 + index * 2.0 * np.pi / 5.0 for index in range(5)]
    outer = [np.array([1.4 * np.cos(a), 1.4 * np.sin(a)]) for a in angles]
    order = (0, 2, 4, 1, 3)
    vertices = [outer[i] for i in order]
    return Source(paths=[PolylinePath(np.array(vertices), path_id="star", closed=True)])


def _deg_circle_line() -> Source:
    """A closed circle whose seam sits exactly on the crossing with the line."""
    theta = np.linspace(0.0, 2.0 * np.pi, 361)
    circle = PolylinePath(
        np.column_stack((np.cos(theta), np.sin(theta))), path_id="circle", closed=True
    )
    line = PolylinePath(np.array([[-1.6, 0.0], [1.6, 0.0]]), path_id="line")
    return Source(paths=[circle, line])


def _deg_three_lines_vertical() -> Source:
    """Three parallel lines plus one vertical: the strict-alternation case."""
    paths = [
        PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="h0"),
        PolylinePath(np.array([[-2.0, 0.8], [2.0, 0.8]]), path_id="h1"),
        PolylinePath(np.array([[-2.0, -0.8], [2.0, -0.8]]), path_id="h2"),
        PolylinePath(np.array([[0.0, -2.0], [0.0, 2.0]]), path_id="v"),
    ]
    return Source(paths=paths)


def _deg_collinear_overlap() -> Source:
    """Two collinear segments sharing an interval: no transverse crossing exists."""
    return Source(paths=[
        PolylinePath(np.array([[0.0, 0.0], [2.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[1.0, 0.0], [3.0, 0.0]]), path_id="b"),
    ])


def _deg_t_junction() -> Source:
    """A strand ending exactly on another one: an endpoint touch, not a crossing."""
    return Source(paths=[
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[0.0, 0.0], [0.0, 1.0]]), path_id="b"),
    ])


def _deg_shallow_angle() -> Source:
    """Two nearly parallel lines: a shallow-angle crossing the renderer must bound."""
    return Source(paths=[
        PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="a"),
        PolylinePath(np.array([[-2.0, -0.05], [2.0, 0.05]]), path_id="b"),
    ])


def _deg_multiway_fan() -> Source:
    """Four strands through one point: no unique binary over/under exists."""
    paths = []
    for index, angle in enumerate(np.linspace(0.0, np.pi, 4, endpoint=False)):
        direction = np.array([np.cos(angle), np.sin(angle)]) * 1.8
        paths.append(PolylinePath(np.array([-direction, direction]), path_id=f"fan{index}"))
    return Source(paths=paths)


def _deg_degenerate_path() -> Source:
    """A zero-length path next to a healthy one: reported, never silently dropped."""
    return Source(paths=[
        PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="real"),
        PolylinePath(np.array([[0.0, 0.5], [0.0, 0.5]]), path_id="zero"),
    ])


def _deg_fully_cut() -> Source:
    """A stub that the crossing cut swallows whole.

    Order matters: the stub is the *second* path so the alternating solver puts it under,
    and an under strand whose cut reaches both ends emits no piece at all and reports
    ``RENDER-PATH-FULLY-CUT`` (measured: cut radius ``offset/sinθ + overshoot·offset`` =
    0.618 against a 0.3-long stub).
    """
    return Source(paths=[
        PolylinePath(np.array([[0.0, -1.2], [0.0, 1.2]]), path_id="crosser"),
        PolylinePath(np.array([[-0.3, 0.0], [0.3, 0.0]]), path_id="stub"),
    ])


def _deg_thin_wedge() -> Source:
    """A sliver triangle crossed by a line: the offset collapses at the tip."""
    return Source(paths=[
        PolylinePath(np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 0.03]]), path_id="wedge",
                     closed=True),
        PolylinePath(np.array([[1.0, -1.0], [1.0, 1.0]]), path_id="line"),
    ])


def _deg_near_tangent() -> Source:
    """A genuinely near-tangent crossing (``GEOM-NEAR_TANGENT``).

    The classification needs ``sinθ ≤ angle_tol × 10 = 1e-7`` — almost exactly parallel —
    *and* a crossing that is not an endpoint *and* a perpendicular distance above
    ``position_tol``, otherwise the detector reports a collinear overlap instead. A strand
    that long is why this case needs ``focus``: the crossing itself is a few units wide.
    """
    return Source(paths=[
        PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="base"),
        PolylinePath(np.array([[-1e4, -1e-3], [1e4, 1e-3]]), path_id="hair"),
    ])


def _deg_square() -> Source:
    """A square crossed by a diagonal: the offset-join style under review."""
    square = PolylinePath(
        np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]]),
        path_id="square", closed=True,
    )
    diagonal = PolylinePath(np.array([[-2.0, -1.5], [2.0, 1.5]]), path_id="diag")
    return Source(paths=[square, diagonal])


def _deg_repeated_points() -> Source:
    """A path with repeated vertices and a zero-length step next to a clean line."""
    return Source(paths=[
        PolylinePath(
            np.array([[-1.0, 0.0], [0.0, 0.0], [0.0, 0.0], [1.0, 0.0]]), path_id="flat"
        ),
        PolylinePath(
            np.array([[-1.0, -1.0], [0.0, 0.0], [1.0, 0.0], [0.0, 0.0], [1.0, 1.0]]),
            path_id="zig",
        ),
    ])


# ---------------------------------------------------------------------------
# adapter: real Manim objects
# ---------------------------------------------------------------------------


def _adapter_circle_line() -> Source:
    from manim import Circle, Line, VGroup

    return Source(mobject=VGroup(
        Circle(radius=1.2, color="#888888"),
        Line(np.array([-1.8, 0.0, 0.0]), np.array([1.8, 0.0, 0.0]), color="#888888"),
    ))


def _adapter_two_lines() -> Source:
    from manim import Line, VGroup

    return Source(mobject=VGroup(
        Line(np.array([-2.0, -1.0, 0.0]), np.array([2.0, 1.0, 0.0]), color="#888888"),
        Line(np.array([-2.0, 1.0, 0.0]), np.array([2.0, -1.0, 0.0]), color="#888888"),
    ))


def _adapter_parametric() -> Source:
    """A Lissajous from ``ParametricFunction``: self-crossings via the Bezier probe."""
    from manim import ParametricFunction, VGroup

    return Source(mobject=VGroup(ParametricFunction(
        lambda t: np.array([np.sin(3.0 * t), np.sin(2.0 * t), 0.0]),
        t_range=[0.0, 2.0 * np.pi], color="#888888",
    )), offset=0.09)


def _adapter_arc_polygon() -> Source:
    """An ``Arc`` and a ``RegularPolygon``: two non-line basic vector objects.

    The radii are chosen so the two really cross: a pentagon of circumradius 1.5 has an
    apothem of 1.5·cos36° ≈ 1.21, so an arc below that sits entirely inside (measured: 0
    crossings) and one above 1.5 entirely outside. 1.35 threads between the two and gives
    8 transverse crossings.
    """
    from manim import Arc, RegularPolygon, VGroup

    return Source(mobject=VGroup(
        Arc(radius=1.35, start_angle=0.0, angle=1.5 * np.pi, color="#888888"),
        RegularPolygon(n=5, radius=1.5, color="#888888"),
    ), offset=0.1)


def _adapter_arc_overlapping() -> Source:
    """An ``Arc`` of more than one full turn: it overlaps *itself*.

    ``Arc(angle=3π)`` draws one and a half turns, so the last half retraces the first —
    a self-overlap rather than a self-crossing. Measured: 175 events in the stroke channel
    (77 of them collinear-overlap-adjacent near-tangent/endpoint noise). The two region
    backends used to exceed 60s and 2.7GB without finishing; the two indexed lookups in
    ``mark_flush_edges`` took that to 17.7s (boolean) and 8.3s (arrangement), which is
    still the most expensive input in the catalog by an order of magnitude. It is in the
    catalog because an arc with a large angle is an ordinary thing to write, and the
    review page should say what happens rather than pretend the case is unremarkable.
    """
    from manim import Arc, Line, VGroup

    return Source(mobject=VGroup(
        Arc(radius=1.2, start_angle=0.0, angle=3.0 * np.pi, color="#888888"),
        Line(np.array([-2.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0]), color="#888888"),
    ), offset=0.1)


def _adapter_pentagram_vmobject() -> Source:
    """A pentagram built with ``set_points_as_corners``: a hand-made point layout."""
    from manim import VMobject

    angles = [np.pi / 2.0 + index * 2.0 * np.pi / 5.0 for index in range(5)]
    outer = [np.array([1.4 * np.cos(a), 1.4 * np.sin(a), 0.0]) for a in angles]
    order = (0, 2, 4, 1, 3)
    star = VMobject()
    star.set_points_as_corners(np.array([outer[i] for i in order] + [outer[order[0]]]))
    star.set_stroke("#888888", width=2)
    return Source(mobject=star, offset=0.12)


def _adapter_nested_vgroup() -> Source:
    """A nested VGroup: recursion must not collect a parent and its child twice."""
    from manim import Circle, Line, VGroup

    inner = VGroup(Circle(radius=0.8, color="#888888"))
    return Source(mobject=VGroup(inner, Line(
        np.array([-1.6, 0.4, 0.0]), np.array([1.6, 0.4, 0.0]), color="#888888",
    )), offset=0.11)


def _adapter_nonplanar() -> Source:
    """A path whose points are not in an XY plane: must raise, not silently project."""
    from manim import VMobject

    mobject = VMobject()
    mobject.set_points_as_corners(np.array([
        [-1.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 1.0],
    ]))
    return Source(mobject=mobject)


def _adapter_missing_geometry() -> Source:
    """A plain ``Mobject`` with no vector points: must raise an understandable error."""
    from manim import Mobject

    return Source(mobject=Mobject())


# ---------------------------------------------------------------------------
# gallery + rosette: the published patterns, geometry taken back from the builder
# ---------------------------------------------------------------------------


def _gallery_source(builder: str) -> Source:
    """Run a gallery builder once and read its source geometry back out.

    ``Lace.target_mobject`` is the exact VGroup the published card wove, and the card's
    own ``offset``/``weave_mode`` come along with it — so this re-renders the published
    pattern in the review page's uniform style instead of a look-alike.
    """
    _examples_path()
    scene_gallery = importlib.import_module("scene_gallery")
    lace = getattr(scene_gallery, builder)()
    return Source(
        mobject=lace.target_mobject,
        offset=float(lace.offset),
        weave_mode=str(lace.engine.weave_mode),
    )


def _gallery(builder: str) -> Source:
    return _cached(f"gallery:{builder}", lambda: _gallery_source(builder))


def _rosette_source(n: int, levels: tuple[int, ...], star_type: str) -> Source:
    """Merge the rosette loops of one or more levels into closed self-crossing strands."""
    return _cached(
        f"rosette:{n}:{levels}:{star_type}",
        lambda: _rosette_loops_source(n, levels, star_type),
    )


def _rosette_loops_source(n: int, levels: tuple[int, ...], star_type: str) -> Source:
    _examples_path()
    scene_rosette = importlib.import_module("scene_rosette")
    paths: list[Any] = []
    for level in levels:
        for index, loop in enumerate(scene_rosette.rosette_loops(n, level, star_type)):
            paths.append(PolylinePath(
                np.asarray(loop, dtype=float),
                path_id=f"rosette-{n}-{star_type}-L{level}-{index}",
            ))
    return Source(paths=paths)


# ---------------------------------------------------------------------------
# implicit: the independent isocontour extractor (SPEC FR-008)
# ---------------------------------------------------------------------------


def _implicit(
    field: Callable[[Any, Any], Any],
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    **kwargs: Any,
) -> Source:
    """Build a source by extracting ``F(x, y) = level`` (default level 0).

    Pure NumPy, so these cases belong to the lane the default test run covers without
    Manim. The subdivision summary travels with the source: without it the engine would
    never see the sampler's warnings (a missed error target, an ambiguous saddle), which is
    exactly how the pole case below would silently look like an ordinary circle.
    """
    summaries: list[dict[str, Any]] = []
    paths = sample_implicit(
        field, x_range, y_range, subdivision_tracer=summaries.append, **kwargs
    )
    return Source(paths=paths, sampling_trace=tuple(summaries))


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------

_CASES: tuple[Case, ...] = (
    # --- spec ---------------------------------------------------------------
    Case("spec-simple", "spec", "简单图形（直线 + 闭合方框）",
         "SPEC §10.2 第一类：几条直线交叉 + 一个闭合正方形。基准里最简单的一档。",
         "paths", lambda: _benchmark("simple"), offset=0.12,
         expect_min_crossings=4, expect_self_crossings=0,
         look_for="方框四角是否为尖角、三条直线各自的交叉是否一上一下清晰。",
         tags=("直线", "闭合路径")),
    Case("spec-dense-smooth", "spec", "密采样平滑曲线（圆 + 正弦）",
         "SPEC §10.2 第二类：1201 点的圆与 601 点的正弦波，用来压候选剪枝。",
         "paths", lambda: _benchmark("dense_smooth"), offset=0.1,
         expect_min_crossings=2,
         look_for="曲线的圆滑度、交叉处切口是否垂直于上股丝带、有没有因为采样密而冒出的碎片段。",
         tags=("密采样", "剪枝")),
    Case("spec-self-intersecting", "spec", "大量自交曲线（Lissajous 5:4）",
         "SPEC §10.2 第三类：1501 点的 Lissajous 曲线，同一交点被经过两次。"
         "实测 31 个交叉全部是自交，严格交替**可以全程成立**（0 处放宽、0 处逐次同侧），"
         "三个通道的分配完全一致。这条曲线在同一坐标上被经过两次：弧长 0.00 与 27.22 是"
         "**闭合路径接缝上的同一个位置**，与 6.73 相交——那里本来只是一个交叉。引擎曾按"
         "接缝两侧各报一次、把它当成两个交叉事件（X0000 配 0.00/6.73、X0015 配 6.73/27.22），"
         "于是凭空多出一个共点交叉和一条无法满足的交替约束（14 处被放宽、28 处逐次同侧，"
         "并报出 REGION-COINCIDENT-CROSSINGS）。交叉去重按弧长取模之后两者合成一个事件，"
         "这些诊断随之消失，boolean 的未描缺口也从 3 段 / 0.0386 降到 2 段 / 0.0274。",
         "paths", lambda: _benchmark("self_intersecting"), offset=0.08,
         channels=("stroke", "boolean", "arrangement", "hybrid"),
         expect_crossings=31, expect_self_crossings=31,
         # Pinned as a regression guard: both of these only ever appeared because one
         # crossing was reported twice at the seam of a closed path.
         forbid_diagnostics=("TOPOLOGY-ALTERNATION-RELAXED", "REGION-COINCIDENT-CROSSINGS"),
         look_for="自交处两次经过是否各自被正确切分，有没有在丝带中间留下横线或缺口。"
                  "人眼点名过两类：boolean 的四个角交叉口有『V 字形差一点点没闭合』，"
                  "arrangement 有长边没有像 boolean 那样被后画填充正确遮挡。"
                  "新增的 experimental hybrid 通道以 boolean 的遮挡为底，只从 arrangement"
                  "补入短、共线且接在既有断点上的缺口；它应当既闭合 V 形，又不出现"
                  "arrangement 的长横线，也不留布尔 overlay 画在自己填充上的 10 个亚像素"
                  "孤立黑点。与 flush 接缝重合的两条短刺现在由共享的"
                  "`missing_weave_outlines` 直接判掉，boolean 参考通道上也不再出现。",
         tags=("自交", "参数曲线", "已知缺陷签名", "共点交叉")),
    Case("spec-network", "spec", "多路径网络（12 竖 + 12 横 + 3 圆）",
         "SPEC §10.2 第四类：27 条路径构成的交叉网络，考验多路径下的去重与归属。",
         "paths", lambda: _benchmark("path_network"), offset=0.06,
         expect_min_crossings=100,
         look_for="密集格点里每个交叉的上下是否互不矛盾、有没有整片区域被漏画。",
         tags=("多路径", "27 路径")),

    # --- index --------------------------------------------------------------
    Case("index-circle-lines", "index", "圆 + 对角线",
         "索引场景基线：一个闭合圆与一条穿过它的对角线。",
         "paths", lambda: _index("circle_and_lines"), offset=0.12,
         expect_min_crossings=2, tags=("闭合路径",)),
    Case("index-concurrent-fan", "index", "共点扇（12 条线过同一点 + 圆）",
         "13 条路径全部经过同一点：多线共点的聚类必须保持有界，且不发明唯一上下顺序。",
         "paths", lambda: _index("concurrent_fan"), offset=0.08,
         expect_any_diagnostics=("GEOM-MULTIWAY-CROSSING",),
         look_for="中心那一团是否被如实报成多线共点（而不是硬画出一个交叉），圆边上的交叉是否正常。",
         tags=("多线共点", "13 路径")),
    Case("index-self-intersecting", "index", "Lissajous 3:2（481 点）",
         "索引场景里的自交路径：交叉沿路径顺序交替排列。",
         "paths", lambda: _index("self_intersecting"), offset=0.09,
         expect_min_crossings=4, tags=("自交",)),
    Case("index-crossing-lines", "index", "三条互相交叉的直线",
         "三条直线两两相交于三点：最朴素的多路径交叉。",
         "paths", lambda: _index("crossing_lines"), offset=0.13,
         expect_crossings=3, tags=("直线",)),
    Case("index-parallel-lines", "index", "8 条平行长线（网格最坏情况）",
         "长细段的包围盒让均匀网格几乎无法区分，剪枝退化的同时结果必须一字不差。",
         "paths", lambda: _index("parallel_lines"), offset=0.05,
         expect_crossings=0,
         look_for="八条平行丝带是否各自完整、有无被误判为交叉或互相切口。",
         tags=("平行", "网格退化")),
    Case("index-random-walks-6", "index", "随机游走 6 条（固定种子）",
         "固定种子 20261015 的随机游走：无序输入下的稳定性。"
         "本案例是页面上最能摊出引擎性能的一例：boolean 区域后端曾在这类输入上实测超过 5 分钟、"
         "峰值内存 1.7GB，当时这一行只跑 stroke 与 arrangement。孔洞展开的死循环修掉之后"
         "boolean 降到 0.50s——比 arrangement 的 0.9s 还快——所以三个通道全部纳入。",
         "paths", lambda: _index("random_walks_6"), offset=0.07,
         expect_any_diagnostics=("REGION-AREA-MISMATCH", "REGION-CONFLICTING-OVERLAP",
                                 "REGION-DROPPED-SLIVER", "REGION-LENS-APPROXIMATION",
                                 "REGION-OFF-CROSSING-OVERLAP"),
         look_for="48 处交叉里有大量近切：arrangement 后端报面积不守恒与透镜近似，"
                  "并有 0 段缺口从未被描到，但仍保留 40 个可见悬空描边端头"
                  "（audit.dangling_ends）——长切弦残余是真实缺陷、需要人眼定位；"
                  "也看三个通道的上下关系是否一致。",
         tags=("随机游走", "固定种子", "引擎性能问题")),
    Case("index-random-walks-12", "index", "随机游走 12 条（固定种子）",
         "12 条更短步长的随机游走，交叉更多；boolean 后端曾同样病态（>4 分钟未跑完），"
         "现在是 1.06s，同样三个通道全部纳入。",
         "paths", lambda: _index("random_walks_12"), offset=0.07,
         expect_any_diagnostics=("REGION-AREA-MISMATCH", "REGION-CONFLICTING-OVERLAP",
                                 "REGION-DROPPED-SLIVER", "REGION-LENS-APPROXIMATION",
                                 "REGION-OFF-CROSSING-OVERLAP"),
         look_for="与 6 条那张对照：交叉更多时各后端的归属与缺口是否仍然自洽。"
                  "实测这一张的 arrangement 通道有一个真实缺陷签名："
                  "audit.dangling_ends 报出 62 个悬在丝带内部、没接上任何描边的端头，"
                  "正是需要人眼定位的东西。",
         tags=("随机游走", "固定种子", "引擎性能问题", "已知缺陷签名")),
    Case("index-repeated-points", "index", "重复点与零长边的折线",
         "含重复顶点与零长步的路径：清洗不能误删真实拐角。实测三个通道都报共线重叠与近切"
         "（这两条路径本身共线且几乎相切），交叉数 3。",
         "paths", lambda: _index("repeated_points_zigzag"), offset=0.1,
         expect_diagnostics=("GEOM-COLLINEAR-OVERLAP", "GEOM-NEAR_TANGENT"),
         look_for="重复点处有没有出现零宽度的碎片面或多余描边。",
         tags=("退化输入", "重复点")),
    Case("index-mixed-scale", "index", "尺度悬殊（长线 + 半径 0.01 的圆）",
         "同一场景里相差三个数量级的几何：容差不能只顾一头。实测两个 ribbon 后端都会报"
         "（boolean 面积不守恒、arrangement 面归属冲突），而 stroke 通道 0 诊断。",
         "paths", lambda: _index("mixed_scale"), offset=0.02,
         expect_any_diagnostics=("REGION-AREA-MISMATCH", "REGION-CONFLICTING-OVERLAP"),
         look_for="微小圆是否被压成看不见的碎片、长线是否因此出现伪切口。",
         tags=("尺度悬殊",)),

    # --- degenerate ---------------------------------------------------------
    Case("deg-bow", "degenerate", "领结（单条路径自交一次）",
         "一条开放路径自己交叉一次：自交的两次经过必须各自成为独立的一遍。",
         "paths", lambda: _deg_bow(), offset=0.15,
         expect_crossings=1, expect_self_crossings=1, tags=("自交",)),
    Case("deg-figure-eight", "degenerate", "八字（闭合自交）",
         "一条闭合八字曲线，曲线从交点起、又回到交点：那个自交的弧长是 0.00 与 4.71"
         "（长度 9.429 的一半），也就是**交点正落在闭合接缝上**。这里正是交叉去重最容易漏"
         "的地方——接缝那一点对一个事件是弧长 0、对另一个是弧长 L，按相同角色比对就会被当成"
         "两个事件，于是凭空冒出一个共点交叉和一条无法满足的交替约束。实测原来确实如此"
         "（自报 REGION-COINCIDENT-CROSSINGS 与 REGION-DRAW-ORDER-CYCLE）；按弧长取模去重"
         "之后只剩 1 个交叉、0 诊断，两个后端也不再需要对照。",
         "paths", lambda: _deg_figure_eight(), offset=0.09,
         expect_crossings=1, expect_self_crossings=1,
         # Regression guard: both of these only ever appeared because the crossing sits on
         # the seam and was counted twice.
         forbid_diagnostics=("REGION-COINCIDENT-CROSSINGS", "REGION-DRAW-ORDER-CYCLE"),
         tags=("自交", "闭合路径", "接缝去重")),
    Case("deg-pentagram", "degenerate", "五角星 {5/2}（5 处自交，严格交替）",
         "沿路径数下去是 10 遍（偶数），所以严格交替可解：五个自交点都应有确定上下关系。",
         "paths", lambda: _deg_pentagram(), offset=0.12,
         expect_crossings=5, expect_self_crossings=5,
         forbid_diagnostics=("TOPOLOGY-ALTERNATION-UNSAT", "REGION-AREA-MISMATCH"),
         look_for="五个自交处的切口是否干净、有没有横穿丝带的接缝线。",
         tags=("自交", "闭合路径", "交替可解")),
    Case("deg-pentagram-free", "degenerate", "五角星（自由模式对照）",
         "同一几何换成 free 模式：侧别按交叉 ID 交替，不保证逐条路径交替。",
         "paths", lambda: _deg_pentagram(), offset=0.12, weave_mode="free",
         expect_crossings=5,
         look_for="与严格交替那张对照，看自由模式是否真的更差、还是只是分配不同。",
         tags=("自交", "自由模式")),
    Case("deg-circle-line", "degenerate", "圆 + 直线（接缝落在交点上）",
         "闭合路径的接缝正好与交叉重合：切口与接缝不能互相吃掉。",
         "paths", lambda: _deg_circle_line(), offset=0.16,
         expect_crossings=2,
         look_for="接缝那一侧有没有出现对接的两个平头端面（细缝）或多余的一段。",
         tags=("闭合路径", "接缝")),
    Case("deg-three-lines-vertical", "degenerate", "三横一竖（奇偶交替）",
         "垂直线穿过三条水平线：交替解应当是上—下—上，不能连着两次同侧。",
         "paths", lambda: _deg_three_lines_vertical(), offset=0.15,
         expect_crossings=3,
         forbid_diagnostics=("TOPOLOGY-ALTERNATION-UNSAT",),
         look_for="竖线是否严格一上一下一上；三张图（本案例的三通道）是否一致。",
         tags=("交替", "4 路径")),
    Case("deg-collinear-overlap", "degenerate", "共线重叠线段",
         "两段共线且部分重叠：不存在横穿交叉，引擎必须拒绝发明上下关系。",
         "paths", lambda: _deg_collinear_overlap(), offset=0.14,
         expect_crossings=0,
         expect_diagnostics=("GEOM-COLLINEAR-OVERLAP",),
         look_for="重叠段是否只是两条并排丝带、没有被硬切出一个交叉。",
         tags=("共线重叠", "拒绝发明")),
    Case("deg-t-junction", "degenerate", "T 型端点接触",
         "一条股线的端点正好落在另一条上：这是一个被检出并如实分类的事件"
         "（kind=endpoint_touch，实测 1 个），默认不进入严格交替求解，因此那里不切口。",
         "paths", lambda: _deg_t_junction(), offset=0.14,
         expect_crossings=1,
         expect_diagnostics=("GEOM-ENDPOINT_TOUCH",),
         look_for="T 型接触处有没有被当成普通交叉切口（默认不该切）；竖线端头应被横线丝带"
                  "盖住，不该露出半个带宽的端头；把 event_policy 设成 weave 时同一个输入会真的织起来。",
         tags=("端点接触",)),
    Case("deg-near-tangent", "degenerate", "真近切（sinθ ≤ 1e-7）",
         "两条几乎完全平行的股线在中间相交一次：这是唯一会得到 kind=near_tangent 的构造"
         "（要求 sinθ ≤ angle_tol×10 = 1e-7，且交点不在端点，且另一条线到本线的垂距大于 "
         "position_tol，否则会被判成共线重叠）。画面聚焦在交点附近，"
         "否则那条为了压出极小夹角而拉长到 2e4 的股线会把交点评成一个像素。",
         "paths", lambda: _deg_near_tangent(), offset=0.14,
         expect_crossings=1,
         expect_diagnostics=("GEOM-NEAR_TANGENT",),
         focus=(0.0, 0.0, 3.0),
         look_for="近切处是否只有几何、没有被硬切出一个普通交叉（默认不进入交替求解）；"
                  "看两支丝带在极浅角下是否仍然各自完整。",
         tags=("近切", "退化分类")),
    Case("deg-shallow-angle", "degenerate", "浅角横穿（sin≈0.025）",
         "两条几乎平行的线交叉。注意两件事不同：事件分类里的 near_tangent 要求 "
         "sinθ ≤ angle_tol×10 = 1e-7（几乎完全平行），所以这里是一个普通横穿事件；"
         "而切口必须被 min_sin 钳制，stroke 通道实测报 RENDER-SHALLOW-ANGLE-APPROXIMATION。",
         "paths", lambda: _deg_shallow_angle(), offset=0.14,
         expect_crossings=1,
         expect_any_diagnostics=("RENDER-SHALLOW-ANGLE-APPROXIMATION",),
         look_for="浅角处切口是否被限制、有没有出现一大片被挖空的区域；"
                  "两个 ribbon 通道没有任何诊断，是否说明它们本来就不需要钳制。",
         tags=("近切", "浅角")),
    Case("deg-multiway-fan", "degenerate", "多线共点（4 条过一点）",
         "四条股线共用一点：不存在唯一的二元上下关系，只能诊断。",
         "paths", lambda: _deg_multiway_fan(), offset=0.12,
         expect_any_diagnostics=("GEOM-MULTIWAY-CROSSING",),
         tags=("多线共点",)),
    Case("deg-degenerate-path", "degenerate", "零长路径 + 正常线",
         "一条长度为 0 的路径必须被明确上报，不能静默丢弃。",
         "paths", lambda: _deg_degenerate_path(), offset=0.12,
         expect_diagnostics=("GEOM-DEGENERATE-PATH",),
         look_for="正常那条线是否完全不受影响；诊断里是否点名了零长路径。",
         tags=("退化路径",)),
    Case("deg-fully-cut", "degenerate", "整条被切（切口吞掉整条股线）",
         "被压的那条短股线整条落在切口范围内：stroke 后端不输出任何片段并报 "
         "RENDER-PATH-FULLY-CUT，而不是画出一段反向的碎片或悄悄消失。",
         "paths", lambda: _deg_fully_cut(), offset=0.6,
         expect_diagnostics=("RENDER-PATH-FULLY-CUT",),
         look_for="被压那条短股线是否只剩上股丝带盖住的一块（stroke 通道只剩上股一个片段），"
                  "诊断是否点名了整条被切。",
         tags=("整条被切", "大偏移")),
    Case("deg-thin-wedge", "degenerate", "薄楔三角形（偏移塌陷）",
         "三角形的高小于丝带半宽：偏移轮廓必然自交或塌陷，必须受控修复或诊断。"
         "实测 boolean 后端在这条薄楔上报 REGION-AREA-MISMATCH（面积守恒降级为警告）。",
         "paths", lambda: _deg_thin_wedge(), offset=0.25,
         expect_any_diagnostics=("REGION-AREA-MISMATCH", "REGION-INVALID-OUTLINE",
                                 "REGION-DROPPED-SLIVER"),
         look_for="楔尖是否被画成一个畸形的块或反向的尖刺；诊断是否说明修复过。",
         tags=("偏移塌陷", "薄楔")),
    Case("deg-square-miter", "degenerate", "方形拐角：miter 连接",
         "偏移连接方式 miter：尖角最长，受 miter_limit 钳制。",
         "paths", lambda: _deg_square(), offset=0.12, engine={"join": "miter"},
         expect_crossings=2,
         look_for="四个直角外侧是否拉出长尖；有没有超过 miter_limit 的夸张尖刺。",
         tags=("连接策略", "miter")),
    Case("deg-square-bevel", "degenerate", "方形拐角：bevel 连接",
         "偏移连接方式 bevel：直角被切平，面积最小。",
         "paths", lambda: _deg_square(), offset=0.12, engine={"join": "bevel"},
         expect_crossings=2,
         look_for="与 miter/round 对照，直角外侧是否被平整地切掉一块（不该有尖、不该有弧）。",
         tags=("连接策略", "bevel")),
    Case("deg-square-round", "degenerate", "方形拐角：round 连接",
         "偏移连接方式 round：直角被圆弧取代。",
         "paths", lambda: _deg_square(), offset=0.12, engine={"join": "round"},
         expect_crossings=2,
         look_for="圆弧是否真的圆滑（离散采样痕迹）、半径是否等于丝带半宽。",
         tags=("连接策略", "round")),

    # --- adapter ------------------------------------------------------------
    Case("adp-circle-line", "adapter", "Manim Circle + Line",
         "最常见的输入：一个闭合圆与一条直线，走 VMobject → 路径提取。",
         "manim", _adapter_circle_line, offset=0.16,
         expect_crossings=2, tags=("VMobject", "贝塞尔")),
    Case("adp-two-lines", "adapter", "两条 Manim Line",
         "两条直线对象的提取与交叉：最小对照。",
         "manim", _adapter_two_lines, offset=0.14,
         expect_crossings=1, tags=("VMobject", "直线")),
    Case("adp-parametric", "adapter", "ParametricFunction（Lissajous 3:2）",
         "参数曲线对象：贝塞尔采样 + 来源曲线探针 + 交叉精化都会用到。",
         "manim", _adapter_parametric, offset=0.09,
         expect_min_crossings=4, tags=("ParametricFunction", "精化")),
    Case("adp-arc-polygon", "adapter", "Arc 与 RegularPolygon",
         "圆弧与正多边形：非直线的两种基础矢量对象。半径刻意选在五边形的内切圆半径与外接圆"
         "半径之间（1.35 对 1.5），否则圆弧整条落在多边形内或外，一个交叉都不会有。"
         "实测三个通道都是 8 个横穿；两个 ribbon 后端各自报一个诊断（boolean 面积不守恒、"
         "arrangement 归属冲突），stroke 通道干净。",
         "manim", _adapter_arc_polygon, offset=0.1,
         expect_crossings=8,
         expect_any_diagnostics=("REGION-AREA-MISMATCH", "REGION-CONFLICTING-OVERLAP"),
         tags=("Arc", "Polygon")),
    Case("adp-pentagram-vmobject", "adapter", "手工折线五角星（set_points_as_corners）",
         "用 set_points_as_corners 造的点布局：不能把折线顶点误当贝塞尔控制柄。",
         "manim", _adapter_pentagram_vmobject, offset=0.12,
         expect_crossings=5, tags=("点布局", "自交")),
    Case("adp-nested-vgroup", "adapter", "嵌套 VGroup（递归与去重）",
         "VGroup(VGroup(Circle), Line)：父对象与子对象不能重复收集同一批点。",
         "manim", _adapter_nested_vgroup, offset=0.11,
         expect_crossings=2,
         look_for="有没有出现同一条圆被画了两遍（重影/双倍线宽）。",
         tags=("VGroup", "去重")),
    Case("adp-arc-overlapping", "adapter", "Arc 超过一整圈（自我重叠）",
         "`Arc(angle=3π)` 画一圈半，后半个圈把前半个圈原路重走一遍——这是自我重叠而不是"
         "自交。实测 stroke 通道报出 175 个事件（其中大量是共线重叠与端点接触噪声），"
         "并让整条圆弧被切光（RENDER-PATH-FULLY-CUT）；两个 ribbon 后端原本超过 60 秒"
         "跑不完、峰值内存 2.7GB，现在都能跑完但仍是目录里最慢的一项：boolean 17.7 秒、"
         "arrangement 8.3 秒，比第二名贵一个数量级。这是一个很普通会写出来的输入，"
         "因此页面必须说出来而不是假装它平平无奇。",
         "manim", _adapter_arc_overlapping, offset=0.1,
         omitted=(
             ("boolean", "实测 solve 17.7 秒（同一输入 stroke 1.1s 出 175 个事件），仍是目录里"
                         "最贵的一项，属引擎侧性能问题，本轮不纳入"),
             ("arrangement", "实测 solve 8.3 秒（同 boolean 的输入，比 boolean 快但仍是第二贵），"
                             "属引擎侧性能问题，本轮不纳入"),
         ),
         expect_min_crossings=150,
         expect_any_diagnostics=("RENDER-PATH-FULLY-CUT",),
         annotate=False,
         look_for="被整整切光的圆弧是否只剩两条端头、直线是否完整；"
                  "以及「一圈半的圆弧算不算合法输入」这个问题——目前引擎接受它，代价在上面那行。",
         tags=("Arc", "自我重叠", "引擎性能问题")),
    Case("adp-nonplanar", "adapter", "非共面路径（必须报错）",
         "坐标带 z 且不共面：默认必须抛错，除非显式要求投影。",
         "error", _adapter_nonplanar, offset=0.12,
         expect_error="not in an XY plane",
         look_for="这是「必须失败」的案例：页面不该有图，程序判定应显示原始错误文本。",
         tags=("必须失败",)),
    Case("adp-missing-geometry", "adapter", "无几何点的 Mobject（必须报错）",
         "普通 Mobject 没有矢量点：必须给出可理解的错误，而不是生成空图案。",
         "error", _adapter_missing_geometry, offset=0.12,
         expect_error="no vector points",
         look_for="同样是「必须失败」案例：确认错误信息能被人读懂。",
         tags=("必须失败",)),

    # --- gallery ------------------------------------------------------------
    Case("gal-circle-line", "gallery", "圆与直线",
         "画廊卡片「圆与直线」的同一份源几何，换成统一配色与线宽。",
         "manim", lambda: _gallery("build_circle_line"),
         tags=("画廊", "2 路径")),
    Case("gal-sine-line", "gallery", "正弦曲线与直线",
         "正弦三周期与水平线反复相交，两端正好压在直线上（端点接触）。",
         "manim", lambda: _gallery("build_sine_line"),
         look_for="两端那两个端点接触是否被如实标为接触而不是硬切；中间七个交叉是否逐次交替。",
         tags=("画廊", "端点接触")),
    Case("gal-trefoil", "gallery", "三叶结（3 个圆）",
         "三个互相交叠的圆构成三叶结拓扑。",
         "manim", lambda: _gallery("build_trefoil"),
         tags=("画廊", "3 路径")),
    Case("gal-star", "gallery", "五角星（{5/2}）",
         "一条闭合路径自交五次；与 deg-pentagram 同几何，但经画廊 builder 走 VGroup。",
         "manim", lambda: _gallery("build_star"),
         expect_crossings=5, tags=("画廊", "自交")),
    Case("gal-spiral", "gallery", "螺旋与直线",
         "阿基米德螺线绕约 3.5 圈穿过水平线：严格交替无法全程成立，两处被放宽。",
         "manim", lambda: _gallery("build_spiral"),
         expect_any_diagnostics=("TOPOLOGY-ALTERNATION-RELAXED",),
         look_for="被放宽的那两处交叉是否看起来仍然合理、诊断是否点名了它们。",
         tags=("画廊", "放宽")),
    Case("gal-grid", "gallery", "四圆格栅（2×2 圆）",
         "相邻圆两两相交（8 交叉），对角方向互不接触。",
         "manim", lambda: _gallery("build_grid"),
         tags=("画廊", "4 路径")),
    Case("gal-cross", "gallery", "十字格栅（三横一竖）",
         "四条直线的四路交叉节点。",
         "manim", lambda: _gallery("build_cross"),
         tags=("画廊", "4 路径")),
    Case("gal-infinity", "gallery", "双纽线与直线（共点交叉）",
         "曲线自交点与直线的交点落在同一点：那份卡片声明了 free 模式。",
         "manim", lambda: _gallery("build_infinity"),
         expect_any_diagnostics=("REGION-COINCIDENT-CROSSINGS", "REGION-AREA-MISMATCH"),
         look_for="共点那一处：两个交叉互相反向扣除会让覆盖面积不守恒，看画面是否真的缺了一块；"
                  "arrangement 通道在共点处可能留下一段半明半暗的透镜边（先画的分段描、被后画的盖住一半）。",
         tags=("画廊", "共点交叉", "自交")),
    Case("gal-chain", "gallery", "链条（3 个交错圆）",
         "三个交错排列的圆模拟链环。",
         "manim", lambda: _gallery("build_chain"),
         tags=("画廊", "3 路径")),

    # --- rosette ------------------------------------------------------------
    Case("ros-n10-pa-l12-o08", "rosette", "n=10 PA 阶 1+2（offset 0.08）",
         "本仓库最常被引用的玫瑰线编织：3 条闭合自交股线、70 交叉（20 处自交），严格交替全解。",
         "paths", lambda: _rosette_source(10, (1, 2), "PA"), offset=0.08,
         expect_crossings=70, expect_self_crossings=20,
         forbid_diagnostics=("TOPOLOGY-ALTERNATION-UNSAT",),
         look_for="弧线尖端处（rose 花瓣尖端）有没有被戳进去的描边、丝带中间有没有断线。",
         tags=("玫瑰线", "70 交叉", "密集")),
    Case("ros-n7-ca-l2-o10", "rosette", "n=7 CA 阶 2（offset 0.10）",
         "收敛尖端型：交叉的两刀正好落在丝带侧边上，是历史缺陷命中过的配置。",
         "paths", lambda: _rosette_source(7, (2,), "CA"), offset=0.10,
         expect_self_crossings=None,
         look_for="尖端处接缝与切口是否被分清（以前这一处把一条边同时判成接缝和切口）。",
         tags=("玫瑰线", "历史缺陷配置")),
    Case("ros-n11-cr-l2-o07", "rosette", "n=11 CR 阶 2（offset 0.07）",
         "细长花瓣：薄楔形的楔尖曾经被当成噪声折返整块删掉，这里是回归图。",
         "paths", lambda: _rosette_source(11, (2,), "CR"), offset=0.07,
         look_for="花瓣尖端是否完整（有没有一整块楔形消失）、外轮廓是否有缺口。",
         tags=("玫瑰线", "历史缺陷配置")),
    Case("ros-n10-pa-l12-o05", "rosette", "n=10 PA 阶 1+2（细丝带 offset 0.05）",
         "与第一张同源同解，只把半宽减半：透镜整个落在被压丝带内部。这一张是本轮查出的"
         "真实缺陷，现已修复：boolean 后端曾报 painted_area 37.702956，而它自己 161 个区域的"
         "面积之和只有 10.183419——比自身之和还大 3.7 倍，数学上不可能，而当时的自检只查 "
         "painted < 参考面积，所以它从不报 REGION-AREA-MISMATCH，是个静默的错误数字。"
         "现在两个后端都是 painted_area = union_area = region_area_sum = 10.183419，"
         "并且 render_region_geometry 补上了反向自检（并集不可能大于各部件面积之和），"
         "再出现这种数会自己报出来，而不是等审查页面去查。",
         "paths", lambda: _rosette_source(10, (1, 2), "PA"), offset=0.05,
         expect_crossings=70,
         look_for="薄丝带下切口是否仍然守恒；这一档的画面看不出问题，"
                  "错的是面积那本账而不是图——账已对上，图对不对仍要人眼看。"
                  "这正是两层都要有的理由：程序查账、人眼看图，各自能发现对方看不见的东西。",
         tags=("玫瑰线", "细丝带", "面积记账缺陷")),
    Case("ros-n5-ca-l2-o12", "rosette", "n=5 CA 阶 2（offset 0.12，已知退化）",
         "文档承认的共点交叉退化配置：boolean 报共点交叉与面积不平衡，arrangement 报透镜近似。"
         "本轮页面复现出与仓库审计脚本完全相同的数字：boolean 通道 "
         "audit.dangling_ends 17 处，arrangement 通道 audit.dangling_ends 4 处"
         "（见 CHANGELOG 里 n5 CA L2 o12 那一行）——两边独立得到同一组数字，"
         "说明判定链条是可信的。",
         "paths", lambda: _rosette_source(5, (2,), "CA"), offset=0.12,
         channels=("stroke", "boolean", "arrangement", "hybrid"),
         expect_any_diagnostics=("REGION-COINCIDENT-CROSSINGS", "REGION-LENS-APPROXIMATION"),
         look_for="各 ribbon 图各自错在哪：是缺口、是断头、还是上下关系与另一张不同。"
                  "这是最需要人眼、程序判不了的一张。"
                  "hybrid 面板在这里应当和 boolean 完全一致：那 6 条横切口"
                  "（长度都是 0.24 = 2 * offset，整条横贯丝带）现在由共享的 flush 判据在"
                  "两个通道上都判掉了，hybrid 自己没有额外要补的（bridge 0、patch 0），"
                  "摆着它是为了让「判据在两条通道上结果相同」这件事本身可见。"
                  "注意共点交叉的退化根因（共点归属与面积记账）在这两个面板里都还在，"
                  "本判据只去掉多余的内部描边，不修退化本身。",
         tags=("玫瑰线", "已知退化", "共点交叉", "已知缺陷签名")),

    # --- implicit -----------------------------------------------------------
    Case("imp-circle", "implicit", "隐式圆 F = x² + y² − 1",
         "独立等值线提取器（marching squares）的最基本情形：一条闭合分支，"
         "96×96 网格一遍就达到 1e-3 的目标误差（实测残差 4.43e-4），"
         "朝向由梯度规则确定为逆时针（把 F < 0 的一侧放在左侧）。",
         "paths", lambda: _implicit(lambda x, y: x * x + y * y - 1.0,
                                    (-2.0, 2.0), (-2.0, 2.0)),
         look_for="圆是否闭合、粗细是否均匀、有没有多出来或断掉的片段。"
                  "这一张是人眼给提取器定标用的：它必须看起来就是一个圆。",
         tags=("隐式曲线", "单分支", "定标")),
    Case("imp-annulus", "implicit", "隐式环 (x²+y²−1)(x²+y²−4)",
         "一个水平集包含两个连通分支：外圈 r=2、内圈 r=1，各自成为一条独立股线，"
         "分支来源（level、网格、分支序号、残差）记录在每条路径的 source.metadata 里。",
         "paths", lambda: _implicit(lambda x, y: (x * x + y * y - 1.0) * (x * x + y * y - 4.0),
                                    (-3.0, 3.0), (-3.0, 3.0)),
         expect_crossings=0,
         look_for="两个同心圈是否各自完整闭合、有没有被错接成一条螺旋线。"
                  "同心圈不该有任何交叉：如果程序报出交叉，那是提取器把两条分支接错了。",
         tags=("隐式曲线", "多分支", "同心")),
    Case("imp-hyperbolas", "implicit", "隐式双曲线 x·y = 0.2",
         "两支互不相交的开曲线：提取器给出两条开分支（各 188 点），"
         "与上面的环一样按连通性拆分，只是不闭合。",
         "paths", lambda: _implicit(lambda x, y: x * y - 0.2, (-3.0, 3.0), (-3.0, 3.0)),
         expect_crossings=0,
         look_for="两支曲线的端头是否停在盒子边界上、有没有在中间被莫名接起来。",
         tags=("隐式曲线", "多分支", "开放曲线")),
    Case("imp-saddle-cross", "implicit", "隐式十字 x·y = 0（退化自触）",
         "水平集是两条坐标轴，它们在原点相交。提取器给出两条分支，但**没有交叉事件**："
         "两条分支在原点附近最近只差 0.707 倍格距而不相接，所以真正的交点没有被表示出来。"
         "鞍点格由双线性中心值裁决，且在中心值恰好等于 level 时配对会随网格翻转"
         "（实测 24/96/192 节点是一种配对、48/384 是另一种）——这一点已写进模块文档。",
         "paths", lambda: _implicit(lambda x, y: x * y, (-2.0, 2.0), (-2.0, 2.0)),
         expect_crossings=0,
         expect_diagnostics=("GEOM-IMPLICIT-AMBIGUOUS-SADDLE",),
         expect_any_diagnostics=("REGION-OVERLAPPING-SECTIONS", "REGION-OFF-CROSSING-OVERLAP"),
         look_for="原点附近：两条丝带是否叠在一起却没有上下关系（这正是交叉缺失的样子）。"
                  "程序说这里 0 个交叉，你看图判断这个缺失是否可接受。",
         tags=("隐式曲线", "退化自触", "已知限制")),
    Case("imp-lemniscate", "implicit", "隐式双纽线 (x²+y²)² = x² − y²",
         "真正的 8 字在原点有一个结点，但提取出来的是一条闭合分支（2109 点），"
         "两条臂最近只差 0.0082，于是**三个通道都报 0 个交叉**——结点处的上下关系整个丢失。"
         "这是本轮实测到的、自触水平集在提取阶段的代价；合上这样的缝隙需要端点吸附容差"
         "（SPEC FR-009/FR-010 + FR-025），本模块不自己猜一个阈值。",
         "paths", lambda: _implicit(lambda x, y: (x * x + y * y) ** 2 - (x * x - y * y),
                                    (-1.5, 1.5), (-1.0, 1.0)),
         offset=0.05,
         expect_crossings=0,
         look_for="原点处两条臂贴得极近：丝带是否合成了一团、有没有产出应有的交叉。"
                  "这一张是「程序给 0、人眼觉得应该是 1」的典型，请直接判定它算不算缺陷。",
         tags=("隐式曲线", "自交丢失", "已知限制")),
    Case("imp-pole", "implicit", "极点 1/(x²+y²−0.25)（假等值线）",
         "F 在框内根本没有零点，唯一的特征是 r=0.5 处的极点：格点值跨过 level，"
         "线性插值于是**造出一条曲线**。局部误差估计抓不到它（极点附近的残差估计也小），"
         "所以提取器用它能控制的那个量如实报警：任何分辨率都达不到目标误差，"
         "GEOM-IMPLICIT-ERROR-TARGET-MISSED 点名超标分支。实测返回的『圆』上 |F|≈400，"
         "而不是 0——它根本不是 F 的等值线。",
         "paths", lambda: _implicit(lambda x, y: 1.0 / (x * x + y * y - 0.25),
                                    (-1.0, 1.0), (-1.0, 1.0)),
         expect_crossings=0,
         expect_diagnostics=("GEOM-IMPLICIT-ERROR-TARGET-MISSED",),
         look_for="画面看上去是一个干净的圆——它并不是 F 的零点集合。"
                  "请对照程序判定里的残差与超标分支：这就是「图好看、账不对」的另一半。",
         tags=("隐式曲线", "极点", "假等值线", "静默风险")),
)

CASES: tuple[Case, ...] = _CASES
CASE_BY_KEY = {case.key: case for case in CASES}


def source_engine_kwargs(source: Source) -> dict[str, Any]:
    """Engine keyword arguments a source implies, in one place.

    Today that is the sampling summaries of a source that sampled its own curve. Both the
    page's renderer and the tests' solver call this, so the two cannot drift into reviewing
    different pipelines — which is exactly what happened first: the page forwarded the
    summaries and the tests did not, so the pole case looked silent in one and warned in the
    other.
    """
    if not source.sampling_trace:
        return {}
    return {"sampling_trace": [dict(summary) for summary in source.sampling_trace]}


def cases_for(category: str) -> tuple[Case, ...]:
    return tuple(case for case in CASES if case.category == category)


def catalog_stats() -> dict[str, int]:
    """Case count per category, for the page header and the tests."""
    return {category.key: len(cases_for(category.key)) for category in CATEGORIES}
