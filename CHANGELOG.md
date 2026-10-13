# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/), 格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

针对 `DEFECTS.md` 的三个算法缺陷的修复。

### 新增

- `validate_paths(paths, atol=DEFAULT_ATOL)`: **输入合法性检查**。检测两类让算法失效的
  退化输入并返回问题描述列表(空列表表示通过): `共线重叠`(两条线段同向/反向共线且投影重叠,
  含完全重合) 与 `多线共点`(三条以上线段经过同一点)。这两类输入会让丝带占据同一块区域、
  上下穿插关系无从定义, 而旧实现是静默的; 受控实验显示注入后中心线覆盖检查的失败点会从 0
  升到 24%~75%;
- `Interlacing(..., validate="ignore" | "warn" | "raise")` 与 `Lace(..., validate=...)`:
  对退化输入的处理策略(默认 `"warn"`, 只发一次 `UserWarning` 并继续求解; `"raise"` 直接抛
  `ValueError`; `"ignore"` 跳过检查), 检出结果存放在 `Interlacing.path_issues`;
- **派生几何自检 + 降级渲染**: 求解早期(`_align_all_rails` 之后)检查算法自己的配对契约
  —— "同一条线段上左右偏移线的交点数相等"(这是 `_set_ribbons` 按索引配对的前提)。契约
  不成立的路径**不再强行切分**, 而是退化成一条"不编织"的整条丝带(外轮廓 + 内轮廓),
  避免产出跨越大半个图形的错乱片段; 检出结果存放在 `Interlacing.rail_issues`,
  并汇总成一条 `UserWarning`;
- `Interlacing._align_all_rails()`: 把原先散在 `_set_ribbons` 里的"按交叉事件补齐缺失
  交点"提到求解早期统一执行, 于是 `_set_holes` 也能受益(孔洞数量/质量随之改善);
- `annulus_polygon(ring_a, ring_b)`: 把两条闭合环合成一个环形多边形(外环逆时针 +
  内环顺时针, 由一条狭缝相连), 已加入 `manim_lace.interlacing.__all__`;
- `tests/weave_checks.py`: 编织(交错)可见性模型校验工具, 按画家顺序重建最终图形并
  检查 A(多边形有效) / C(交点处恰好一方压上) / D(过欠交替) / E(中心线无重叠无破洞) /
  F(孔洞可见) / G(旋转对称) 六项性质;
- `tests/test_weave.py`: 上述模型的回归测试, 固定"已知正确的编织配置"(X 形两线、
  3×3 编织网格、PA n=12 L2、CA n=9 L1、PA n=8 L4)作为安全网;
- `tests/helpers.py`: `ring_path` / `ring_with_collinear_seam` /
  `level_zero_rosette_paths` / `rosette_paths` 路径构造器。

### 修复

- **缺陷 2**: `clear_paths` 现在会检查**闭合路径闭合点处的绕回共线**(首尾边 + 首边),
  删除该冗余顶点。此前 `Circle` 的子路径在 0° 锚点处前后两段边共线, 偏移线求交时被
  误判为平行而丢失唯一交点, 导致 `Lace(Circle(radius=2), offset=0.2)` 完全空输出
  (0 holes / 0 ribbons); 现已恢复为环形丝带, 并补上回归测试;
- **缺陷 1**: 无自交点的闭合路径(正方形/圆环/`level=0` 玫瑰线)此前被 `_set_ribbons`
  退化成"左右偏移线各自闭合成一个实心圆盘", 内侧圆盘把孔洞整个盖死(渲染成实心团块)。
  现在这类路径直接产出环形丝带, 中间孔洞保持可见;
- **缺陷 3(部分修复)**: `_set_ribbons` 在左右偏移线条数不一致时, 先按**交叉事件**
  把缺失的近失交点补回(`_align_rail_events`, 拓扑上紧跟其配对事件, 并同步登记以保持
  对称性), 再逐事件配对, 而不是按排序后的索引硬配对。对齐后仍不一致时不再静默, 求解
  结束会输出一条 `logging.warning` 汇总(而非逐段刷屏)。

### 已知限制

- **"偏移线自交"不是退化信号**: 实测大量正常玫瑰线的偏移线会自交且左右两侧对称
  (如 CA n=12 L4 有 48 处), 渲染完全正常, 因此派生几何自检**只**检查左右交点数是否相等;
- 缺陷 3 未完全修复。退化输入(共线重叠/多线共点)现在能被检出并降级, 但**正确编织**
  仍限于输入落在一般位置上的配置;
- `weave_grid_paths(4)`(4×4 开放网格)在可见性模型下也存在交点处双带同绘/破洞, 与文档
  里的缺陷 3 同源。文档所列"已知正确"的配置(X 形两线、`weave_grid_paths(3)`、
  PA n=12 L2、CA n=9 L1、PA n=8 L4)已全部通过 A/C/D/E/F/G;
- 重构前后对 `examples/lace_scenes.py` 的前四个展示场景渲染结果**逐字节一致**(A/B 对比
  md5 相同), 即第 1/2 步与配对对齐对正常输入零影响。

## [0.3.0] - 2026-10-13

一次以可用性与可维护性为目标的整体升级: 补齐测试与文档、加固核心流程、规范工程配置。

### 新增

