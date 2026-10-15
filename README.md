# manim_lace

[![Manim](https://img.shields.io/badge/Manim-0.19%2B-bcbdc0?style=flat)](https://github.com/ManimCommunity/manim)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat)
[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

把任意 [Manim](https://github.com/ManimCommunity/manim) 路径转换成具有 **"编织交错" (lace / interlacing)** 效果的丝带图案。当多条路径相交时, 算法自动计算交替的上下遮挡关系, 无需 Z-buffer 即可模拟真实编织物的视觉效果。

<p align="center">
  <img src="images/TestLaceScene0_ManimCE_v0.19.1.png" width="427" height="240" />
  <img src="images/TestLaceScene1_ManimCE_v0.19.1.png" width="427" height="240" />
  <img src="images/TestLaceScene2_ManimCE_v0.19.1.png" width="427" height="240" />
  <img src="images/TestLaceScene3_ManimCE_v0.19.1.png" width="427" height="240" />
</p>

## 特性

- **通用输入**: 任何 `VMobject`(圆、多边形、`FunctionGraph`、`NumberPlane`、任意贝塞尔路径)都可直接编织;
  曲线会先按三次贝塞尔重采样成折线(见 `manim_lace.lace.mobject_paths`), 采样点落在真正的曲线上;
- **纯几何内核**: `Interlacing` 只依赖 `numpy` / `scipy` / `networkx`, 可脱离渲染环境做单元测试。
- **两种产物**: 丝带片段 (`ribbons`) 与孔洞色块 (`holes`), 其中孔洞支持 4 种自动分组配色策略。
- **内置配色**: 84 张日式配色色卡, 无需手动指定颜色即可得到协调的配色。
- **星形玫瑰(可选)**: `manim_lace.rosette` 提供 `StarRosette` 与 `PA / PO / PR / CA / CR` 五种花型。
  它与核心的"任意路径 → 编织丝带"**零耦合**(不引用 `interlacing` / `lace`), 导入包时惰性加载,
  将来可以整体拆成独立包: `from manim_lace import StarRosette` 仍然可用;
- **健壮性**: 输入参数校验、空输入安全退化为空图形、对退化几何与浮点误差做了容错处理
  (所有容差都按角度判定, 与图形尺度无关)。
- **可维护**: 420+ 单元测试、ruff 代码规范、GitHub Actions 多版本 CI。

## 安装

需要 Python 3.10+ 与 Manim 所需的系统依赖(见 [Manim 安装文档](https://docs.manim.community/en/stable/installation.html))。

使用 [uv](https://docs.astral.sh/uv/)(推荐):

```bash
uv sync                # 安装运行时依赖
uv sync --extra dev    # 附带测试与 lint 工具
```

使用 pip:

```bash
pip install -e .            # 从仓库安装
pip install -e ".[dev]"     # 附带开发依赖
```

## 快速开始

```python
from manim import Scene, WHITE, Circle, tempconfig
from manim_lace import Lace


class MyScene(Scene):
    def construct(self):
        path = Circle(radius=2)

        lace = Lace(
            target_mobject=path,
            offset=0.2,             # 丝带半宽
            hole_opacity=0.9,       # 孔洞不透明度
            hole_group_method="by_area",
            stroke_color=WHITE,     # 丝带边框颜色
            fill_color=WHITE,       # 丝带填充颜色
            fill_opacity=1.0,
        )
        self.add(lace)


with tempconfig({"quality": "medium_quality", "background_color": WHITE}):
    MyScene().render()
```

配合星形玫瑰图案:

```python
from manim_lace import Lace, StarRosette

rosette = StarRosette(n=10, level=2, star_type="CA")
lace = Lace(rosette, offset=0.1, stroke_color=BLACK, stroke_width=1)
```

## API 速查

### `Lace`

继承自 `manim.VGroup`, 内部包含两个子组: `holes`(先绘制)与 `ribbons`(后绘制, 从而遮挡下方孔洞的局部区域)。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `target_mobject` | `VMobject` | 必填 | 待编织的路径对象, 算法会自动提取其所有子路径 |
| `offset` | `float` | `0.1` | 丝带半宽(总宽约 `2 * offset`), 必须为正 |
| `hole_opacity` | `float` | `1.0` | 孔洞填充不透明度, 取值 `[0, 1]` |
| `hole_color` | `Color \| None` | `None` | 指定后所有孔洞使用同一颜色, 忽略分组配色 |
| `hole_swatch` | `Sequence[Color] \| None` | `None` | 自动着色使用的调色板, 缺省从内置色卡随机取 |
| `hole_group_method` | `str` | `"by_area"` | 孔洞分组方法, 见下表 |
| `render` | `str` | `"ribbon"` | 编织通道: `"ribbon"`(区域切分)或 `"stroke"`(中心线 + 描边), 见"两条编织通道" |
| `**kwargs` | - | - | 透传给丝带片段的 `Polygon` 参数(`stroke_color` / `stroke_width` / `fill_color` / `fill_opacity` 等) |

常用属性与方法:

| 名称 | 说明 |
| --- | --- |
| `lace.holes` / `lace.ribbons` | 孔洞与丝带片段的 `VGroup` |
| `lace.hole_groups` | `{分组键: [孔洞坐标, ...]}`(带缓存), 键已排序 |
| `lace.num_holes` / `lace.num_ribbons` | 数量快捷方式 |
| `lace.interlacing` | 底层的几何求解结果, 可访问 `paths` / `d_intersections` 等中间量 |
| `lace.draw_path(coords)` | 调试辅助: 把坐标画成折线 |

`hole_group_method` 取值:

| 取值 | 分组依据 | 适用场景 |
| --- | --- | --- |
| `"by_area"` | `(顶点数, 面积)` | 默认值, 能区分大小不同的孔洞 |
| `"by_distance"` | 孔心到整体中心的距离 | 径向对称图形(曼陀罗), 产生由中心向外的渐变 |
| `"by_hole_index"` | 每个孔洞自成一组 | 需要随机/逐孔区分颜色 |
| `"by_vertex_count"` | 孔洞边数 | 只需按形状复杂度区分 |

### 两条编织通道(`render`)

| 取值 | 丝带是什么 | 孔洞 | 透明度 | 3D 挤出 |
| --- | --- | --- | --- | --- |
| `"ribbon"`(默认) | **区域**: 用偏移线交点切成片段多边形 | 显式构造(可配色) | 可半透明 | 支持 |
| `"stroke"` | **中心线 + `stroke_width`** | 不需要构造(没被盖住的地方就是背景) | **必须不透明** | 不支持 |

`render="stroke"` 用"中心线 + 描边宽度"表达丝带: 交叉处**把被压的一方切开**(断口 = 交点两侧
`offset / |sinθ|`), 于是压上方自然可见。它的好处是**与折线采样密度解耦** —— 密采样曲线、贝塞尔
输入也能织起来; 代价是线宽被强制为 `2 * offset / 0.01`(冲突的 `stroke_width` / `stroke_opacity` /
`fill_opacity` 会被忽略并告警), 没有孔洞色块与 3D 挤出, 且当"谁压谁"的约束成奇环时退化成
"每条路径一根完整描边"并发出告警。两条通道并存, 默认仍是 `"ribbon"`。

```python
# 曲线/贝塞尔输入推荐走 stroke 通道: 与折线采样密度解耦, 且不需要构造孔洞
lace = Lace(rosette, offset=0.1, render="stroke", ribbon_swatch=(BLUE, GREEN))
```

### `StarRosette`

继承自 `manim.Polygram`。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `n` | `int` | 必填 | 花瓣(角)数量, 必须 `>= 4`(`n = 3` 时核会退化成径向线段) |
| `level` | `int` | `2` | 阶数/复杂度, 必须 `>= 0`; 并非所有 `(n, star_type)` 都存在任意高阶, 见下 |
| `star_type` | `str` | `"PA"` | 花型标识: `PA` / `PO` / `PR` / `CA` / `CR` |
| `**kwargs` | - | - | 透传给 `Polygram` 的样式参数 |

#### 高阶的可行范围

第 2 阶由封闭公式给出, 更高阶则由"旋转前一阶 + 与该阶所在直线与 x 轴求交"迭代得到。
某些 `(n, star_type)` 组合会让旋转后的核线段恰好**与 x 轴平行**, 此时该阶在数学上不存在
(早期版本会在这里除零并产出 `inf` / `nan`, 形成无意义的图形)。现在会显式抛出:

```python
ValueError: level 4 is not realizable for n=6, star_type='PA': the rotated kernel segment is
parallel to the x-axis ...; the largest usable level for this (n, star_type) is 3
```

经验规律(实测):

| 情形 | 可行阶数上限 |
| --- | --- |
| 偶数 `n`, `PA` / `CA` | `n / 2` |
| 偶数 `n`, `PR` / `CR` | `n / 2 + 1` |
| 偶数 `n`, `PO` | `n / 2 + 3`(`n = 4` 时为 1, 因第 2 阶就已退化) |
| 奇数 `n` | 上限远大于 `n`, 且图形以 `n` 为周期循环(不再增长) |

也就是说"越高的阶"并不是无限的: 偶数 `n` 的图形会随阶数逐级向外生长直到撞上平行退化,
奇数 `n` 则很快进入周期循环。

### `Interlacing`(进阶)

纯几何求解器, 不依赖 Manim, 可在无渲染环境下使用:

```python
import numpy as np
from manim_lace import Interlacing

solver = Interlacing([np.array([[0.0, 0.0], [4.0, 0.0]]), np.array([[2.0, -2.0], [2.0, 2.0]])], offset=0.1)
print(len(solver.holes), len(solver.ribbons))
```

参数: `paths`(路径序列)、`offset`(丝带半宽)、`compute_overlaps`(是否额外计算交错重叠区域, 默认 `False`)。
空输入或全部退化时不会抛异常, 而是得到一个 `is_empty == True` 的空结果。

### 异常行为

以下情况会抛出 `ValueError`(便于尽早发现参数错误, 而不是渲染后看到错误画面):

- `offset <= 0` 或非有限值;
- `hole_opacity` 不在 `[0, 1]` 区间;
- `hole_group_method` 不在支持列表中;
- `hole_swatch` 传入空列表(传 `None` 表示使用随机调色板);
- `StarRosette` 的 `n < 4`、`level < 0` 或未知 `star_type`;
- 请求了该 `(n, star_type)` 下不存在的阶数(见下方"高阶的可行范围")。

`n` / `level` 类型不是整数时抛出 `TypeError`。

## 算法流程详解

Lace 算法的核心思想是把几何问题转化为拓扑图论问题: 先构造路径的偏移线(丝带的上下边缘)并计算交点, 把丝带切成若干片段, 再在交点处交替"绘制"与"跳过", 从而在二维平面上模拟遮挡关系。

### 1. 预处理

输入为任意的 Manim `VMobject`, 逐个取出子路径后:

1. **路径提取**: 遍历 `family_members_with_points()` 收集所有子路径;
2. **清洗** (`clear_paths`): 移除重复点与共线点, 丢弃长度不足 2 的退化路径;
3. **合并** (`merge_paths`): 把首尾相接的路径拼成更长的开放链或闭合环, 并统一闭合环的绕向(逆时针)。

### 2. 偏移线生成

为了模拟有宽度的丝带, 算法为主路径生成两条平行偏移线:

- **算法**: **Miter Join**, 在拐点取相邻法向量的角平分线并放大 `1 / (1 + cosθ)`;
- **保护**: 锐角处延伸倍数被限制在 `MITER_LIMIT = 5` 以内, 避免尖刺;
- **输出**: 左 (`paths_l`) 右 (`paths_r`) 两条偏移路径。

### 3. 交点计算

算法构建基于 **Segment(线段)** 与 **Intersection(交点)** 的网络:

1. **扫描线**: 按 `xmin` 排序后对候选线段做包围盒过滤, 再用向量化公式求交(`vectorized_intersection`);
2. **聚类与告警**: 同一坐标上有 3 条以上线段相交时会发出 `UserWarning`;
3. **排序**: 每条线段上的交点按到起点的距离排序, 供后续拓扑分析使用。

> 中线(`type=0`)不参与求交, 只有左右偏移线互相切割, 这样每条丝带的"上下边缘"才能对上。

### 4. 区域识别与生成

#### 孔洞 (`_set_holes`)

- 开放路径的 4 个断头端点先被登记为虚拟节点;
- 用 `KDTree` 为断头端点寻找最近的合法邻居并"缝合"成虚拟边(排除同一条丝带的左右孪生端点), 从而封闭区域;
- 在交点图上搜索环 (`cycle_basis`), 排除面积最大的外轮廓环与退化环, 其余即为孔洞。

#### 丝带片段 (`_set_ribbons`)

这是编织效果的关键:

- 沿每条路径的左右偏移线行进, 维护布尔标志 `flag`, 每经过一组交点就翻转;
- `flag` 为真时, 补全当前片段并封口, 形成一个闭合多边形(丝带片段);
- `flag` 为假时跳过该段, 留给其它丝带覆盖, 于是形成"上/下"穿插的视觉错觉;
- 开放路径的 `paths_flag` 初始值在相邻路径间交替, 避免所有丝带压在同一层。

## 关键数据结构

```python
from manim_lace import Interlacing

solver = Interlacing(paths, offset=0.1)

solver.paths              # 清洗合并后的路径列表
solver.paths_closed       # 每条路径是否闭合
solver.paths_flag         # 每条开放路径的初始绘制标志
solver.paths_l, solver.paths_r   # 左右偏移线
solver.d_segments         # {(路径, 类型, 线段): (起点, 终点)}
solver.d_intersections    # {交点键: 坐标}
solver.d_seg_intersects   # {线段: [相交线段, ...]}(按距离排序)
solver.holes              # 孔洞多边形列表
solver.ribbons            # 丝带片段多边形列表
solver.overlaps           # 交错重叠区域(需 compute_overlaps=True)
```

线段标识为 `(路径下标, 类型, 线段下标)`, 其中类型 `0` 表示中线, `1` 表示左偏移线, `2` 表示右偏移线。

## 项目结构

```
manim_lace/
├── manim_lace/            # 包源码
│   ├── interlacing.py     # 纯几何内核: 清洗/合并/偏移/求交/拓扑(第一条通道)
│   ├── stroke.py          # 纯几何: 第二条通道 "中心线 + stroke_width + 顺序"
│   ├── lace.py            # 渲染层: Lace(VGroup) 与参数校验
│   ├── rosette.py         # 可选模块: 星形玫瑰(核计算 + StarRosette), 核心不依赖它
│   ├── swatches.py        # 内置配色色卡
│   └── py.typed           # PEP 561 类型标记
├── tests/                 # pytest 测试套件
│   ├── helpers.py         # 共享路径构造与几何断言辅助
│   ├── test_interlacing.py
│   ├── test_geometry_utils.py
│   ├── test_lace.py
│   ├── test_rosette.py
│   ├── test_swatches.py
│   └── test_package.py
├── examples/              # 可运行的渲染示例(不参与打包)
│   ├── lace_scenes.py
│   └── rosette_scenes.py
├── images/                # README 展示图
├── pyproject.toml         # 打包/依赖/ruff/pytest/coverage 配置
└── .github/workflows/     # CI
```

## 开发与测试

```bash
uv sync --extra dev                       # 安装开发依赖

uv run pytest                             # 运行全部测试
uv run pytest -q -k rosette               # 只跑部分测试
uv run pytest --cov=manim_lace --cov-report=term-missing   # 带覆盖率

uv run ruff check .                       # 静态检查
uv run ruff format .                      # 代码格式化
```

渲染示例场景(在仓库根目录执行):

```bash
uv run python examples/lace_scenes.py                 # 渲染全部 Lace 场景
uv run python examples/lace_scenes.py TestLaceScene0  # 只渲染一个场景
uv run python examples/rosette_scenes.py StarRosetteGallery -q low_quality -p
```

### 图形大全 (rosette_gallery.py)

为每个 `(花型, n, level)` 出一张图, 写入 `media/rosette_gallery/`(已被 `.gitignore` 忽略)。
默认 `n = 4~12, 16, 20, 36`, `level = 0~12`, 不可实现的组合会自动跳过并打印清单。

```bash
uv run python examples/rosette_gallery.py                          # 全量(默认 566 张, 720px, 约 40 MB)
uv run python examples/rosette_gallery.py --star-type PA CA --n 9 12 --level 0 1 2
uv run python examples/rosette_gallery.py --size 1080              # 更高分辨率
uv run python examples/rosette_gallery.py --overlay petal          # 骨架改成花瓣轮廓(默认 kernel)
uv run python examples/rosette_gallery.py --overlay none           # 只画图形本身
```

每张图包含: 蓝色图形轮廓(统一缩放到画幅 84%, 标签给出真实最大半径 `r`) +
红色 **kernel 实线**与其 **镜像虚线**(实线/虚线每个拐点都有圆点) + 淡灰对称轴。
输出目录里的 `index.html` 默认是**可筛选浏览页**: 按花型 / N / 等级过滤, 点缩略图放大后
用 `←` `→` 在筛选结果里连续翻看(模板见 `examples/gallery_page.html`);
`--index simple` 换回静态网格, `--index none` 不生成。

### 相邻阶叠加 (rosette_levels.py)

把相邻阶画在同一张图上并**共用坐标系**, 便于观察高阶如何从低阶"长"出来:

```bash
uv run python examples/rosette_levels.py --star-type PA --n 5 7      # 默认每张叠两阶
uv run python examples/rosette_levels.py --star-type PA --n 9 12 --window 3   # 三阶叠加(较难分辨)
uv run python examples/rosette_levels.py --star-type PA --window 8 --step 8 --frame n

# 内圈细节被外围尖刺压小的时候, 放大取景(裁掉最外层尖刺)
uv run python examples/rosette_levels.py --star-type PA --frame half    # 最小圈与最外圈半径的中点(推荐)
uv run python examples/rosette_levels.py --star-type PA --frame mid     # "居中圈"与最外圈半径的中点
uv run python examples/rosette_levels.py --star-type PA --frame inner   # 按窗口内最小那一圈取景(裁得最狠)
uv run python examples/rosette_levels.py --star-type PA --frame inner --zoom 0.8   # 再放大 25%

# 只渲一张做快速预览; 线型 band=只有半透明描边(默认) / faint=更透 / core=描边+同色实心芯
uv run python examples/rosette_levels.py --star-type PA --n 7 --only 2 --frame half --style core
uv run python examples/rosette_levels.py --star-type PA --color absolute          # 同一阶跨图同色

# 每张图默认叠加各阶的 petal 花瓣单元(实线 + 顶点圆点: 整图由它旋转 n 份拼成), 不需要时关闭
uv run python examples/rosette_levels.py --star-type PA --no-petal
uv run python examples/rosette_levels.py --star-type PA --petal-style dashed      # 想用虚线
```

配色默认按窗口内位置取 Manim 基础常量 `RED` / `GREEN` / `BLUE`(最低阶 → 最高阶),
因此颜色本身就指示了内外圈; 半径大的先画, 最小那一阶落在最上层, 不会被外圈描边盖住。

两个脚本都会在输出目录生成 `index.html` 便于连续翻阅。

也可以直接使用 Manim CLI:

```bash
uv run manim -pql examples/lace_scenes.py TestLaceScene0
```

添加新功能时请同步:

1. 在 `tests/` 中补充覆盖正常流程、边界情况与异常场景的用例;
2. 运行 `uv run ruff check . && uv run ruff format --check .` 与 `uv run pytest`;
3. 在 [CHANGELOG.md](CHANGELOG.md) 中记录变更。

## 常见问题

**渲染结果是一团黑色?**
丝带片段会同时使用 `stroke_color` 作为填充色。若只想看到描边, 请显式传入 `fill_color` / `fill_opacity=0`。

**孔洞没有颜色 / 颜色重复?**
孔洞按 `hole_group_method` 分组后, 从 `hole_swatch` 中线性取色。分组数少于色卡长度时会重复使用颜色, 可用 `hole_swatch` 指定更短的调色板, 或用 `hole_color` 强制统一颜色。

**`offset` 取多大合适?**
默认 `0.1`。图形越小/交点越密, 应取越小的值; `offset` 过大时丝带会互相吞没, 孔洞消失。

**出现 `Multi-segment intersection` 警告?**
说明有 3 条以上偏移线在同一点相交(常见于精确共点的构造)。渲染结果依然可用, 但该处的遮挡关系可能不理想, 可微调 `offset` 或把输入路径稍微错开。

**`Node ... has no valid neighbors` 警告?**
某条开放路径的断头端点附近找不到可以缝合的邻居(例如孤立的短线)。该路径的孔洞会缺失, 但不影响丝带绘制。

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 致谢

- 配色色卡来自樱井辉子 (Teruko Sakurai) 的《日本色彩调和辞典》(Japanese Color Harmony Dictionary);
- 编织(interlacing)思路参考凯尔特结与拓扑图论中的常规做法。
