# Manim Lace — 二维矢量路径蕾丝编织引擎

> 版本：`0.1.0`（可运行的开发起点，不是完整 1.0 产品；`main` 上另有未发版改动，见 [CHANGELOG](CHANGELOG.md)）

这是根据 `docs/SPEC.md` 建立的 Python 项目骨架。它遵循需求书中的几个核心原则：

1. 先把不同来源的输入规范化为可追踪的二维路径；
2. 交叉事件与过／欠关系属于拓扑层，不从偏移边交点反向猜测；
3. 拓扑结果与渲染后端分离；
4. 动画轨迹来自真实算法阶段；
5. 未实现的能力显式报告，不伪装成已经完成。

## 当前实现状态

| 能力 | Starter Kit 状态 |
|---|---|
| 纯 NumPy 路径模型 | 已实现 |
| 参数函数 `gamma(t)=(x(t),y(t))` 自适应采样 | 已实现，支持最大参数步长、断点、非有限值切分 |
| 显式图像 `y=f(x)` 采样 | 已实现，跳跃阈值可选 |
| 从 Manim `VMobject` / `VGroup` 读取路径 | 已提供可选适配器，并在 Manim CE `0.22.0` 上实测通过（`tests/test_optional_manim.py`） |
| 中心线段交叉检测 | 已实现基础版：路径间/自交/重叠/端点/多线共点诊断；顶点交叉、闭合缝、重复顶点与退化路径有回归测试 |
| 候选加速与性能基准 | 已实现确定性均匀网格剪枝（`candidate_strategy` 可切换网格/暴力，两者逐事件等价），附四类输入的可复现基准集与事件指纹 |
| 来源曲线上的局部交点精化（FR-036） | 已实现：两侧路径都带可求值来源曲线与来源参数映射时，用阻尼 Newton 解 `gamma_a(t)=gamma_b(u)`，给出曲线参数、真实切向角与曲线弧长；无探针、探针失效、不收敛或路径在该处确实拐折时如实回退到折线估计 |
| 路径级严格交替求解 | 已实现：约束传播 + 冲突的**最小见证环**（奇偶环 / 自交奇偶间隔）+ FR-045 冲突策略开关（`error` 报错不伪造 / `manual` 手动优先并放宽自动约束 / `relax` 保留自动解并放宽无解处） |
| 非横穿候选的事件策略 | 已实现：`event_policy` 可按事件类选择"如实诊断 / 提升为普通横穿（`weave`，仅点状接触）/ 只保留几何不报警告（`ignore`）"；重叠与多线共点只能是诊断或忽略，永不变成二元交叉 |
| 每次交叉手动指定上下关系 | 已实现 `manual` 模式和逐交叉覆盖 |
| Stroke 几何切分 | 已实现基础版：闭合缝切口、整条被切、浅角受限与片段丢弃都有显式诊断和测试；端帽与精确区域裁剪仍属视觉近似 |
| 端帽策略与绘制顺序 | 已实现：`cap_style ∈ {butt, round, square}`（round/square 会按半个线宽加宽断口并报 `RENDER-CAP-EXTENSION`）；每个片段带确定性 `draw_index`（按"被压者先画"分层，环按路径顺序确定性打破，仅在近似断口处报 `RENDER-DRAW-ORDER-CYCLE`），Manim 侧同步 `CapStyleType` 与 `z_index` |
| Manim `Lace` VGroup 封装 | 已提供，并在 Manim CE `0.22.0` 上实机渲染通过（`examples/scene_weave.py`） |
| 基于算法轨迹的动画计划 | 已实现 renderer-neutral trace plan；Manim 动画适配器为初始版本，实机渲染已跑通 |
| 细粒度算法轨迹 | 已完成（M5）：候选对逐条判定、约束传播步骤、自适应细分决策、面域遍历归属全部是真实的 `TraceEvent`，计数精确、记录列表有界（`*_count` / `*_truncated`） |
| 可视化线宽 | 已实现像素对齐换算：`px_to_stroke_width` / `px_to_units`（`render/pixels.py`）在目标输出分辨率和 Manim 画幅高度之间转换，`Lace` 的 `stroke_width_px` 参数直接以输出像素指定线宽；未指定时仍用 `max(1.0, 200.0 * offset)` 启发式 |
| 实体 Ribbon、多边形面域与孔洞 | 已实现两套后端（`ribbon_backend`）：`boolean` 用受验证的布尔几何按"该交叉局部"交集精确切除；`arrangement` 走**平面剖分**——把丝带边界（含自交分段边界）noding 后 `polygonize` 出全部面，逐面判定归属，因此区域**永不重叠**、自交不再需要重叠分段、共点交叉也能守恒。两者输出同样的 `RibbonRegion`/`RegionRing`（带 role、外环逆时针、孔洞顺时针）与面积核对 |
| 美学策略（M6） | 已实现：`manim_lace.style` 提供可插拔调色板（56 色和色色卡 + 7 套配色）、path/piece/layer/degree 分组、边框设计、切口端处理（覆盖余量 + 真实端头轮廓）与密度感知的视觉简化；样式不改变拓扑（`apply_style` 只读结果），密度简化只影响"画哪些片段"且逐条上报 |
| 隐式方程直接等值线提取 | 未实现；可先传入 Manim `ImplicitFunction` 的矢量对象 |
| 鲁棒多线共点分解 | 未实现；当前只能识别并诊断多线共点，不做唯一穿插顺序推断 |

## 安装

建议在项目根目录创建虚拟环境。纯几何核心不依赖 Manim：

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1

