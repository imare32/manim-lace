# Manim Lace — 二维矢量路径蕾丝编织引擎

> 版本：`0.1.0`（可运行的开发起点，不是完整 1.0 产品）

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
| 从 Manim `VMobject` / `VGroup` 读取路径 | 已提供可选适配器；需安装 Manim 后实测特定版本 |
| 中心线段交叉检测 | 已实现基础版：路径间/自交/重叠/端点/多线共点诊断；顶点交叉、闭合缝、重复顶点与退化路径有回归测试 |
| 候选加速与性能基准 | 已实现确定性均匀网格剪枝（`candidate_strategy` 可切换网格/暴力，两者逐事件等价），附四类输入的可复现基准集与事件指纹 |
| 路径级严格交替求解 | 已实现基础版与冲突诊断 |
| 每次交叉手动指定上下关系 | 已实现 `manual` 模式和逐交叉覆盖 |
| Stroke 几何切分 | 已实现基础版：闭合缝切口、整条被切、浅角受限与片段丢弃都有显式诊断和测试；端帽与精确区域裁剪仍属视觉近似 |
| Manim `Lace` VGroup 封装 | 已提供，需要安装 Manim 才可运行 |
| 基于算法轨迹的动画计划 | 已实现 renderer-neutral trace plan；Manim 动画适配器为初始版本 |
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
- `result.trace`：实际求解过程留下的结构化轨迹。

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

核心用法是：

```python
from manim import *
from manim_lace import Lace

class WeaveDemo(Scene):
    def construct(self):
        source = VGroup(
            ParametricFunction(lambda t: np.array([t, np.sin(2*t), 0]), t_range=[-3, 3]),
            Line(LEFT*3 + DOWN, RIGHT*3 + UP),
        )
        lace = Lace(source, offset=0.12, render="stroke", weave_mode="alternating")
        self.play(lace.build_animation(mode="algorithm"))
        self.wait()
```

`Lace` 是可加入 `Scene` 的 `VGroup`。适配器依据 Manim CE 的 `VMobject.get_subpaths()` / 四点三次贝塞尔结构开发（参见 [Manim 官方 VMobject 文档](https://docs.manim.community/en/stable/reference/manim.mobject.types.vectorized_mobject.VMobject.html)）。当前构建环境没有安装 Manim，因此纯几何测试已实跑，但实际 Manim 渲染仍需要你本机做一次 smoke test，特别是 VMobject 点结构与视觉线宽。

## 运行测试

```bash
pytest
```

不安装 Manim 也应能运行纯几何单元测试。可选 Manim 集成测试应通过 `pytest.importorskip("manim")` 跳过。

## 重要语义

- `offset` 表示半宽，因此总几何宽度目标为 `2 * offset`。
- 严格 `alternating` 模式只有在约束相容时才能给出解；若不相容，拓扑对象会携带 `TOPOLOGY-ALTERNATION-UNSAT` 诊断，不会假称已满足严格交替。
- `free` 模式对未手动指定的交叉使用确定性默认分配，但不承诺路径级交替。
- `manual` 模式需要为每个普通横穿交叉提供 `crossing_id: "a" | "b"`；`a` / `b` 分别指该事件数据中的 `path_a` / `path_b` 一侧。自交的两侧仍由不同弧长经过区分。
- 当前 `stroke` 后端针对不透明二维描边的视觉呈现。半透明叠色、浅角遮挡端头的精确几何与真实区域裁剪不在保证范围内。
- `render="ribbon"` 当前明确抛出 `NotImplementedError`。后续应基于真正的平面细分/半边结构或经过验证的二维布尔几何来实现，而不是把普通图的环路基当成平面面域。
- 输入为文字、SVG 时，提取的是矢量轮廓，不是字形的语义中心线笔画。

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

1. 交叉候选已用确定性网格剪枝，且与暴力枚举逐事件等价（见 `tests/test_index.py`）；下一步是窄相位包围盒的向量化，以及采样曲线的交点局部精化（FR-036）。
2. 用实际 Manim CE 版本做适配器和视频视觉测试。
3. 为 Stroke 补齐端帽策略、片段绘制依赖顺序与视觉回归样例（闭合路径切口与浅角近似已有测试与诊断）。
4. 建立 half-edge / planar arrangement 或验证几何库的区域后端。
5. 把算法 TraceEvent 扩展成采样细分、局部交叉候选、约束传播步骤和区域遍历的细粒度记录。

完整需求基线见 [`docs/SPEC.md`](docs/SPEC.md)。
