# manim_lace

## 项目概述

`manim_lace` 是一个基于 [Manim](https://www.manim.community/) 的 Python 库, 提供两件核心能力:

1. **编织交错 (Lace / Interlacing)**: 把任意 Manim 路径转换成具有"上下穿插"效果的丝带图案,
   算法自动计算交点处的绘制/跳过关系以模拟编织物, 无需 Z-buffer。
2. **星形玫瑰 (StarRosette)**: 基于"核 (kernel) + 镜像 + 旋转"的算法生成对称星形/花朵图案。

## 架构分层

代码严格分为两层, 便于分别测试:

- **纯几何层** (`manim_lace/interlacing.py`): 只依赖 `numpy` / `scipy` / `networkx`,
  负责路径清洗合并、偏移线生成、交点计算与拓扑求解, 与 Manim 解耦。
- **渲染层** (`manim_lace/lace.py`, `manim_lace/rosette.py`): 把几何结果包装成
  `VGroup` / `Polygram`, 并做参数校验。

## 核心组件

| 文件 | 内容 |
| --- | --- |
| `manim_lace/interlacing.py` | `Interlacing` 求解器与 `clear_paths` / `merge_paths` / `generate_offset_lines` / `vectorized_intersection` / `right_handed` / `longest_chain` / `is_cycle` / `is_open_walk` |
| `manim_lace/lace.py` | `Lace`(继承 `VGroup`)与 `to_3d`、`HOLE_GROUP_METHODS` |
| `manim_lace/rosette.py` | `StarRosette`(继承 `Polygram`)与 `cal_kernels` / `get_petals_by_kernel` / `sort_petals` / `merge_adjacent_petals` / `transform_reps` |
| `manim_lace/swatches.py` | 84 张日式配色色卡与 `random_swatch` |

`Interlacing` 的主要中间量: `paths` / `paths_l` / `paths_r` / `paths_closed` / `paths_flag` /
`d_segments` / `d_intersections` / `d_seg_intersects` / `holes` / `ribbons` / `overlaps`。

## 开发环境

使用 `uv` 管理依赖, 配置见 `pyproject.toml`。

```bash
uv sync --extra dev            # 安装运行时 + 开发依赖
```

要求 Python 3.10+, 以及 Manim 所需的系统依赖(cairo / pango / ffmpeg)。

## 常用命令

```bash
uv run pytest                                  # 全部测试
uv run pytest --cov=manim_lace --cov-report=term-missing
uv run ruff check .                            # 静态检查
uv run ruff format .                           # 格式化

uv run python examples/lace_scenes.py              # 渲染示例(Lace)
uv run python examples/rosette_scenes.py           # 渲染示例(StarRosette)
uv run python examples/rosette_gallery.py          # 图形大全(566 张, 含可筛选的 index.html)
uv run python examples/rosette_levels.py --star-type PA   # 相邻阶叠加对比图(默认每张两阶)
uv run manim -pql examples/lace_scenes.py TestLaceScene0   # 直接使用 Manim CLI
```

预览图输出到 `media/` 下的子目录, 该目录已被 `.gitignore` 忽略。两个预览脚本的产物都能用
浏览器直接打开: `media/rosette_gallery/index.html` 是可按键筛选(花型 / N / 等级)的浏览页,
模板在 `examples/gallery_page.html`。

## 约定

- 修改核心逻辑时必须补充 `tests/` 用例, 并保证 `ruff check` 与 `ruff format --check` 通过;
- 参数非法时优先抛出 `ValueError`(类型问题抛 `TypeError`), 不要静默忽略;
- 几何构造不可实现时必须显式报错, 不允许产出 `inf` / `nan` 坐标
  (例如高阶核旋转后与 x 轴平行时的退化情形);
- 空输入应退化为空结果而不是抛异常;
- 所有输出的多边形保持逆时针绕向, 且首尾点重复(便于直连 Manim `Polygon`);
- 变更需记录到 `CHANGELOG.md`。

### 可视化约定(示例脚本)

- **线宽一律按"输出图片上的像素"定义**, 再用 `px_to_stroke_width(px, half_frame, size)`
  换算: Manim 的 `stroke_width` 是相对画幅定义的(逻辑宽度 ≈ `stroke_width × 0.01` 个单位),
  固定写死一个数在大画幅/低分辨率下会细成发丝(实测 `stroke_width=9` 只有 2 像素);
  圆点半径等几何量用 `px_to_units` 同理换算;
- 配色只用 Manim 的**基础常量**(`RED` / `GREEN` / `BLUE` / `TEAL` / `MAROON` …), 不用带
  `_A`~`_E` 后缀的深浅变体;
- 曲线与骨架分工明确: 曲线画半透明描边, **实线只留给 kernel**(实线)与其镜像(虚线);
- 文字大小与画幅无关(固定 `0.285 units/22pt`), 需要按取景范围等比放大字号与间距。

## 目录结构

```
manim_lace/          # 包源码
tests/               # pytest 测试套件(含 helpers.py)
examples/            # 可运行的渲染示例与预览工具, 不参与打包
                     #   rosette_gallery.py + gallery_page.html(图形大全与浏览页模板)
                     #   rosette_levels.py(相邻阶叠加对比)
images/              # README 展示图
.github/workflows/   # CI
```