python -m pip install -e '.[dev]'
```

如需在 Manim 场景中直接使用 `Lace`（可选依赖约束为 Manim CE `0.22.0`）：

```bash
python -m pip install -e '.[manim,dev]'
```

区域（实体丝带）后端使用 Shapely 做布尔几何；它已包含在开发依赖里，也可以单独安装：

```bash
python -m pip install -e '.[geometry]'
```

`Lace` 是**惰性**模块属性：没装 Manim 也能 `import manim_lace`，此时它不在 `__all__` 里，首次访问才报带安装提示的 `ImportError`；`TYPE_CHECKING` 声明与静态 `__all__` 字面量保证类型检查器和 IDE 仍能解析该名字（契约由 `tests/test_package_api.py` 冻结）。

## 快速开始：纯几何内核

```python
import numpy as np
from manim_lace import LaceEngine

# 两条相交的开放路径。offset 表示丝带半宽。
paths = [
    np.array([[-2.0, -1.0], [2.0, 1.0]]),
    np.array([[-2.0, 1.0], [2.0, -1.0]]),
]
engine = LaceEngine(paths, offset=0.12, weave_mode="alternating")
result = engine.solve()

print("crossings:", len(result.crossings))
print("assignments:", result.topology.assignments)
print("stroke pieces:", len(result.pieces))
print("trace events:", len(result.trace))
```

纯核心结果的数据可用性：

- `result.paths`：规范化路径；
- `result.crossings`：交叉候选及路径弧长位置；精化成功的交叉还会带 `refined=True` 与来源曲线参数 `parameter_a` / `parameter_b`；
- `result.topology.assignments`：每个已解交叉的过／欠分配；
- `result.pieces`：Stroke 后端切分出来的可见折线片段；
- `result.diagnostics`：结构化诊断；
- `result.trace`：实际求解过程留下的结构化轨迹（含细粒度事件：`crossing.candidate_pairs`、`topology.propagation`、`sampling.subdivision`、`region.face_walk`）；
- `result.detection_stats`：候选筛选统计（策略、线段数、候选对数、窄相位次数、网格单元数、暴力上界、精化事件数）。

调试时常用的几个入口：

```python
result = LaceEngine(paths, offset=0.1, weave_mode="free").solve()
print([d.code for d in result.diagnostics])       # 稳定诊断码，见下文表格
print(result.detection_stats)                      # 候选剪枝比与实际判定次数
for event in result.trace:                         # 真实算法阶段，而非事后编故事
    print(event.sequence, event.stage, event.event_type, event.data)
```

细粒度事件只描述真的发生过的步骤，并且对任何输入规模都保持有界：

```python
from manim_lace import LaceEngine, sample_parametric

summaries = []                                     # 采样细分：每个来源曲线一条摘要
paths = sample_parametric(lambda t: (t, t * t), (0.0, 1.0), max_error=1e-6, max_step=0.5,
                          subdivision_tracer=summaries.append)
summary = summaries[0]
# 计数精确（node_count == split + accept + 触顶 + 丢弃），决策列表有界：
print(summary["node_count"], summary["decisions_count"], summary["decisions_truncated"])
print(summary["decisions"][0])                      # {kind, reason, t0, t1, depth, error}

result = LaceEngine(paths, sampling_trace=summaries).solve()    # 交给引擎，事件即写入 trace
subdivision = next(e for e in result.trace if e.event_type == "sampling.subdivision")
print(subdivision.stage, subdivision.data["split_count"])       # input, 真实细分次数

ribbon = LaceEngine(paths, render_mode="ribbon", ribbon_backend="arrangement").solve()
walk = next(e for e in ribbon.trace if e.event_type == "region.face_walk").data
print(walk["backend"], walk["node_kind"], walk["owner_count"], walk["steps"][0]["decision"])
```

`LaceEngine.from_parametric` / `from_graph` 会自动把采样摘要带进引擎，所以 `Lace.from_parametric(...).build_animation(mode="algorithm")`
能把真实的"细分了多少个递归节点"与"面域遍历归给几条股线"直接打在画面上；`sampling.subdivision` 记录在 `input` 阶段，
`region.face_walk` 记录在 `construction` 阶段，都不新增阶段，动画计划的时长与模式归属不变。

`LaceEngine(..., candidate_strategy="brute_force")` 可作为参照实现：它与默认网格策略必须给出**相同的交叉事件、诊断与片段几何**，若不一致即为缺陷。

精化结果是可选的增强，不是新的交叉来源：

```python
result = LaceEngine.from_parametric(lambda t: (np.cos(t), np.sin(t)), (0, 2*np.pi),
                                    closed=True, refine=True).solve()
for event in result.crossings:
    if event.refined:                       # 已在来源曲线上求解
        print(event.crossing_id, event.parameter_a, event.parameter_b, event.sin_angle)
```

非横穿候选与严格交替冲突各有显式策略（默认：如实诊断 + 报错不伪造）：

```python
from manim_lace import EventPolicy, LaceEngine

result = LaceEngine(
    paths,
    event_policy=EventPolicy(endpoint_touch="weave"),   # 把 T 型接触真正织进去
    conflict_strategy="manual",                         # 手动指定优先，放宽矛盾的自动约束
    manual_over={"X0000": "b"},
).solve()
relaxed = [a.crossing_id for a in result.topology.assignments.values() if a.source == "relaxed"]
```

## 直接从数学曲线开始

```python
import numpy as np
from manim_lace import LaceEngine

engine = LaceEngine.from_parametric(
    lambda t: (np.cos(3*t), np.sin(2*t)),
    (0, 2*np.pi),
    offset=0.08,
    max_error=0.002,
    max_step=0.01,
    closed=False,
)
result = engine.solve()
```

显式函数使用 `LaceEngine.from_graph(lambda x: np.sin(x), (-4, 4), ...)`。函数在不连续点附近时，优先显式传入 `breakpoints`；`jump_threshold` 只能作为用户可控的启发式断线规则，不保证自动识别所有奇点。

## Manim 场景示例

安装 `.[manim]` 后可运行：

```bash
manim -pql examples/scene_weave.py WeaveDemo
```

核心用法是（与 `examples/scene_weave.py` 一致）：

```python
from manim import *
from manim_lace import Lace

