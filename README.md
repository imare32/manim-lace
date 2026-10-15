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
| 路径级严格交替求解 | 已实现基础版与冲突诊断 |
| 每次交叉手动指定上下关系 | 已实现 `manual` 模式和逐交叉覆盖 |
| Stroke 几何切分 | 已实现基础版：闭合缝切口、整条被切、浅角受限与片段丢弃都有显式诊断和测试；端帽与精确区域裁剪仍属视觉近似 |
| Manim `Lace` VGroup 封装 | 已提供，并在 Manim CE `0.22.0` 上实机渲染通过（`examples/scene_weave.py`） |
| 基于算法轨迹的动画计划 | 已实现 renderer-neutral trace plan；Manim 动画适配器为初始版本，实机渲染已跑通 |
| 可视化线宽 | 采用 `max(1.0, 200.0 * offset)` 的启发式映射；Manim 的 `stroke_width` 随画幅变化，尚未做严格的像素对齐换算 |
| 实体 Ribbon、多边形面域与孔洞 | 明确未实现，留下接口与设计要求 |
| 隐式方程直接等值线提取 | 未实现；可先传入 Manim `ImplicitFunction` 的矢量对象 |
| 精确曲线曲线求交、鲁棒多线共点分解 | 未实现；当前中心线求交基于采样折线 |

## 安装

建议在项目根目录创建虚拟环境。纯几何核心不依赖 Manim：

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1

python -m pip install -e '.[dev]'
```

如需在 Manim 场景中直接使用 `Lace`（可选依赖约束为 Manim CE `>=0.19,<0.23`）：

```bash
python -m pip install -e '.[manim,dev]'
```

如之后采用 Shapely 作为区域布尔运算后端：

```bash
python -m pip install -e '.[geometry,dev]'
```

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
- `result.crossings`：交叉候选及路径弧长位置；
- `result.topology.assignments`：每个已解交叉的过／欠分配；
- `result.pieces`：Stroke 后端切分出来的可见折线片段；
- `result.diagnostics`：结构化诊断；
- `result.trace`：实际求解过程留下的结构化轨迹；
- `result.detection_stats`：候选筛选统计（策略、线段数、候选对数、窄相位次数、网格单元数、暴力上界）。

调试时常用的几个入口：

```python
result = LaceEngine(paths, offset=0.1, weave_mode="free").solve()
print([d.code for d in result.diagnostics])       # 稳定诊断码，见下文表格
print(result.detection_stats)                      # 候选剪枝比与实际判定次数
for event in result.trace:                         # 真实算法阶段，而非事后编故事
    print(event.sequence, event.stage, event.event_type, event.data)