- `tests/` pytest 测试套件(303 个用例), 覆盖几何工具函数、求解器、渲染层、
  玫瑰线生成、色卡与包级公开接口, 包含边界情况与异常场景;
- `tests/helpers.py`: 共享的路径构造器与几何断言辅助;
- `Interlacing(..., compute_overlaps=False)` 参数, 以及 `is_empty` 属性与 `__repr__`;
- `Lace.num_holes` / `Lace.num_ribbons` 属性, `Lace.hole_swatch` 暴露实际调色板;
- `manim_lace.lace.to_3d`: 坐标补齐为 Manim 三维点的公共工具函数;
- `StarRosette.level` / `StarRosette.star_type` 属性与 `__repr__`;
- `STAR_TYPE_VALUES`、`SWATCH_SIZE` 常量, `random_swatch(rng)` 支持自定义随机源;
- 示例脚本的命令行入口(`examples/*.py --help`), 以及 `TestLaceScene5`、
  `StarRosetteGallery`、`StarRosetteLaceScene` 三个新场景;
- `examples/rosette_gallery.py`: 批量导出各 `(花型, n, level)` 组合的预览图(图形大全),
  每张图叠加以红色**实线**绘制的 kernel 与以红色**虚线**绘制的镜像, 标注真实最大半径 `r`,
  并生成**可按键筛选**的 `index.html`(按花型 / N / 等级过滤, 点缩略图放大后用 `←` `→` 翻看);
- `examples/gallery_page.html`: 上述可筛选浏览页的模板(零依赖的 HTML/CSS/JS);
- `examples/rosette_levels.py`: 把相邻阶叠加在同一张图上(共用坐标系、逐阶标注最大半径),
  默认每张叠两阶, 支持 `--frame window|n|half|mid|inner` 与 `--zoom` 调整取景;
- `.github/workflows/ci.yml`: lint + 多 Python 版本测试;
- `py.typed` 类型标记、`CHANGELOG.md`、ruff / pytest / coverage 配置。

### 破坏性变更

- `MIN_PETALS` 3 → 4: `StarRosette(3, ...)` / `cal_kernels(3, ...)` 现在抛 `ValueError`;
- `cal_kernels` 返回长度由 `max(3, level + 1)` 变为 `max(2, level + 1)`(只构造到请求的阶),
  依赖 `kernels[2]` 的下游代码需注意;
- 不可实现的 `(n, level)` 组合现在抛 `ValueError`, 而不再静默返回含 `inf` / `nan` 的骨架。

### 变更

- 模块 `manim_lace/manim_lace.py` 重命名为 `manim_lace/lace.py`;
- 示例脚本由仓库根目录的 `test_lace.py` / `test_rosette.py` 迁移到
  `examples/lace_scenes.py` / `examples/rosette_scenes.py`, 且不再在导入时渲染;
- 包级导出扩充: `Interlacing`、`cal_kernels`、`random_swatch`、`swatches`、
  `STAR_TYPE_VALUES`、`__version__` 等;
- 所有输出多边形(孔洞、丝带片段、重叠区域)统一为逆时针绕向;
- `by_area` 分组键中的顶点数由 `len(hole)` 修正为 `len(hole) - 1`, 与
  `by_vertex_count` 保持一致;
- `MIN_PETALS` 由 3 提高到 4: `n = 3` 时 `xk0 = cosθ + sinθ / tan2θ = 0`, 核退化
  成径向线段, 图形没有实际意义;
- `cal_kernels` 只构造到请求的阶(返回长度 `max(2, level + 1)`), 不再为不需要的
  阶计算可能退化的坐标;
- 运行期诊断信息改用 `logging`(默认静默), 移除求解器中的调试 `print`;
- `requires-python` 放宽到 `>=3.10`, 并显式声明 `numpy` / `scipy` / `networkx` 依赖。

### 修复

- 高阶骨架在"旋转后的核线段与 x 轴平行"时除零, 产出 `inf` / `nan` 坐标(量级可达
  `1e16`, 图形被缩放成无意义的米字线) —— 现在改为抛出 `ValueError`, 并在消息中
  给出该 `(n, star_type)` 可用的最大阶数, 同时补上回归测试;
- 空输入(如 `Lace(VGroup())`)不再因缺少属性而崩溃, 而是退化为空图形;
- `hole_group_method` 传入未知取值时不再抛出 `UnboundLocalError`;
- 修复 `_set_ribbons` 中左右偏移线交点数不一致(例如闭合外环内侧相交、外侧不相交)
  导致的 `IndexError`;
- 传入与内部 `color` 参数重名的 kwargs(如 `Lace(path, color=RED)`)不再触发 `TypeError`;
- `StarRosette` 传入未知 `star_type` 时不再抛出 `UnboundLocalError`, 而是给出明确的
  `ValueError`;
- 修复 `right_handed` 对已知顶点不足的输入误判、`merge_paths` 在非正容差下的行为;
- 示例脚本的线宽/圆点半径改为按**输出像素**定义再换算(`px_to_stroke_width`): Manim 的
  `stroke_width` 是相对画幅的, 原先在大画幅低分辨率下会细成发丝(实测 `stroke_width=9`
  只有 2 像素), 导致粗细与透明度的设置在图上完全看不出差别。

### 移除

- 无破坏性移除; 原测试脚本仅迁移位置。

## [0.2.0] 及更早版本

未保留变更记录。