class WeaveDemo(Scene):
    def construct(self):
        source = VGroup(
            ParametricFunction(lambda t: np.array([t, 0.9*np.sin(1.5*t), 0]),
                               t_range=[-3, 3], color=GREY_B),
            Line(LEFT*3 + UP*1.1, RIGHT*3 + DOWN*1.1, color=GREY_B),
        )
        lace = Lace(source, offset=0.12, render="stroke", weave_mode="free", stroke_color=TEAL)
        self.play(lace.build_animation(mode="algorithm", show_sampling=True))
        self.wait()
```

### 像素对齐线宽

Manim 的 `stroke_width` 随画幅和输出分辨率变化，不是像素单位。`render/pixels.py`
提供了在两者之间换算的工具，`Lace` 的 `stroke_width_px` 参数直接按输出像素指定线宽：

```python
from manim_lace.render.pixels import px_to_stroke_width, px_to_units

# 在 1080p、画幅高 6.0 的场景中画 2 像素粗的线
sw = px_to_stroke_width(2.0, pixel_height=1080, frame_height=6.0)
# 或直接在 Lace 上指定
lace = Lace(source, offset=0.12, stroke_width_px=2.0, pixel_height=1080, frame_height=6.0)
```

### 动画坐标一致性验证

```python
from manim_lace.animation import verify_coordinate_consistency

result = lace.result
report = verify_coordinate_consistency(result)
print(report.consistent)            # True = 动画高亮与最终几何坐标和 ID 一致
print(report.mismatches)            # 不一致项列表（crossing_id, traced_point, canonical_point）
```

### 可配置动画计划

```python
from manim_lace.animation import build_animation_plan, DEFAULT_STAGE_DURATIONS

plan = build_animation_plan(result, mode="algorithm", durations={"input": 3.0})
# 也可覆盖某阶段出现在哪些模式中
plan = build_animation_plan(result, mode="overview",
                            stage_modes={"crossings": ("overview", "construction")})
```

`Lace` 是可加入 `Scene` 的 `VGroup`。适配器依据 Manim CE 的 `VMobject.get_subpaths()` / 四点三次贝塞尔结构开发（参见 [Manim 官方 VMobject 文档](https://docs.manim.community/en/stable/reference/manim.mobject.types.vectorized_mobject.VMobject.html)）。

同一个输入换成有面积的区域后端（需要 `pip install 'manim-lace[geometry]'`）：

```python
ribbon = Lace(
    source, offset=0.12, render="ribbon",
    stroke_color=TEAL, fill_color=TEAL, hole_color=BLACK,
)
scene.add(ribbon.ribbons, ribbon.holes)   # 孔洞是独立图层，便于按背景色处理
for region in sorted(ribbon.result.pieces, key=lambda r: r.draw_index):   # 绘制顺序
    print(region.region_id, round(region.area, 4), [hole.role for hole in region.holes])
```

**实测状态**：本仓库 `.venv` 中安装的是 Manim CE `0.22.0`，上面这条命令已实机渲染通过（输出 `media/videos/scene_weave/480p15/WeaveDemo.mp4`），`tests/test_optional_manim.py` 的 VMobject→路径提取也真实执行而非跳过。像素对齐换算已实现（见 `render/pixels.py` 的 `px_to_stroke_width` / `px_to_units`）。本项目只支持 Manim CE `0.22.0`，不维护旧版本兼容矩阵。

`build_animation(mode=...)` 支持 `overview` / `algorithm` / `construction` / `debug` / `custom`，阶段划分来自 `result.trace` 记录的真实算法阶段（见 `docs/ALGORITHM_TRACE.md`）；未知模式会抛 `ValueError`，不会静默给出一段空动画。`build_animation` 还接受 `durations` 和 `stage_modes` 关键字参数来覆盖各阶段时长和模式归属（与 `build_animation_plan` 一致），每个 Manim 动画的 `run_time` 由计划中该阶段的 `duration` 派生，不再硬编码。

## 美学策略（M6）

样式层在 `manim_lace.style`，是**不依赖 Manim 的纯数据 / 纯几何层**：它读取已经求解好的结果，决定"怎么画"，不参与交叉识别与上下关系求解。`apply_style` 返回一份 `StylePlan` 而不修改 `result`（`tests/test_style_policy.py` 冻结了交叉、上下关系与片段坐标）。

```python
from manim_lace import LaceEngine
from manim_lace.style import (
    BorderSpec,
    DensityPolicy,
    StylePolicy,
    analyze_density,
    apply_style,
    build_border,
    simplify_for_density,
    stroke_piece_outline,
)

result = LaceEngine(paths, offset=0.12).solve()

plan = apply_style(result, StylePolicy(palette="haru", group_by="path"))
print(plan.colors())                       # 每条路径一个和色
print(plan.assignment_for(result.pieces[0].piece_id).color)

density = analyze_density(result)          # 交叉聚集度：网格计数 + 密集簇
print(density.is_dense, density.hotspots(3), [cluster.size for cluster in density.clusters])
simplified = simplify_for_density(result, DensityPolicy())   # 只隐藏密集区里的极短片段
print(simplified.applied, simplified.dropped_ids)