```

`LaceEngine(..., candidate_strategy="brute_force")` 可作为参照实现：它与默认网格策略必须给出**相同的交叉事件、诊断与片段几何**，若不一致即为缺陷。

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

`Lace` 是可加入 `Scene` 的 `VGroup`。适配器依据 Manim CE 的 `VMobject.get_subpaths()` / 四点三次贝塞尔结构开发（参见 [Manim 官方 VMobject 文档](https://docs.manim.community/en/stable/reference/manim.mobject.types.vectorized_mobject.VMobject.html)）。

**实测状态**：本仓库 `.venv` 中安装的是 Manim CE `0.22.0`，上面这条命令已实机渲染通过（输出 `media/videos/scene_weave/480p15/WeaveDemo.mp4`），`tests/test_optional_manim.py` 的 VMobject→路径提取也真实执行而非跳过。尚未验证的是跨版本兼容矩阵（`pyproject.toml` 声明 `>=0.19,<0.23`）与视觉线宽的像素对齐。

`build_animation(mode=...)` 支持 `overview` / `algorithm` / `construction` / `debug` / `custom`，阶段划分来自 `result.trace` 记录的真实算法阶段（见 `docs/ALGORITHM_TRACE.md`）；未知模式会抛 `ValueError`，不会静默给出一段空动画。

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
- 严格 `alternating` 模式只有在约束相容时才能给出解；若不相容，拓扑对象会携带 `TOPOLOGY-ALTERNATION-UNSAT` 诊断，不会假称已满足严格交替。
- `free` 模式对未手动指定的交叉使用确定性默认分配，但不承诺路径级交替。
- `manual` 模式需要为每个普通横穿交叉提供 `crossing_id: "a" | "b"`；`a` / `b` 分别指该事件数据中的 `path_a` / `path_b` 一侧。自交的两侧仍由不同弧长经过区分。
- 当前 `stroke` 后端针对不透明二维描边的视觉呈现。半透明叠色、浅角遮挡端头的精确几何与真实区域裁剪不在保证范围内。
- `render="ribbon"` 当前明确抛出 `NotImplementedError`。后续应基于真正的平面细分/半边结构或经过验证的二维布尔几何来实现，而不是把普通图的环路基当成平面面域。
- 输入为文字、SVG 时，提取的是矢量轮廓，不是字形的语义中心线笔画。
- Stroke 片段不变式（有测试保证）：同一路径的片段弧长区间互不重叠、也不超过路径总长；绕闭合缝的切口输出为一个 `piece-seam` 加其余可见弧段；开放路径的切口一旦覆盖整条中心线，就不输出片段并报 `RENDER-PATH-FULLY-CUT`。
- 参数非法一律抛 `ValueError`，且都在 `LaceEngine` 构造时校验（不会拖到 `solve()` 中途才失败）：`offset > 0`、`position_tol > 0`、`0 < angle_tol < 1`、`0 < min_sin <= 1`、`overshoot >= 0`、`min_piece_length >= 0`、`weave_mode ∈ {"alternating","free","manual"}`、`manual_over` 取值只能是 `"a"`/`"b"`、`candidate_strategy ∈ {"grid","brute_force"}`。
- 候选加速只剪枝、不改语义：网格与暴力枚举必须给出逐事件、逐诊断、逐片段一致的结果（`tests/test_index.py`、`tests/test_benchmarks.py` 的黄金指纹）。

## 诊断码

诊断通过 `result.diagnostics` 暴露；`code` 稳定可编程判断，`message` 仅供人读。

| 阶段 | 诊断码 | 严重级 | 触发条件 |
|---|---|---|---|
| 几何 | `GEOM-DEGENERATE-PATH` | warning | 路径总长不超过位置容差（例如采样返回重复坐标） |
| 几何 | `GEOM-ENDPOINT_TOUCH` / `GEOM-NEAR_TANGENT` | warning | 候选交叉被判为端点接触／近切，默认不进入严格交替 |
| 几何 | `GEOM-COLLINEAR-OVERLAP` | warning | 共线重叠线段，不发明交叉关系 |
| 几何 | `GEOM-MULTIWAY-CROSSING` | warning | 多路径在同一点附近相交，不进入二元过／欠求解 |
| 拓扑 | `TOPOLOGY-ALTERNATION-UNSAT` | error | 严格交替约束冲突，返回空分配而不是伪造解 |
| 拓扑 | `TOPOLOGY-MANUAL-ASSIGNMENT-MISSING` | error | `manual` 模式缺少部分交叉的上方指定 |
| 拓扑 | `TOPOLOGY-MANUAL-OVERRIDE` | info | 用户指定覆盖了自动交替结果 |
| 渲染 | `RENDER-MISSING-ASSIGNMENT` | warning | 交叉没有上下关系，因此该处不切口 |
| 渲染 | `RENDER-PATH-FULLY-CUT` | warning | 切口覆盖整条中心线（闭合或开放） |
| 渲染 | `RENDER-PIECE-DROPPED` | info | 可见弧段短于 `min_piece_length` 而未输出 |
| 渲染 | `RENDER-SHALLOW-ANGLE-APPROXIMATION` | info | 至少一个浅角交叉的断口使用了受限近似 |

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
  topology/solver.py       # Pass 排序与 over/under 约束
  render/stroke.py         # 中心线切分几何
  render/regions.py        # 实体区域后端接口（未实现）
  adapters/manim.py        # Manim 矢量对象提取器
  manim_api.py             # 可选的 Manim VGroup Facade
  animation/trace.py       # 真实算法阶段轨迹
  animation/plan.py        # renderer-neutral 动画阶段计划
benchmarks/bench_crossings.py  # 计时 + 网格/暴力等价校验
```

运行基准（会打印剪枝比、耗时与事件指纹，并在两套候选策略不一致时返回非零退出码）：

```bash
python benchmarks/bench_crossings.py --repeat 3
```

## 建议的下一步开发顺序

1. 采样曲线的**交点局部精化**（FR-036）：当前求交基于折线，顶点交叉的角度仍取自线段对而非真实切向。
2. Stroke 的端帽策略、片段绘制依赖顺序与视觉回归样例（闭合缝切口、整条被切、浅角近似已有测试与诊断）。
3. 视觉线宽的像素对齐换算，以及 Manim CE `0.19`~`0.22` 的适配器兼容矩阵。
4. 建立 half-edge / planar arrangement 或验证几何库的区域后端。
5. 把算法 TraceEvent 扩展成采样细分、逐候选线段对、约束传播步骤和区域遍历的细粒度记录（目前候选阶段只有聚合计数）。
6. 在更大输入上继续压索引构造与逐段记账的开销（见 `make bench` 输出）。

完整需求基线见 [`docs/SPEC.md`](docs/SPEC.md)。