frame = build_border(result, BorderSpec(margin=0.25, corner="round", radius=0.2, bands=2))
outline = stroke_piece_outline(result.pieces[0], half_width=0.12, cap_style="round")
```

调色板是"色卡 + 命名配色"：`SWATCHES` 是 56 个日本传统色（色名、假名、hex），`PALETTES` 是 7 套配色 —— `haru` 春 / `natsu` 夏 / `aki` 秋 / `fuyu` 冬 / `matsuri` 祭 / `wabi` 侘 / `ayame` 菖蒲，别名（`春`、`spring`、`iris` 等）同样可用。色卡值取自公开的日本传统色名；配色分组参考樱井辉子《日本色彩调和辞典》的季节 / 色调思路，不复刻原书色卡页与配色方案。登记自己的色卡用 `register_palette(...)`，随机取色用 `strand_colors(..., mode="shuffle", seed=...)` 保持可复现。

Manim 侧可以一次给全：

```python
lace = Lace(
    source, offset=0.12, palette="aki", paper=True,
    border=BorderSpec(margin=0.3, corner="round", radius=0.15),
    density_policy=DensityPolicy(), stroke_width_px=3.0,
)
lace.ribbons            # 每片自取调色板颜色（按路径 / 片段 / 绘制层 / 疏密分组）
lace.paper_layer        # 纸张层（z_index=-1，取配色的纸色）
lace.border_layer       # 边框层（默认取配色里最深的颜色，`border_color` 可覆盖）
lace.density            # 密度报告与 kept/dropped 列表；result.pieces 始终是完整几何
```

几条口径：样式**不能**改变交叉与上下关系（FR-062 / AT-018）；`palette` 与 `style_policy` 互斥；**覆盖余量 `cover_allowance` 是几何参数**（它确实改变切口），只允许吃掉切口本来就有的余量 `overshoot`，上限在构造时校验；密度简化只隐藏"落在密集簇内、且短于阈值"的可见片段，并在 `RENDER-DENSITY-SIMPLIFIED` 中逐条列出被隐藏的片段 ID。示例场景见 `examples/scene_style.py`（`PaletteGallery` / `BorderGallery` / `CutEndGallery` / `DensityGallery`）。

## 玫瑰线示例（`examples/rosette.py`）

`examples/rosette.py` 是示例自带的星形玫瑰线几何模块（论文式"核 + 镜像 + 旋转"构造法）：`cal_kernels` 逐阶算出骨架、`get_petals_by_kernel` 镜像并旋转出花瓣、`sort_petals` 按拓扑重排、`merge_adjacent_petals` 合并成连续折线，`StarRosette` 再把结果包成 Manim 的 `Polygram`。**`manim_lace` 自己不导入它**，用法全在示例里：

```bash
manim -pql examples/scene_rosette.py RosetteGallery     # n=10 五种花型（附各自最大可用阶）
manim -pql examples/scene_rosette.py RosetteLevels      # n=10 PA 的第 0~5 阶阶梯
manim -pql examples/scene_rosette.py RosetteConstruction # 核 → 镜像 → 旋转 → 合并
manim -pql examples/scene_rosette.py RosetteWeave        # 玫瑰线交给编织器（三通道）
manim -pql examples/scene_rosette.py RosetteLimits       # 可行域与真实 ValueError 原文
```

两处与仓库自身设定直接相关的地方：

- **可行域是有界的，而且会明说。** 高阶核由"旋转前一阶 + 与 x 轴求交"迭代得到，当旋转后的核线段与 x 轴平行时该阶在数学上不存在，`cal_kernels` 直接抛 `ValueError` 并在消息里给出该组合的最大可用阶，而不是产出 `inf`/`nan` 坐标；偶数 `n` 一律有限（`n = 10` 时 PA/CA 到 5 阶、PR/CR 到 6 阶、PO 到 8 阶），奇数 `n` 宽松得多。`RosetteLimits` 与画廊页面上的表格就是逐阶探测这个边界的真实结果。
- **玫瑰线可以直接喂给编织器。** `merge_adjacent_petals` 的结果是若干条**闭合自交股线**，于是可以当作 `Lace` 的输入：`RosetteWeave` 把 level 1 与 level 2 两朵玫瑰线（共 3 条股线）在 stroke / ribbon(boolean) / ribbon(arrangement) 三个通道里编织。单条路径没法自己压自己，所以 ribbon 后端仍会照例报 `REGION-DRAW-ORDER-CYCLE` 与 `REGION-OVERLAPPING-SECTIONS`（arrangement 后端对同一输入 0 诊断）。

`rosette.py` 与示例同目录、不在安装包内（`src/` 之外，只是示例的支撑模块）：`scene_rosette.py` 通过显式路径导入它，因此从任意工作目录启动场景都能找到，而它随 `examples/` 一起被 `make lint` 与 CI 检查。

## 状态画廊：一眼看清目前做到哪

`media/gallery/index.html` 是把当前代码"摊开给你看"的页面：每个图案都由本仓库实机渲染，**卡片上的每个数字都读自同一次求解真实产生的对象**，不是手写的。页面与所有媒体都落在 `media/` 下（Manim 自己的生成物目录，仓库不跟踪），所以重跑脚本不会在 `examples/` 留下任何未跟踪文件。

```bash
python examples/build_gallery.py                 # 渲染全部媒体 + 重写页面
python examples/build_gallery.py --no-render     # 只重算数据与页面，复用已有媒体
python examples/build_gallery.py -q l            # 更小更快的渲染
```

它覆盖五块：编织图案（ribbon 后端 9 例）、玫瑰线（五种花型、阶数阶梯、构造链、交给编织器、可行域，附逐阶探测出的最大可用阶表）、绘制通道对照（stroke / boolean / arrangement 同输入，附面积核算表）、美学策略（调色板、边框、切口端、密度简化）、算法轨迹（两段动画视频 + 真实事件表 + `sampling.subdivision` 的完整载荷）。末尾还有一张"诊断与诚实降级"表，列出本次渲染实际触发的诊断码、级别、说明与出现在哪张卡片上。

实现方式：脚本用探针记录每个场景 `construct` 期间真正创建的 `Lace`（`play`/`wait`/`add` 被替换为空操作，因此数据采集与渲染是两件事），所以交叉数、可见区域数、面积核算、诊断、配色选择、密度省略数、trace 事件统计全部来自对象本身；编织图案的文案取自 `scene_gallery.GALLERY` 里的 `GalleryEntry`，与场景共用同一处定义。这也是它立刻暴露出两处**内容不实**的原因：四圆格栅原本是四个外切圆（0 交叉），五角星原本不自交——现在两者都是真的编织。

## 运行测试、lint 与基准

```bash
pytest                                  # 纯几何核心 + 可选 Manim 集成测试
ruff check src tests examples benchmarks # 与 CI 一致
python benchmarks/bench_crossings.py --repeat 3
```

或用 `make test` / `make lint` / `make bench` / `make demo`。

未安装 Manim 时纯几何测试仍可运行：集成测试以 `pytest.importorskip("manim")` 开头，会自行跳过。

## 重要语义

- `offset` 表示半宽，因此总几何宽度目标为 `2 * offset`。
- 严格 `alternating` 模式只有在约束相容时才能给出解；若不相容，拓扑对象会携带 `TOPOLOGY-ALTERNATION-UNSAT` 诊断，不会假称已满足严格交替。诊断里的 `crossing_ids` 是**最小见证集合**（每个冲突一条"最短替代路径 + 该约束"构成的奇偶环，或一条两次经过奇偶性相同的自交），不再倾倒整个连通分量。此时可以用 `conflict_strategy` 选择近似解：
  - `error`（默认）：报告见证并返回空分配；
  - `manual`：手动指定变成硬约束（参与奇偶传播），与之矛盾的自动约束被放宽；
  - `relax`：尽量保留自动交替解，只放宽无解处，手动指定仍然覆盖。
  两个放宽策略都会给每个被放宽的交叉写 `source="relaxed"`、按确定性默认值（`a` 侧在上，若用户指定过则用用户值）给出上下关系，并携带 `TOPOLOGY-ALTERNATION-RELAXED` 警告（含见证与 `relaxed_crossing_ids`）。结果不是严格交替编织，但绝不静默。
- 手动指定在可满足时不会破坏交替：`relax`/`error` 下手动值作为覆盖生效，只有**确实与自动解不同**时才报 `TOPOLOGY-MANUAL-OVERRIDE`（info）；`manual` 下它作为硬约束参与传播，邻居交叉随之调整。同一路径上两次互相矛盾的手动指定会报 `TOPOLOGY-MANUAL-CONFLICT`（warning）并保留交叉 ID 较小的一项。
- `event_policy` 决定非横穿候选怎么处理，取值 `"diagnose"`（默认，保留分类并报警告）、`"weave"`（把**点状接触**提升为普通横穿进入过／欠求解，并报 `GEOM-CONTACT-WOVEN`）、`"ignore"`（保留几何与分类，只是不报警告）。可传 `EventPolicy(...)`、字段映射（如 `{"endpoint_touch": "weave"}`）或一个统一取值。共线重叠与多线共点只能是 `"diagnose"`/`"ignore"`：前者是区间、后者超过两条股线，都不存在唯一的二元上／下关系。
- `free` 模式对未手动指定的交叉使用确定性默认分配，但不承诺路径级交替。
- `manual` 模式需要为每个普通横穿交叉提供 `crossing_id: "a" | "b"`；`a` / `b` 分别指该事件数据中的 `path_a` / `path_b` 一侧。自交的两侧仍由不同弧长经过区分。
- 当前 `stroke` 后端针对不透明二维描边的视觉呈现。半透明叠色、浅角遮挡端头的精确几何与真实区域裁剪不在保证范围内。
- `cap_style`（默认 `"butt"`）描述可见端头怎么画：`"butt"` 的几何严格停在切口处；`"round"`/`"square"` 会沿切向多画半个线宽，因此断口会额外加宽 `offset` 并报 `RENDER-CAP-EXTENSION`（info）。端头轮廓现在可以真的取出：`style.caps.stroke_piece_outline` 按端帽样式与 miter 连接算出该片段覆盖的闭合多边形（未切口的闭合中心线输出为带孔环），不再需要猜渲染器怎么画。
- `cover_allowance`（默认 `0`）是**几何**风格参数：每个断口两侧各缩短 `cover_allowance × offset`，让被压股线的端头更靠里、藏到上方股线之下，并报 `RENDER-COVER-ALLOWANCE`。它只能吃掉切口本来就有的余量，因此 `cover_allowance > overshoot` 一律在 `LaceEngine` 构造时抛 `ValueError`（不会画出一个越过真实交叉点的端头）；ribbon 模式下报 `RENDER-COVER-ALLOWANCE-IGNORED`。
- 样式层（`manim_lace.style`）是装饰性的：`StylePolicy` / `apply_style` 只决定颜色、分组与绘制顺序，不重算拓扑（FR-062 / AT-018）。换调色板或换样式策略时，`result.crossings`、`result.topology.assignments` 与全部片段坐标逐位不变；`StylePolicy(piece_order="path")` 这类偏离几何层顺序的重排会报 `STYLE-DRAW-ORDER-OVERRIDE`。
- 密度简化（`DensityPolicy` / `simplify_for_density`）只隐藏"中点落在密集簇内、且弧长短于阈值"的可见片段，隐藏清单、阈值与簇尺度写在 `RENDER-DENSITY-SIMPLIFIED` 里；`result.pieces` 保持完整，实际要画哪些片段由 `simplification.kept(result)` 决定。ribbon 模式（切口是真实几何）报 `RENDER-DENSITY-SKIPPED`，稀疏图案则不产生任何诊断。
- 边框从**可见**几何的包围盒生成（`pattern_bounds`，被完全切掉的片段不会撑大画框），环一律闭合且逆时针；会把边框推进图案内部（`inset` 过大）或圆角半径放不下的配置判为 `ValueError`，不静默近似。
- 每个片段都带确定性 `draw_index`：按"被压路径先画"的路径分层（最长路分层）排序，环按路径顺序确定性打破。两条股线交叉偶数次时"谁先画"必然成环，这是正常编织图案，可见性由切口决定，因此只有环上存在被 `min_sin` 钳制的近似断口时才报 `RENDER-DRAW-ORDER-CYCLE`（info）。Manim 侧按该顺序建组、设置对应 cap 与 `z_index`，不会与几何层不一致。
- `render="ribbon"` 已实现（需要 `pip install 'manim-lace[geometry]'`，即 Shapely；缺失时抛出带安装提示的 `ImportError`）。它把丝带当**有面积的面域**构造：每条路径一条偏移带（`join`/`miter_limit` 控制拐角连接），在交叉处从被压带里扣除"该交叉局部"的 `被压带 ∩ 上方带`——即上方丝带真实覆盖的那块面积，因此没有半径近似、没有浅角钳制，也不需要端帽补偿。`result.pieces` 在 ribbon 模式下是 `RibbonRegion`（外环 + 孔洞环，role 分别为 `exterior` / `source_contour` / `occlusion`，外环逆时针、孔洞顺时针）。两种后端消费**同一份**交叉与拓扑（`FR-040`）。
- ribbon 模式有两套实现，`ribbon_backend="boolean"`（默认）/`"arrangement"`：
  - **`boolean`**：按交叉局部交集切除。对**自交**，同一条带不可能既在上又在下，因此带自交的路径按"经过"拆成**分段**输出，分段在交叉处**互相重叠**（面积之和大于可见面积），上下由 `RibbonRegion.draw_index` 绘制顺序决定（与描边后端同款"顺序兜住"策略），并报 `REGION-OVERLAPPING-SECTIONS`（info）。多个交叉共点时各交叉扣除会互相抵消，覆盖面积不再守恒，报 `REGION-COINCIDENT-CROSSINGS` + `REGION-AREA-MISMATCH`。
  - **`arrangement`**：把全部丝带边界（路径带边界 + 自交分段边界）noding 后剖分成面，每个面按"该处上方的股线"归属唯一所有者——因此区域**永不重叠**（`region_area_sum == painted_area`）、自交的上下关系体现为真实边界、共点交叉仍然守恒（`painted_area == union_area`）。无法从几何唯一确定的面会如实上报：`REGION-CONFLICTING-OVERLAP`（同一面上有互相矛盾的多个交叉，通常是共点）、`REGION-OFF-CROSSING-OVERLAP`（多条丝带平行重叠、附近没有交叉）、`REGION-DROPPED-SLIVER`（近乎相切产生的碎片面）、`REGION-LENS-APPROXIMATION`（自交的局部窗口不足以覆盖重叠）。
  - 两者在普通交叉上**面积逐位一致**（`tests/test_arrangement.py` 对照断言）；分歧只出现在布尔模型必须近似的场景（自交、共点）——这正是保留两套实现的意义。
- ribbon 模式其余边界（都有诊断）：交叉没有上下关系时报 `REGION-MISSING-ASSIGNMENT`；偏移轮廓无效时受控修复并报 `REGION-INVALID-OUTLINE`；切分点落在折线顶点上时分段并集比整带少一个拐角连接，报 `REGION-SECTION-SEAM`（info）；过／欠关系成环且存在分段时报 `REGION-DRAW-ORDER-CYCLE`（info）。面积口径：`painted_area`（区域并集＝实际绘制面积）与 `union_area`（构建出的丝带并集）应当相等，`region_area_sum` 是含重叠的求和。Manim 侧孔洞是独立图层（Manim 没有奇偶填充规则），默认用 `hole_color` 涂成背景色，可用 `draw_holes=False` 自行处理。
- 输入为文字、SVG 时，提取的是矢量轮廓，不是字形的语义中心线笔画。
- Stroke 片段不变式（有测试保证）：同一路径的片段弧长区间互不重叠、也不超过路径总长；绕闭合缝的切口输出为一个 `piece-seam` 加其余可见弧段；开放路径的切口一旦覆盖整条中心线，就不输出片段并报 `RENDER-PATH-FULLY-CUT`。
- 样式层的参数同样在构造时校验，不静默退化：`StylePolicy` 的 `group_by`/`color_mode`/`opacity`/`fill_opacity`/`buckets`/`piece_order`/颜色值/配色名，`BorderSpec` 的 `corner`/`margin`/`thickness`/`radius`/`inset`/`bands`/`samples`，`CapTreatment` 的 `style`/`cover_allowance`/`samples`，`DensityPolicy` 的 `cluster_radius`/`cell_size`/`sliver_length`/`sliver_fraction`/`min_cluster_size`，以及 `Lace(palette=..., style_policy=...)` 同时给出。
- 参数非法一律抛 `ValueError`，且都在 `LaceEngine` 构造时校验（不会拖到 `solve()` 中途才失败）：`offset > 0`、`position_tol > 0`、`0 < angle_tol < 1`、`0 < min_sin <= 1`、`overshoot >= 0`、`min_piece_length >= 0`、`weave_mode ∈ {"alternating","free","manual"}`、`manual_over` 取值只能是 `"a"`/`"b"`、`candidate_strategy ∈ {"grid","brute_force"}`、`refine` 必须是布尔值、`conflict_strategy ∈ {"error","manual","relax"}`、`event_policy` 是 `EventPolicy`/字段映射/统一取值或 `None` 且取值合法（`endpoint_touch`、`near_tangent` 取 `"diagnose"|"weave"|"ignore"`，`collinear_overlap`、`multiway` 取 `"diagnose"|"ignore"`）、`cap_style ∈ {"butt","round","square"}`、`join ∈ {"miter","bevel","round"}` 且 `miter_limit > 0`、`ribbon_backend ∈ {"boolean","arrangement"}`。
- 候选加速只剪枝、不改语义：网格与暴力枚举必须给出逐事件、逐诊断、逐片段一致的结果（`tests/test_index.py`、`tests/test_benchmarks.py` 的黄金指纹）。
- 交叉精化（`refine=True`，默认开启）只精化已有事件，不产生新事件，也不改变事件的最大集合：候选仍在采样折线上判定。精化要求两侧路径都带来源曲线探针（`PolylinePath.curve`，由 `sample_parametric` / `sample_graph` / Manim 适配器提供）与来源参数映射（`PolylinePath.parameters`），成功时事件带 `refined=True`、`parameter_a/parameter_b`、曲线弧长与由**真实局部切向**算出的 `sin_angle`。探针缺失、探针抛错或返回非有限值、Newton 不收敛、解跑出候选邻域、或路径在该处**确实拐折**（无唯一局部切向）时，一律回退到折线估计并保持 `refined=False`，不会用"平滑过的"结果冒充几何。
- 精化后的 `segment_a`/`u_a` 描述的是精化参数所在的采样段，`s_a`/`s_b` 是折线累计弧长加上曲线在段内的真实弧长；闭合路径的弧长位置取模到 `[0, length)`。自交事件在精化后仍保证 `s_a < s_b`。

## 诊断码

诊断通过 `result.diagnostics` 暴露；`code` 稳定可编程判断，`message` 仅供人读。

| 阶段 | 诊断码 | 严重级 | 触发条件 |
|---|---|---|---|
| 几何 | `GEOM-DEGENERATE-PATH` | warning | 路径总长不超过位置容差（例如采样返回重复坐标） |
| 几何 | `GEOM-ENDPOINT_TOUCH` / `GEOM-NEAR_TANGENT` | warning | 候选交叉被判为端点接触／近切，默认不进入严格交替（`event_policy` 可改为提升或静默） |
| 几何 | `GEOM-CONTACT-WOVEN` | info | `event_policy` 把点状接触提升为普通横穿，`details["classified_as"]` 保留原分类 |
| 几何 | `GEOM-COLLINEAR-OVERLAP` | warning | 共线重叠线段，不发明交叉关系（`event_policy` 可静默） |
| 几何 | `GEOM-MULTIWAY-CROSSING` | warning | 多路径在同一点附近相交，不进入二元过／欠求解（`event_policy` 可静默） |
| 拓扑 | `TOPOLOGY-ALTERNATION-UNSAT` | error | 严格交替约束冲突；`details` 给出每个冲突的最小见证与 `crossing_ids` 并返回空分配，而不是伪造解 |
| 拓扑 | `TOPOLOGY-ALTERNATION-RELAXED` | warning | 冲突策略 `manual`/`relax` 放宽了部分交叉；`details` 含同样的见证与 `relaxed_crossing_ids` |
| 拓扑 | `TOPOLOGY-MANUAL-ASSIGNMENT-MISSING` | error | `manual` 模式缺少部分交叉的上方指定 |
| 拓扑 | `TOPOLOGY-MANUAL-OVERRIDE` | info | 用户指定覆盖了自动交替结果 |
| 拓扑 | `TOPOLOGY-MANUAL-CONFLICT` | warning | 同一路径上两次手动指定奇偶性不相容，保留了交叉 ID 较小的一项 |
| 渲染 | `RENDER-MISSING-ASSIGNMENT` | warning | 交叉没有上下关系，因此该处不切口 |
| 渲染 | `RENDER-CAP-EXTENSION` | info | `cap_style` 为 `round`/`square`，端头会多画半个线宽，断口已相应加宽 |
| 渲染 | `RENDER-DRAW-ORDER-CYCLE` | info | 过／欠关系成环且环上存在近似断口，绘制顺序被确定性打破 |
| 渲染 | `RENDER-PATH-FULLY-CUT` | warning | 切口覆盖整条中心线（闭合或开放） |
| 渲染 | `RENDER-PIECE-DROPPED` | info | 可见弧段短于 `min_piece_length` 而未输出 |
| 渲染 | `RENDER-SHALLOW-ANGLE-APPROXIMATION` | info | 至少一个浅角交叉的断口使用了受限近似 |
| 渲染 | `RENDER-COVER-ALLOWANCE` | info | 设置了端头覆盖余量：每个断口两侧各缩短 `cover_allowance × offset`（属几何风格参数，改切口不改拓扑） |
| 渲染 | `RENDER-COVER-ALLOWANCE-IGNORED` | info | ribbon 模式的切口是真实区域几何，覆盖余量不生效（如实上报而非静默忽略） |
| 渲染 | `RENDER-DENSITY-SIMPLIFIED` | info | 密度简化隐藏了密集簇内短于阈值的可见片段；`details` 含被隐藏的片段 ID、阈值与簇尺度 |
| 渲染 | `RENDER-DENSITY-SKIPPED` | info | 密度简化在 ribbon 后端不适用（那里的切口是真实几何），已跳过并上报 |
| 样式 | `STYLE-DRAW-ORDER-OVERRIDE` | info | 样式策略按非几何顺序重排绘制顺序；`details.moved_pieces` 给出不再处于几何层顺序的片段数 |
| 区域 | `REGION-OVERLAPPING-SECTIONS` | info | ribbon 模式下自交路径按分段输出，段落互相重叠，重叠处由 `draw_index` 决定上下 |
| 区域 | `REGION-COINCIDENT-CROSSINGS` | warning | 多个交叉落在同一点，各交叉扣除的重叠区互相抵消，覆盖面积无法保证守恒 |
| 区域 | `REGION-DRAW-ORDER-CYCLE` | info | 过／欠关系成环且存在分段，绘制顺序按节点顺序确定性打破 |
| 区域 | `REGION-SECTION-SEAM` | info | 切分点落在折线顶点，分段并集比整带少一个拐角连接的面积 |
| 区域 | `REGION-CONFLICTING-OVERLAP` | warning | 剖分后端：同一个面落在多个上下关系相反的交叉内（多为共点），按路径顺序确定性归属 |
| 区域 | `REGION-OFF-CROSSING-OVERLAP` | info | 剖分后端：多条丝带平行重叠且附近没有交叉，按路径顺序确定性归属 |
| 区域 | `REGION-DROPPED-SLIVER` | info | 剖分后端：近乎相切产生的碎片面已忽略（含数量与总面积） |
| 区域 | `REGION-LENS-APPROXIMATION` | info | 剖分后端：自交的局部窗口不足以完整覆盖重叠，面归属可能不精确 |
| 区域 | `REGION-MISSING-ASSIGNMENT` | warning | ribbon 模式下交叉缺少上下关系，该处没有扣除面积 |
| 区域 | `REGION-INVALID-OUTLINE` | warning | 偏移轮廓自交或塌缩，已受控修复 |
| 区域 | `REGION-EMPTY-RIBBON` | info | 路径没有长度或偏移区域为空，不产生面域 |
| 区域 | `REGION-AREA-MISMATCH` | warning | 绘制面积与丝带并集面积不一致（多条丝带非交叉点重叠，或多个交叉共点） |

## 项目结构

```text
src/manim_lace/
  model.py                 # 不依赖 Manim 的核心数据模型
  engine.py                # 数据流编排
  diagnostics.py           # 结构化诊断和领域异常
  benchmarks.py            # 可复现的基准输入集与事件指纹
  geometry/
    sampling.py            # 显式函数 / 参数曲线采样
    index.py               # 确定性候选索引与邻域聚类
    intersections.py       # 折线交叉事件检测
    refine.py              # 来源曲线上的局部交点精化（FR-036）
  topology/solver.py       # Pass 排序与 over/under 约束
  render/stroke.py         # 中心线切分几何
  render/order.py          # 两个后端共用的确定性绘制顺序
  render/regions.py        # 实体面域后端：布尔切除（默认）
  render/arrangement.py    # 实体面域后端：平面剖分 + 逐面归属
  render/pixels.py         # 像素对齐线宽换算（px_to_stroke_width / px_to_units）
  style/palette.py         # 和色色卡与命名配色、注册表、可复现取色（M6）
  style/grouping.py        # path / piece / layer / degree 分组
  style/policy.py          # StylePolicy / StylePlan / apply_style / 绘制顺序策略
  style/border.py          # 边框设计（BorderSpec / build_border）
  style/caps.py            # 切口端处理：覆盖余量契约与真实端头轮廓
  style/density.py         # 密度测量与密集区视觉简化
  adapters/manim.py        # Manim 矢量对象提取器
  manim_api.py             # 可选的 Manim VGroup Facade
  animation/trace.py       # 真实算法阶段轨迹
  tracing.py               # 有界 trace 载荷（计数精确 + 记录列表有界）
  animation/plan.py        # renderer-neutral 动画阶段计划
  animation/verify.py      # 动画坐标与最终几何一致性验证
benchmarks/bench_crossings.py  # 计时 + 网格/暴力等价校验
examples/scene_weave.py        # 基础编织场景 + 算法动画（WeaveDemo / SamplingTraceDemo）
examples/scene_gallery.py      # 端帽策略、绘制顺序与 9 个编织图案（含 GalleryEntry 注册表）
examples/scene_style.py        # 配色、边框、切口端与密度简化画廊（M6）
examples/scene_rosette.py      # 星形玫瑰线画廊，并把玫瑰线交给编织器
examples/rosette.py            # 示例自带的星形玫瑰线几何模块（manim_lace 不导入它）
examples/build_gallery.py      # 渲染上述场景并生成 media/gallery/index.html 状态画廊
media/gallery/                 # 生成物：状态画廊页面 + 静帧 + 两段动画视频（media/ 不入库）
```

运行基准（会打印剪枝比、耗时与事件指纹，并在两套候选策略不一致时返回非零退出码）：

```bash
python benchmarks/bench_crossings.py --repeat 3
```

## 建议的下一步开发顺序

与 `docs/ROADMAP.md` 的里程碑顺序保持一致（M5 收尾与 M6 均已完成）：

1. 在更大输入上继续压索引构造与逐段记账的开销（见 `make bench` 输出；区域模式可以压布尔/剖分运算次数，剖分后端目前对每个面做线性点测试）。
2. 让精化受益于更多输入：为无法求值来源曲线的路径（如 SVG 轮廓的多段折线）定义局部多项式精化，或让适配器保留更多来源参数信息。
3. 放宽时的质量：目前被放宽的交叉取确定性默认值，可以尝试"最少修改"的近似解（把放宽代价降到最低）。
4. 剖分后端可继续做细：把"面归属"提升为带 strand 标签的显式半边结构（现在已能正确归属，但没有对外暴露半边/邻接关系），并去掉自交局部窗口的经验长度。
5. 把细粒度轨迹用起来：让 `algorithm` 模式按 `sampling.subdivision` 的决策顺序逐层放大采样（现在只显示一行摘要），并给 `region.face_walk` 的每个面做逐面高亮。
6. 美学层继续做深：把样式策略接到动画阶段的强调色（`animation` 的 accent），并给 `BorderSpec` 加上圆弧 / 花边这类真正的装饰轮廓。

完整需求基线见 [`docs/SPEC.md`](docs/SPEC.md)。
