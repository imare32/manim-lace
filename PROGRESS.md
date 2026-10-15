# manim-lace 进度

> **唯一进度入口**: 记状态、已完成(带证据)、正在做、待做, 以及"**已经试过并被否决的做法**"。
> 本文件只写**结论 + 证据指针**; 逐条实测数据与推导过程在各条目的证据文件里, 不要重复堆表格。
> 相关文档: `DEFECTS.md`(缺陷台账)、`CHANGELOG.md`(按版本)、`AGENTS.md`(工程约定)、`README.md`(用法)。

**更新于 2026-10-14** · 版本 `0.3.0` · `uv run pytest -q` → **471 passed** · `ruff check .` / `ruff format --check .` 全绿

---

## 0. 状态快照

| 项 | 值 |
| --- | --- |
| 分支 / checkpoint | `master`;提交点 `59fcfa8`(布局重构)、`53a9593`(按交叉身份切分)、`f5bbffd`(工具入库)、`e639831`(缺陷 9/10 + 描边收尾)、`ea1fea3`(文档/工具/CI)、`7ede551`(tag `pre-step3`) |
| 未提交 | 无(工作区干净);§3 P0-5 的"阶段 1 第三步"与随后的布局重构均已提交 |
| 未入库 | `media/`(1358 文件 / 96.8 MB,含全部探针脚本、渲染图、验收页);基线快照 `media/_review/head_tree/` |

```bash
uv run pytest -q                                  # 471 passed
uv run ruff check . && uv run ruff format --check .   # 全绿
uv run python tools/matrix_digest.py media/_review/digest.txt   # 全矩阵指纹(改动前后 diff)
```

### 0.3 回归底线:对正常输入零影响(A/B 字节级)

```bash
git archive <基线 ref> | tar -x -C media/_review/head_tree          # 一次性: 取出基线快照(不入库)
uv run python tools/ab_render.py --root media/_review/head_tree --out media/_review/ab_old
uv run python tools/ab_render.py --root .                       --out media/_review/ab_new
# 比对两个目录里四张 png 的 md5
```

即 `examples/lace_scenes.py` 前四个展示场景(`TestLaceScene0..3`)必须与重构前**逐字节一致**。
**当前 4/4 相同**(2026-10-14 复核的所有改动之后重跑仍然 4/4)。任何改动都要重跑这条 —— 它是
"不破坏既有渲染"的唯一硬证据, 工具已入库(`tools/ab_render.py`)。

---

## 1. 已完成(结论 + 证据)

**类一~类五的测试矩阵**(类一玫瑰线 §1.10、类二简单闭合/相切/共线 §1.10b、类三闭合+开放 §1.10c、
类四开放+开放(含 3×3/4×4/5×5 编织网格) §1.10c、类五平铺: 变体 A 重叠格点 §1.12、变体 B Kaplan §1.11):
画廊在 `media/lace_tests/{rosette,closed,mixed,open,kaplan,tiling}/index.html`, 脚本 `media/_review/campaign_*.py`。
**收录门槛**: 不降级无残差(`deg=0`、`rail_issues` 空、C/D/E/F=0, 浅角交点按 `stats["skipped"]` 跳过)
+ 密度 `r ≥ 30` + 代表性(同花型内 level 相同且 n 差 ≤ 2 视为重复)。

| # | 结论 | 关键数字 / 证据 |
| --- | --- | --- |
| 1.1 | **缺陷 2 已修**: `Lace(Circle)` 不再空白 | 根因是闭合点处的"绕回共线"没被清理 → `_clear_closed_collinear()`;`0/0` → `1 hole / 1 ribbon` |
| 1.2 | **缺陷 1 已修**: 无自交闭合路径不再渲染成实心团块 | `annulus_polygon()` + `_is_simple_closed()` 直接产出环形丝带;正方形/65 边形/`level=0` 玫瑰线均 `1 + 1` |
| 1.3 | 配对对齐(缺陷 3 早期尝试) | `_align_all_rails` / `_align_rail_events`;对 CA 只部分补齐(64/64 → 48/64),现已被 1.6 的重归属取代 |
| 1.4 | **输入合法性检查**(第 1 步) | `validate_paths` 检"共线重叠 / 多线共点";判别力: 15 例正常输入全 0,4 例人为退化全抓到 |
| 1.5 | **派生几何自检 + 降级渲染**(第 2 步) | `_check_rail_geometry` 检"同一线段左右交点数相等";不成立则整条降级为整条丝带 + 汇总告警 |
| 1.6 | **缺陷 3 的 CA 分支已修**: 逐段归属错位 | `_normalize_rail_attribution` 按沿轨弧长逐位配对 + 投影定归属;**逐段计数本来就相等的路径整条跳过**(对正常输入零影响)。`CA n=16 L4` 由 `1/0` → `64 ribbons / 65 holes` |
| 1.7 | 丝带分组配色 API | `ribbon_color` / `ribbon_swatch` / `ribbon_group_method`(5 种)与 `ribbon_groups`;`ribbon_swatch=None` 保持旧行为;22 个新用例 |
| 1.8~1.9 | 测试台与验收管线 | `tests/weave_checks.py`(A/C/D/E/F/G)+ `tests/test_weave.py`;`media/_review/{acceptance_render,campaign_*,screen_rosettes}.py` |
| 1.10~1.13 | 类一~类五矩阵完成 | 见上表头;类五平铺的关键结论: **通过率低且必须"搭接"不能"相切"**(`PA n=6 L2` 格距 1.75~1.85R 稳健,2.00R 相切档降级);瓶颈是"缺镜像事件"(§3 P0-0) |
| 1.14 | **复核: 校验器口径 + 输入清洗的尺度 bug + "两圆"更正** | 见下 §1.14(缺陷 5/6/7);A/B 仍 4/4 |
| 1.15 | **曲线输入保真 + 稠密折线的角点事件** | 见下 §1.15(缺陷 8 + `mobject_paths`);A/B 仍 4/4 |
| 1.16 | **玫瑰线降级为可选模块 + 核心测试解耦** | 见下 §1.16;`check_rosette_free.py` → 211 passed / 3 skipped |
| 1.17 | **缺陷 9 已修**: 重归属留下"查不到坐标的引用"→ 求解崩溃 | 见下 §1.17;全矩阵指纹 8 行崩溃 → 0 行、其余 1149/1166 行逐字节不变 |
| 1.18 | **缺陷 10 已修**: 落在端点的交点被固定参数容差丢掉(类型 B 的真因) | 见下 §1.18;全矩阵指纹"两态 deg=0" **0 行变化**、54 组已坏配置转为诚实降级 |
| 1.19 | **缺陷 1 的描边收尾**: 环形丝带不再有狭缝描边 | 拆环成 `Polygram` 双 subpath;A/B **4/4 相同**、全矩阵指纹 0 行变化、461 passed |
| 1.20 | **密采样曲线的可行编织配方**: 折线精度与丝带宽度匹配 | 步长 ≳ 4×offset;`N=16/20/32/40 @offset=0.05` 干净且 C/D/E/F 全过(渲染验证);示例场景 4 本来就是织的(11.1×offset);d5 用例(0.27×offset)保留降级 |
| 1.21 | **缺陷 3 的密采样自交分支已修**: "按交叉身份"切分让密采样自交曲线真正织起来 | 见 §3 P0-5 的"阶段 1 第三步已完成";密采样利萨如 `r=7` 且 C/D/E/F 全过;A/B 4/4、全矩阵指纹 20 行变化全是原本降级的配置 |

### 1.14 复核(2026-10-14): 校验器口径 / 清洗尺度 / "两圆"更正

- **缺陷 5(清洗尺度)**: `_is_non_collinear` 原来比较叉积**绝对量**(≈ `|v1||v2|sinθ`), 点一密就整段
  判共线 → `ParametricFunction` 默认采样**塌成直线**、`dt=0.005` 与 1024 边形环**输出空白**。
  改为比较 `sinθ` 后: `Circle` 仍 17 点(既有输出逐元素不变), 稠密曲线恢复正常。
  证据: `media/_review/audit_clear_paths_fix.py`、`audit_dense_*.py`。
- **缺陷 6(重归属崩溃)**: 同一轨道上的自交事件两条记录**共用一把交点键** → 改挂时 `KeyError`。
  新增 `_reservation_is_consistent()` 预演护栏, 不自洽就跳过重归属走降级。
- **缺陷 7(校验器误报, 影响面最大)**: C/D 的探针固定 `±1.5×offset`, 而压上方带子沿被压方切线的
  覆盖长度是 `offset/|sinθ|` → **θ ≲ 42° 时整个窗口落进压上方带子里, 两侧都判"连续穿过"**。
  实测失败全部落在 20°/30° 桶、≥50° 无一失败;被判失败的 30° 交叉放大渲染后是**标准编织**。
  G 的 8 个"不对称"孔洞实为**分解重复**。修正后重扫: `PA n=12 L2 / PA n=10 L3 / PA n=8 L4 /
  CA n=9 L1 / CA n=12 L4` 全部 **0 问题**;`CA n=16 L4 / n=15 L5` 仅剩 E(≈0.05% 采样点);
  CR/PR/PO 仍是真实损坏。证据: `audit_c_angle.py` / `audit_crossing_probe.py` / `audit_recheck.py` /
  `audit_zoom_scene.py`、`audit_g_cover.py`。
- **更正**: `_fix_path_flags()` 只让**约束**自洽, 丝带并未切分 —— 但"两圆不编织"是**我的误判**:
  修正口径(补上"交点本身"探针)后, 两圆是**交替编织**的(上交点断黄带、下交点断青带), C 检查 0 问题。
  证据: `media/images/audit_rings_zoom/Rings{Top,Bottom}.png`。
- **顺带量到的事实**: 求解 11.7~80.6 ms(96 路径 / 9600 交点 0.51 s), 而 `check_picture` 要 1.2~4.9 s
  (慢 60~100 倍)—— **瓶颈在检查层, 不在算法**;包 2364 行(缺陷弥补类 546 行 = 37%,HEAD 时 25%)、
  测试 2442 行、示例 1176 行、文档 1438 行、未入库探针 60 个(约 6574 行)。
  证据: `audit_bench.py` / `audit_stages.py` / `audit_size.py`。
- **"密铺"从未进入包**: 全仓库(`git ls-files`)无密铺代码, 只在 `media/_review/` 与本文档/`DEFECTS.md` 里。

### 1.15 曲线输入保真 + 稠密折线的角点事件

- 新增 `manim_lace.lace.mobject_paths()` + `CURVE_SAMPLES = 8`: 每个三次贝塞尔段重采样;
  **全是直线段的子路径直接取端点**(所以 `Line` / `Rectangle` / `Polygram` 几何逐字节不变 → 无需重定 A/B 基线);

| 输入 | 之前 | 现在 |
| --- | --- | --- |
| `Circle(2)` | 17 个控制点, 半径 2.069 | 65 个采样点, 半径 **2.0**(残差 8e-6 来自 Manim 自身近似) |
| `ParametricFunction` 默认采样 | 200 个点, **渲染空白** | 801 个点, 到真曲线最大距离 **5.6e-4** |
| 该曲线的示例场景 | `media/images/audit_curve_scene/CurveOld.png`(全白) | `CurveNew.png`(真正的编织丝带) |
| `Square(3)` / `Star(4)` / `Line` | 5 / 11 / 2 个点 | 不变 |

- **缺陷 8(角点事件丢失 → 输出空白, 已修)**: 逐段子图靠"相邻同轨线段共享端点"的事件串起来, 而该事件
  由通用求交登记、判据是叉积绝对量 `|d1 × d2| < 1e-9` —— 采样一密就误判成平行(实测 800 段采样圆弧
  末 3 段事件数 `1/0/0` → 链断 → 无环 → 空输出且**无告警**)。修法: 求交与 `_segment_line_intersection`
  的平行判据改为比较 `sinθ`(`PARALLEL_SIN_ATOL`) + `_fill_rail_corners()` 按结构补共享角点。
- **降级路径的"整条丝带"对开放路径用错公式**: `annulus_polygon` 假定两条闭合环, 开放路径会得到自交
  多边形(真空气白洞)。新增 `_plain_band()`: 闭合 → 环形带, 开放 → 左右偏移线合围的条带。
- **已知限制**: 曲线**自交**处仍走降级(平滑采样的利萨如 `dt=0.1/0.05/0.02` 三档都是"整条降级 +
  7 个交点无丝带覆盖"), 与缺陷 3 的 CR/PR 一族同源(§3 P0-0/P0-1)。证据: `audit_curve_scene_metrics.py`。

### 1.18 缺陷 10: 落在端点的交点被固定参数容差丢掉 → 类型 B 的真因(已修)

- **症状**: CR/PR/PO 一族的"缺镜像事件"(同一交叉只有一侧登记), 逐段计数不等 → 整条路径降级;
  全矩阵 **91 组**配置受同一原因影响(含 `CR/PR n=10 L3` 的 16 条坏段)。
- **真因**: `vectorized_intersection` 用**固定参数容差** `1e-9` 判"交点是否落在线段内",
  而参数误差在"交点落在对方线段端点"时可到 `1e-7` —— 两条中心线恰好交在**对方拐点**上时
  (星形旋转全等的结构性位置), 偏移线求交就落在对方轨段端点上, 实测 `ub = -9.3e-8` → **整条丢掉**。
  此前记录的"缺镜像事件 / miter 截断 / 两轨相切"都是**误诊**(截断另有其证: 伸长系数 max=1.24)。
- **修法**: 端点判据改尺度无关 `tol = DEFAULT_ATOL / |d|`(几何距离口径, 与 `DEFAULT_ATOL` 一致);
  `validate_paths` 里复制的那份求交逻辑同样对齐(顺带统一平行判据为 `PARALLEL_SIN_ATOL`, 零行为变化)。
- **必须配套**: 补登记之后逐段计数变相等 → 退化路径不再降级、转而按索引配对 →
  实测强行切分 **52/52** 组违反 C/D/E/F。故新增 `_has_joint_crossing(i)`
  ("交叉落在偏移线拐点上"同样判降级), 取代原先"靠丢事件意外保护"的效果。
- **验证**: ① `tools/matrix_digest.py`: "两态 deg=0"配置 **0 行变化**、A/B 4/4、448 passed;
  ② 被新判据降级的 54 组**改动前就全部违反可见性检查**(逐组核对, 0 误伤,
  `media/_review/guard_false_positive_audit.py`); ③ 7 组"已知良好"配置判据一律不触发。
- 证据: `media/_review/tol_event_diff.py`(宽/严容差多登记了什么)、`joint_crossing_probe.py`
  (接头交叉分布: 退化配置 40~96 个、已知良好 0 个)、`vertex_crossing_layout.py`(拐点局部链结构)、
  `tol_wins_audit.py`(单靠容差修复时 0/52 组合格 → 证明判据必须配套)、`tol_audit.py`、
  `guard_false_positive_audit.py`。

### 1.20 密采样曲线(利萨如)的可行编织配方: 精度与丝带宽度匹配

- **结论**: 稠密采样的自交曲线(缺陷报告 `d5-dense-curve` = `dt=0.01 @offset=0.05`)在当前架构下
  **无法编织**(配对契约要求"同一线段左右偏移线交点数相等", 而同一次自交的两侧交点沿轨相距约
  `2×offset`, 密采样段长只有 `0.27×offset` → 必然落到不同线段)。但把**折线精度与丝带宽度匹配**后,
  **现有实现就能正确编织**: 实测 `步长 ≳ 4×offset` 的配置干净 ——
  `offset=0.05`: `N=16/20/32/40`(7.6~18×offset) 全部 **不降级 + C/D/E/F 全过**;
  `offset=0.1`: `N=16/20` 干净(9.0×/7.4×)、`N=32` 只剩 E(4.7×)、`N≥40` 降级(≤3.8×)。
- **渲染验证**: `media/_review/lissajous_weave_render.py` → `lissajous_check/lissajous_n{20,32,40}.png`
  (7 个交叉处穿插清楚、8 个孔洞露出、0 跳过交点)。`examples/lace_scenes.py::TestLaceScene4`
  (`dt=π/20` + `scale(3)` + `offset=0.1`, 步长 **11.1×offset**)本来就一直是织的。
- **注意规律不单调**: 中间某些 N 反而降级(`offset=0.05` 时 `N=24`(12.5×)、`N=48`(6.3×)), 因为
  交叉点落在折线顶点/段中的位置会改变 miter 接头与事件归属; 只有"远大于 4×offset"才稳定。
- **对真正修复的意义**: ① 顺带确认了 **D(过/欠交替)对这条曲线是可满足的**(7 个交叉 = 14 次通过,
  粗配置 D 全过、`skipped=0`) —— §3 P0-1 里担心的"非交替织法"(§3 P1-8)不是这条曲线的障碍;
  ② 剩下的唯一障碍是**归属/配对**(按交叉身份, 而不是"同一段的左右第 k 个事件"), 见 §4-23/§4-24。
- **证据**: `media/_review/lissajous_{resolution,threshold,weave_render,relax_guard,guard,pair}_probe.py`。

### 1.19 缺陷 1 的描边收尾: 环形丝带不再有狭缝描边

- **症状**: 无自交闭合路径的环形丝带(`annulus_polygon` 的"外环 + 反向内环 + 狭缝")在**有描边**时,
  狭缝(两条零宽度重合边)被画成一条横跨带子的细线, 一圈丝带看起来被小缝隔断 —— `stroke_width=1`
  也看得见(缺陷报告的 `d1-square__after.png` 右上角、`d1-hexagon__after.png` 右顶点)。
- **根因**: 环带(annulus)是双连通区域, 一条简单闭合轮廓表示不了它, 必须切一刀(狭缝)才能缝成
  单轮廓; 填充靠非零绕数抵消狭缝, 但**描边会把轮廓的每一条边都画出来**, 包括狭缝边。
- **修法**: `Lace._generate_visuals` 改走 `_ribbon_mobject`: 用 `_annulus_loops` 识别环形丝带
  (结构标记 = 外环闭合点与数组首点**逐位相同** + 内环自身闭合 + 外逆内顺 + 外环面积更大), 拆回两条
  闭合环后用 `manim.Polygram` 建成**一个 VMobject 的两个子路径**。Manim 的 cairo 后端
  (`Camera.set_cairo_context_path`)按"锚点不连续"切子路径, 每个子路径单独 `new_sub_path` +
  `close_path` → 描边是内外两条连续圆环、**没有跨轮廓的边**; 填充仍是非零绕数(外 +1 / 内 −1 →
  内区绕数 0, 依旧镂空)。非环形丝带(交织片段 / 开放路径条带)仍是单轮廓 `Polygon`, 逐字节不变。
- **为什么不是"内环外环各自填充"**: 两条环都填充 = 实心团块(就是缺陷 1 本身); 只描边 = 两个细圆圈
  而不是"带"; 外盘 + 背景色内盘则依赖绘制顺序(`Lace` 先画 holes 再画 ribbons, 且 holes 有独立
  配色), 且会在重合边界留抗锯齿缝。反过来说, 只要两条环是**独立子路径**且**绕向相反**, 非零绕数
  规则下就镂空 —— manim 从不设置 cairo 填充规则(全包 grep `fill_rule` 零命中), 用的是默认
  `FILL_RULE_WINDING`(OpenGL 后端走耳切三角化, 按 ring 结构挖洞, 两个后端都成立)。
- **验证**: ① A/B(`media/_review/ab_slit_{old,new}`, 基线 = **同一工作区**只回退那一行的副本,
  避免混入"未提交的缺陷 9/10 修复"与历史基线的差异)**4/4 png md5 相同** —— 这 4 个场景不含
  环形丝带(玫瑰线是编织的、网格是开放线段、矩形与星形相互交叉), 顺带证明改动对既有底线零影响;
  ② `tools/matrix_digest.py` 与 `digest_guard*.txt` **逐字节相同**(几何层一个字节没动);
  ③ `461 passed`(13 个新用例: 双 subpath / 绕向相反 / kwargs 保留 / 交织片段不拆 / 开放条带不拆 /
  拆分-回缝逐位一致 / 四种反例); ④ 按缺陷报告同参重渲 `d1-square` / `d1-hexagon` / `d2-circle`,
  细线消失、填充区域与线宽不变。
- **证据**: `media/_review/slit_probe.py`(拆分/回缝逐位校验)、`slit_render_check.py` +
  `slit_check/{d1-square,d1-hexagon,d2-circle}/`、`ab_slit_old` vs `ab_slit_new`、`digest_slit.txt`。
- **影响面**: 只改渲染层 `manim_lace/lace.py`; `manim_lace/interlacing.py` 只有文档改动(在
  `annulus_polygon` 里写明"外环闭合点与数组首点逐位相同"这个被拆环依赖的输出格式约定)。

### 1.17 缺陷 9: 重归属留下"查不到坐标的引用" → 求解崩溃(已修)

- **症状**: 7 组高阶玫瑰线在构造中途抛 `KeyError`, 整幅图**求解失败**(`PA n=7 L7` /
  `PA n=11 L8` / `CA n=12 L6` / `CA n=15 L7` / `CA n=19 L8` / `CA n=20 L8` / `CR n=19 L4`)。
- **根因**: 事件的身份是 `(本方线段, 对方线段)`; 重归属改挂线段时只改了自己的标识, 而
  **同一条线段上常常只有一部分事件改挂**(实测 `CA n=9 L4` 的 36 号线段 6 个事件里只走 1 个)
  → 对方那条记录重建列表时写回旧标识 → 列表引用的标识查不到坐标。
- **修法**: `_commit_rail_reattribution()`(按**事件**找另一端记录改写对方标识) +
  `_rail_references_are_consistent()`(提交后校验, 不过则整体回滚走降级)。
  ⚠️ 已否决的快速修法: 按**线段**整体替换标识(会把没动的事件一起搬走, 实测把 `CA n=9 L4`
  从"正常"打成"降级 + 36 处悬挂引用")。
- **验证工具(新增入库)**: `tools/matrix_digest.py` 打全矩阵指纹(5 花型 × n=5~20 × 各阶 ×
  两种 offset + `Circle`/`Square`/两档采样的利萨如 = 1166 行), 改动前后逐行 diff 即可说清
  "哪些配置变了、变成什么样"。**本次: 崩溃 8 行 → 0 行, 9 行本来就损坏的配置片段变细,
  其余 1149 行逐字节不变**; 回归 `tests/test_weave.py::TestReattributionConsistency`
  (旧实现下 16 个用例里 14 个失败); A/B 仍 4/4。
- 证据: `media/_review/matrix_digest.py`(探针版仍留在 `media/`)、`defect9_repro.py`、
  `reattr_debug.py`;工具: `tools/matrix_digest.py`。

### 1.16 玫瑰线降级为可选模块 + 核心测试解耦

- `manim_lace/__init__.py` 改为 PEP 562 惰性转发(`__getattr__` + `_ROSETTE_EXPORTS`):
  `from manim_lace import StarRosette` 照旧可用, 但 `import manim_lace` **不加载**玫瑰线
  (子进程测试锁定);玫瑰线缺失时抛 `AttributeError`(而不是 `ImportError`), 便于 `hasattr` 与补全。
- 玫瑰线相关的测试夹具/用例全部 `pytest.importorskip("manim_lace.rosette")` 保护;
  `tests/helpers.py` 的玫瑰线路径改走库的公开转换 `mobject_paths()`(与 `Lace` 同一条输入通道)。
- **验证**: `media/_review/check_rosette_free.py`(禁止导入 `manim_lace.rosette`)→ **211 passed / 3 skipped**;
  全量仍 426 passed。
- **剩下的是"物理搬走"**, 清单已写进 `AGENTS.md`: `rosette.py` / `test_rosette.py` / `__init__.py` 的转发与
  `__all__` 的 4 个名字 / `test_package.py` 的 `ROSETTE_EXPORTS` / README 玫瑰线小节 / 4 个 rosette 示例
  与浏览页模板 / **A/B 底线的 Scene0-1**(它们是玫瑰线输入, 拆分前要换成非玫瑰线的固定输入)。

---

## 2. 正在做

- **本轮已完成**: §2 收尾(探针清理 26 个 + 3 批提交) → **§3 P0-5 阶段 1 第三步**(按"交叉身份"
  切分, 让密采样自交曲线真正织起来) —— 见 §3 P0-5 的"阶段 1 第三步已完成"与 `CHANGELOG.md`。
- **收尾内容**: ① 删除 `media/_review` 里**已被否决 / 已被定案取代**的归因类探针 **26 个**
  (清单见 §6「已删除」行; 结论全部保留在本文件 §4 与 `DEFECTS.md`, 探针只是当时的一次性推导脚本);
  ② 把工作区改动**分 3 批提交**: 工具入库(`tools/matrix_digest.py` + `tools/defect_report.py`) →
  缺陷 9/10 + 环形丝带描边收尾(核心 + 测试) → 文档对齐(本文件 / `DEFECTS.md` / `CHANGELOG.md` / `AGENTS.md`)。
- **原先计划的 ①~⑤ 五批未能实现**: 缺陷 1~8 已随 `5dc2df2` 落地, 剩下的缺陷 9/10 与阶段 0/1 的只读方法
  在 `interlacing.py` / `tests/test_lace.py` / `tests/test_weave.py` 里**互相缠绕**, 逐 hunk 切会产出
  跑不过测试的中间提交; 故按"**每批都能过 `pytest` + `ruff`**"的最小干净粒度切分(每批都跑 A/B)。
- **下一步**: §3 P0-5 剩余两项 —— ① 把 `holes` 接到同一套"按交叉身份"的表示(密采样利萨如现在
  `h=0`); ② CR/PR/PO 一族的拐点/切触交叉(仍被分组护栏拦下)。

---

## 3. 未完成

### P0(决定"降级机制能否退役")

- **0. 平铺(与 CR/PR 同源)的瓶颈 = "缺镜像事件"(类型 B)**, 不是相切本身: 相切档(`PA n=6 L2 @2.00R`)
  出现"两侧**事件总数**都不等"的路径, 而稳健档(`@1.80R`)全是类型 A(完美匹配)。修法与 P0-1 的接头
  拓扑是同一件事。判定要用**二分图最大匹配**(`tiling_match.py`)。
- **1. 接头拓扑**: `generate_offset_lines` 的 miter + `MITER_LIMIT = 5.0` 强行封角, 接头附近产生额外
  交点。⚠️ **2026-10-14 钻取修正**(证据 `media/_review/joint_topology_probe.py` / `joint_topology_drill.py` /
  `joint_wedge_zoom.py`): 接头拓扑**只对 PO 家族直接有效**(21 顶点里 10 个被截断, 坏段↦截断距离=0);
  `CR/PR n=10 L3` 的缺镜像事件与截断无关(伸长系数 max=1.24), 真因是**两轨恰好相切**(B-L 角点顶点
  落在 A-L 上, 距离=0) —— 旋转全等图形的结构性切触, 换接头拓扑不会消失;平滑曲线(利萨如)
  **与凹侧折返无关**(2026-10-14 实测: offset ≤ 0.05 时"曲率半径 < offset"的顶点 **0** 个、
  坏段仍 **56** 个; 采样加密到 dt=0.005 也还是 56 个), 真机制是"同一次自交的两侧交点沿轨相距
  约 2×offset, 密采样下跨 4~8 条线段"导致的逐段归属错位(证据
  `media/_review/lissajous_{weave,pair,guard,relax_guard}_probe.py`; 详见 §4-23/§4-24 与 DEFECTS §3)。
  ✅ **2026-10-14 补充**: ① **D(过/欠交替)对这条曲线可满足**(7 交叉 = 14 次通过, 粗配置 D 全过、
  `skipped=0`), 故"非交替织法"(P1-8)不是它的障碍; ② 不换实现也能让它织起来 —— **把折线精度与丝带
  宽度匹配**(步长 ≳ 4×offset)即可, 见 **§1.20** 的配方与渲染验证; ③ 要覆盖密采样输入, 仍须做
  **按交叉身份配对**的表示层改造(§4-23/§4-24)。
  类型 B 的修复方向 = 先解决**跨段镜像的表示**(见 DEFECTS §3 的已否决快修),
  接头拓扑降级为 PO 一族的专项。会改变几何 → 仍需先定 A/B 基线策略。
  **最小单元已定位(同日追加, 证据 `media/_review/gt_corners_probe.py` / `odd_event_probe.py` / `orphan_zoom.png`)**:
  `CR/PR n=10 L3` 的 8 个单侧事件的**对应中心线段并不相交** —— 两条中心线的交叉恰好落在**对方中心线
  的拐点**上(参数 `u = 0 ± 1e-7` 或 `1 ± 1e-7`, 而本侧严格在 (0,1) 内部), 也就是"一条射线正好穿过
  另一条星形的角点";同一个交叉的四个角点因此被拆到拐点两侧的线段上。**已否决**"把中心线不相交的
  事件直接剔除": 它能立刻恢复配对契约(CR/PR 坏段 16→0、利萨如 64→0, 且对 7 个健康配置零影响),
  但 `check_picture` 显示这些是**真交叉**, 剔掉就变成"双带同绘"(A/C/D/E 全亮) —— 正确方向是
  **把拐点交叉的四个角点重新归拢到同一次交叉**(表示跨段镜像), 不是删事件。证据
  `cross_centerline_probe.py` / `cross_centerline_matrix.py` / `drop_candidate_eval.py`。
  ⚠️ **2026-10-14 定案(缺陷 10)**: 上面"缺事件"这个前提本身是**误诊** —— 那些事件从来都在,
  另一侧的交点落在对方轨段**端点**上, 被 `vectorized_intersection` 的固定参数容差 `1e-9`
  (参数误差实为 `1e-7`)整条丢掉。修法见 §1.18(端点容差尺度无关 + `_has_joint_crossing` 判据)。
  于是 P0-1 剩下的部分收窄为:**几何本身退化**(拐点重合 / 切触 / miter 截断)导致的"拐点交叉",
  这类配置现在**诚实降级**(而不是静默画错); 要真正编织它们, 需要在表示层把"一次交叉的四个
  角点"归拢到一起(仍是 §1.18 里那条没走完的路)。
- **2. 残差收敛(按新口径)**: `CA n=9 L5` D=3+E=1、`CA n=16 L5` D=2+E=1、`CA n=16 L4` E=1(≈0.05%
  采样点)、`CA n=15 L5` E=1。量级极小, 优先级低。
- **3. 浅角/近平行交叉没有自动检查**: θ ≲ 42° 的交叉被 C/D 跳过(`stats["skipped"]`), 需要尺度无关的
  判据(例如直接比较"两侧可见丝带片段是不是同一片")。
- **4. `merge_paths` 会改写开放路径的起点/方向**(`longest_chain` 从哪个端点起步取决于字典序):
  几何不变但左右偏移线互换, 影响 `by_path` 分组与 D 的遍历方向。

- **5. 表示层改造(A: 把"一次交叉的角点"当整体事件)的基线策略 —— 2026-10-14 拟定, 待确认**。
  影响面实测(`media/_review/baseline_impact_probe.py`): 全矩阵指纹 1166 行里**健康 535 行**
  (deg=0 且 issues=0)、**降级/有 issues 631 行**(PR 166 / CR 157 / PO 141 / PA 90 / CA 75 / 利萨如 2);
  A/B 4 个场景**当前全部健康**(降级 0、issues 0)。
  - **核心思想"只修坏的"**: 新构造路径**仅在现行实现会降级时启用**(现行 `_check_rail_geometry` 已经算出
    `_degraded_paths` / `rail_issues`, 天然就是那个开关) → A/B 4/4 与指纹 535 行**构造上**逐字节不变,
    可能变化的只有那 631 行。
  - **分期**: 阶段 0 = 只加只读的"交叉事件分组"结构 + 语料探针(不接决策路径, 输出必须零变化);
    阶段 1 = 对"现行降级"的配置改用按交叉分组的配对/归属; 阶段 2(可选) = 切触交叉的角点归拢
    (利萨如 7 交点里的 2 个相切自触、CR/PR 的切触)。
  - **验收口径(红线不变)**: ① 健康配置逐字节不变(A/B 4/4 + 指纹 535 行 + 现有 461 测试, 除被明确改写的
    条目); ② 任何"由降级变编织"的配置必须 `check_picture` C/D/E/F **全过**(沿用"不降级无残差"门槛),
    否则**保持降级**(宁可不变好, 不可静默画错); ③ 每步跑 `pytest` / `ruff` / 指纹 diff / A/B,
    变更记 `CHANGELOG` + `PROGRESS`。
  - **阶段 0 已完成(2026-10-14, 只读探针 `media/_review/crossing_group_probe.py`, 核心零改动)**:
    分组规则 = "以中心线交叉点为锚, 把非接缝轨记录按 `2.5*offset/max(sinθ,0.3)` 归属"。105 组玫瑰线 +
    3 个利萨如精度测得: **利萨如三档全部完美**(7 组 × 8 条记录, 孤立 0、歧义 0); PA 干净(歧义 246/2736);
    而 **CR/PO/CA 歧义 1900~2300、空组 281~463**(这些正是退化配置, 交叉彼此近到阈值内)。
    → 结论: 几何聚类在"干净"配置上够用, 在退化族上不够; **"歧义/孤立 = 0"可直接当 Phase 1 的启用护栏**
    (与"只修坏的 + 宁缺勿滥"完全同向)。
  - **阶段 1 第一步已完成(2026-10-14)**: 核心新增**只读**方法 `_centerline_crossings(i)` /
    `_crossing_groups(i)`(启用护栏: 有孤立/歧义即返回 `None`) / `_crossing_attribution(i)`
    (组内按"自己所在线段"分簇 = 分支, 簇内按**对方路径 + 对方轨道**配对), **尚未接入任何决策路径**。
    验收: `ruff` 全绿、**465 passed**(+4 用例)、全矩阵指纹与改动前基线**逐字节相同**
    (`digest_phase1.txt` vs `digest_guard.txt` = `0311D9…`)、A/B 4 场景按构造不变。
    模拟接线(`media/_review/phase1_measure.py`)显示**新路径当前一处也启用不了**(护栏正常工作):
    - **利萨如: 多重点拦下** —— 它多次穿过原点, 同一位置有**两个相距 1.7e-5 的锚点**
      ("一次交叉 = 4 个角点"的模型在这里不成立) → 下一步必须先**合并重合锚点**并支持 k 重点;
    - CR n=10 L3 / PO n=5 L2: 分组**歧义**(与阶段 0 的测量一致) → 需要结构性身份, 或继续降级;
    - A/B 4 场景: 健康 → `_degraded_paths` 为空, 新路径根本不会进入 ✓。
  - **阶段 1 第二步(2026-10-14)**: ① `_merge_crossings` 合并**重合锚点**(交叉正好落在折线顶点上时
    会被两条相邻线段对各枚举一次, 实测相距 1.7e-5); ② `_branch_clusters` 按**中心线段号的环距**分簇
    (两条轨道的 `arc` 参照系不可比, 实测同段号处相差 0.78; 闭合路径用环距, 否则同一分支会被绕回处劈开);
    ③ `_nearest_segment`: 一次交叉的两对记录必须落在**同一段**(交叉所在的那个中心线段)上 ——
    取"这一对自己所在的段"会让两对相隔 7 段, `_set_ribbons` 于是**完全不切分**(实测只切出 2 条丝带)。
    效果: 密采样利萨如**分组干净、归属算出 28 对、契约恢复**, 重切 **r 从 2 → 14**(切分真的发生了);
    ⚠️ 但画面仍 `C×7/D/E`(交叉处双带同绘) —— 缺口落在 **`_set_ribbons` 的片段构造**(14 条片段里
    "压上/被压"的语义还没对上)。按约定**画面不过就保持降级** → 新路径**仍不接线**:
    零输出变化(指纹 `0311D9…` 与基线逐字节相同、466 passed、A/B 4 场景按构造不变)。
  - **✅ 阶段 1 第三步已完成(2026-10-14): 结论更正 —— 缺口不在"交替模型无解", 而在"跨段配对"**。
    用**与 D 检查同源**的口径复核(`media/_review/phase1_step3_diag.py`: `all_centerline_crossings` +
    `crossing_pass_flags`)显示: **所有采样密度下, 7 个自交交叉的"两次通过在通过序列里的位置差恒为
    奇数"**(9/7/5/9/7/5/7) ⇒ "沿曲线交替 + 每个交叉恰一方压上"**数学上总有解**, 交替模型没有问题;
    真正的分界是"折线段长 ≳ 5×offset 才不降级"(`N=20`(8.3×)与 `N=32`(5.0×)不降级, `N≥40`(≤4.0×)
    降级)。⇒ 原先那条"缺口定案在交替模型"**作废**(它是按 `_path_crossings` 的旧口径推的 —— 那个口径
    把"每段内按索引两两分组"当成了通过序列, 而密采样下一次穿越的两个交点**跨 4~8 段**, 根本不在同一段)。
  - **真正的根因(定位并修复)**: `_set_ribbons` 的逐段索引配对隐含前提"一次穿越的两个交点落在同一条
    线段上"。密采样时它们沿轨相距约 `2*offset`(正好是对方丝带宽度), 实测段载荷出现 `(3,3)` 的**奇数段**;
    契约自检只保证"每段左右计数相等", 抓不到跨段错位。追查中还发现两处配合缺陷: ①
    `_commit_rail_reattribution` 会把**两条不同的边折叠到同一把新键**(坐标互相覆盖, 事件挂在"不在其上的
    线段"上, 实测原点自交的两条分支共用候选段时命中); ② 按交叉归属会因"两条分支共用同一批候选段"
    把不同交点归到同一段。
  - **修法(已接线, 只修坏的)**: 新增 `_crossing_ribbon_cycles`(与"段"无关的表示: 穿越由
    `_crossing_groups` 给出, 覆盖区间按弧长处理、**跨越闭合点时取补集**)、`_cluster_pass_records`
    (按**对方轨道**配对 —— 密采样时对方**段号**不同, 不能按段号配)、`_outer_boundary_vertices`
    (切口端头沿**对方偏移线折线**走, 否则端头直线斜穿中心线, 实测交叉附近"一侧双覆盖、另一侧破洞"
    各一处); 在 `_check_rail_geometry` 判降级之后由 `_try_crossing_weave` 对降级路径**只读地**尝试一次
    (失败即放弃、不改任何中间状态), 并对"片段退化为零面积 / 片段数与切刀数不符"兜底; 重归属补
    "新键不折叠"护栏。
  - **量到的边界**: 密采样利萨如(`dt=0.01/0.02/0.05 @offset=0.05`)由"降级 + `C×7/D/E`"变为
    **7 条丝带 + C/D/E/F 全过**; A/B 4 场景逐字节一致; 全矩阵指纹 **20 行变化全部是原本降级的配置**
    (健康配置 **0 行变化**), 其中 `PR n=6 L=3` 变编织后画面 A/C/D/E 不合格 → 被运行期兜底拦回降级。
    证据: `media/_review/phase1_step3_{diag,probe,dump,reattr_check,verify}.py`、
    `tests/test_weave.py::TestCrossingWeave`。
  - **已定案(2026-10-14 拍板)**: (1) 启用范围 = "只修坏的"; (2) 验收 = 严格"宁缺勿滥"(由降级变编织的
    必须 `check_picture` C/D/E/F 全过, 否则保持降级); (3) 允许把降级断言改写为"编织断言 +
    `check_picture` 断言"。三条都已按此执行。
  - **2026-10-15 结构整理(纯重构, 零行为变化)**: 把布局抽成 `_crossing_layout`(每轨道的点序 +
    按弧长排序的全部穿越), 丝带片段(`_crossing_ribbon_cycles`)与孔洞边界共用一个入口; 片段的
    两个兜底(片段退化 / 片段数与切刀数不符)补上 `logger.debug` 诊断。验收: 指纹 20 行变化与
    A/B 均与上一轮**逐字节相同**、`471 passed`。
  - **2026-10-15: holes 的"按交叉身份"尝试(未完成, 已回滚, 结论留档)**。目标: 让密采样利萨如也
    生成孔洞(现状 `h=0`; 不影响 C/D/E/F, 因为 F 检查在有孔洞时才有对象可查)。试了两条路都不通:
    1. **共享键图**(节点 = `frozenset((本方线段, 对方线段))`, 沿用既有 `_set_holes` 的约定)+
       "挖掉所有穿越区间": 自交时**同一把键会在同一条轨道上出现两次**(例如
       `{(0,1,5),(0,1,502)}` 既在段 5、也在段 502 的点序里), 于是"区间定位"有歧义 ——
       `setdefault` 取第一次会把区间从 13 条边放大到 1016 条, 整图只剩 2 条边、0 个环;
    2. **坐标去重 + 端头链**: 端头链的"对方折线顶点"与轨道点序里的点**坐标相同但键不同**, 会被
       `cycle_basis` 串成零面积的退化环(实测 15~21 顶点、面积 ~1e-16); 而把节点按坐标合并, 端头链
       又退化成"已有的边"(片段数 7 → 1)。
    ⇒ 真正需要的是**表示层**: 把"一次穿越的四个角点"归拢成一个整体事件(自交里"同一个交点"只是
    一次通过的一部分, 而现有数据结构用"线段对身份"表示它, 天然会在同一条轨道上出现两次) ——
    这与下面 ② 是**同一件事**。
  - **下一步**: ① 上面的表示层改造("一次穿越 = 一个整体事件")能同时解决 holes 与 CR/PR/PO 一族;
    ② CR/PR/PO 的拐点/切触交叉现在仍被分组护栏拦下(它们"歧义/孤立 ≠ 0"), 保持降级。

### P1(覆盖与简化)

- **5. 类五变体 B 扩展**: 更大补丁(≥3 圈)、其它正多边形平铺(八边形+正方形、三角形)、Kaplan 第 3 步
  真正把"尖点延伸进空隙"(当前用"尖点伸出量"近似)。
- **6. 共线重合按"双股带"处理**: 让 §1.4 检出的 96 组从"降级轮廓"变回可编织 —— 把 CR/PR L≥3 修好的
  另一条路。
- **7. 把四类用例固化成 `tests/` 回归**(含"不得降级"与指标断言), 而不只是渲染图。
- **8. 结构性限制(交替织法)**: `三圆链`(三圆两两相交)的约束图是三角形 → 奇环 → 2 着色无解;
  `三重嵌套`、`六边形+双三角` 同类。需要"非交替织法"另立课题。
- **9. 星形多边形自交处的织法**: `{5/2} 星 + 五边形`、`{7/3} 星 + 圆` 在自交点处未全过;自交点现已纳入
  C/D 枚举, 需按新口径重测后再定级。
- **10. 玫瑰线的"物理搬走"**(§1.16 的清单)。

### P2(工程)

- **11. `check_picture` 的空间索引**: 19 单元补丁(约 400 条路径)要做上百万次逐片点测试, 慢到不可用。
  同一批输入求解 11.7~80.6 ms(§1.14), 检查要 1.2~4.9 s —— 该优化的是检查。
- **12. 其余可复用工具**: `acceptance_render.py` / `campaign_*.py` / `screen_rosettes.py` 仍未入库
  (依赖 `media/` 的实验数据);`ab_render.py` 已入库 `tools/`。
- **13. `images/` 里 4 张展示图**: manim 0.19.1 + 旧场景产物, 是否替换待定。
- **14. README**: 尚未写明 `ribbon_swatch` / `ribbon_group_method` 的用法。

---

## 4. 已经试过并被否决的做法(别再重复)

| # | 尝试 | 结论 | 数据 / 原因 |
| --- | --- | --- | --- |
| 1 | **缩小丝带宽度**解决缺陷 3 | ❌ 无效 | 扫 4%→0.05% × r_max:`CR n=10 L3` 仍 16/40 不等;miter 接头随 offset **等比缩放**, 尺度不变 |
| 2 | 把"偏移线自交"当退化信号 | ❌ 不是判别器 | 干净配置 `CA n=12 L4` 有 48 处自交且左右对称、渲染正常 |
| 3 | 把"输入自交"当退化信号 | ❌ 不是判别器 | `PA n=12 L2` 24 处、`CA n=12 L4` 48 处,均正常 |
| 4 | 不对称的段**不切分**(丝带原样穿过)代替整路径降级 | ❌ 更差 | 不对称普遍时整条丝带一次都不切:`CA n=15 L5` bad 19.3%→**71.9%**;已回退 |
| 5 | 早期一次 `_set_ribbons` **整体重写**(按事件分组 + 每交叉翻 flag) | ❌ 回退 | 把正确配置弄坏:`CA n=9 L1` ribbons 9→19、`PA n=8 L4` 32→65。**必须保持"事件列表从索引 0 起两两分组、under 跨度取组间"的既有约定** |
| 6 | 依赖探针报"120 处本应命中却漏检的交点" | ⚠️ 探针假象 | 跨轨道比较**事件 id 集合**本就不相等;且把**相邻线段的共享角点**也算成缺失 |
| 7 | 按"交叉身份"重写配对(算中心线交点当锚点) | ⚠️ 前提被证伪 | CA 一族**不缺几何**(cross/self/corner 三类事件总数两侧相等 128/128), 只是**逐段归属错位** → 只需重归属 |
| 8 | 收紧配对规则(要求对方段号 ±1) | ❌ 更差 | CR/PR 的可用伙伴数 63→52 |
| 9 | 交叉身份几何配对 + **最小代价分配**(`linear_sum_assignment`) | ❌ 无效 | CR/PR 的最大匹配本就 52<63, 换算法救不了 |
| 10 | 按几何**补出缺失的镜像事件**(各沿直线外推 ≤3×offset 求交) | ❌ 回退 | 补缺会误触发, 把已修好的 `CA n=9 L5/n=15 L5/n=16 L5` 重新打成降级 |
| 11 | 补登记"共线相邻段的共享角点"(作为缺陷 3 的成因) | ❌ 归因有误 | 11 个配置实测**全部已登记** → 零命中, 代码已删 |
| 12 | 用"旋转无关的径向覆盖率指纹"自动去重测试图 | ❌ 饱和失效 | 所有配置对的指纹 L∞ 距离都在 0.40~0.50, 连 CA vs CR 都分不开 → 改用显式规则(§0 门槛) |
| 13 | **身份兜底配对**(逐位配对失败时改用"对方线段兼容 + 最近"的贪心双射) | ❌ 无收益 | 平铺可用格距列表一字未变;失败路径多是类型 B(两侧事件总数不等), 配对方式救不了 |
| 14 | 把平铺失败归因于"相切/近似相切" | ⚠️ 归因不准 | 缺失事件的线段其实是正常横穿(`sin`=0.71~1.0);缺失在**镜像侧**(类型 B) |
| 15 | 把"简单闭合几何体组合不编织"归因于相切 | ⚠️ 归因不准 | 真因是两处记账/相位问题(`_rail_events` 接缝切分 + 闭合路径 flag 全 `True`), 都已修 |
| 16 | 用**固定距离**探针(±1.5×offset)判"压上/被压" | ❌ 系统性假阳性 | θ ≲ 42° 时窗口落进压上方带子里 → 两侧都判"连续穿过"(`PA n=12 L2` 24 个交点里 12 个误报, ≥50° 无一失败)。改为距离随夹角自适应 |
| 17 | 用"多边形一一对应"判旋转对称(G) | ❌ 假阳性 | 区域分解不唯一: `CA n=12 L4 / n=16 L4` 各有 8 个孔洞旋转后完整落在其它孔洞里(8/8 验证) |
| 18 | 按"是否穿过对方轨支撑直线"(符号翻转)剔除**贴而不穿**的切触事件, 让契约自然恢复 | ❌ 更糟 | `CR n=10 L3` 坏段 16→**40**, 正常配置 `CR n=8 L4` 0→**24**: 切触事件存在**跨段镜像**(A-L 段 j 的切触, 镜像在 A-R 另一段上, 已被弧长修复配对), 朴素剔除拆散配对。证据 `media/_review/tangency_probe.py`;sinθ 判据也无效(切触在角点上, 登记线段方向不平行, CR/PR 无一 sinθ<1e-3) |
| 19 | 按"**对应中心线段是否相交**"剔除单侧事件(判据精确: 参数区间 `u ∈ [0,1]` 比 `sinθ` 尺度无关) | ❌ 画面错 | 契约**确实**恢复了(`CR/PR n=10 L3` 坏段 16→0、平滑利萨如 64→0)、且 7 个健康配置零剔除零影响; 但 `check_picture` 显示 CR/PR/Lisajous 全部出现 A/C/D/E(`交点被 2 条丝带覆盖`=双带同绘)。原因是这些事件本身是**真交叉**(两条中心线确实相交, 只是恰好交在对方拐点上), 剔掉等于不切分。三种插入位置(重归属前/后/近失补齐后)结果一致。证据 `cross_centerline_probe.py` / `drop_candidate_eval.py` |
| 20 | 缺陷 9 的快速修法: 维护"旧线段 → 新线段"映射, 按**线段**整体替换对方标识 | ❌ 反向弄坏 | 同一条线段上**只有一部分事件**改挂(CA n=9 L4 的 36 号线段 6 个事件里只走 1 个), 整体替换会把没动的事件也搬走 → 该配置从"正常编织(37 h / 36 r)"变成"降级 + 36 处悬挂引用"。正确做法是按**事件**定位另一端记录(见 §1.17) |
| 21 | 缺陷 10 只修端点容差、**不**加退化判据 | ❌ 静默画错 | 补偿登记交点后逐段计数变相等 → 退化路径不再降级、转去按索引配对: 实测"由降级变编织"的 52 组配置**全部**违反 C/D/E/F(`tol_wins_audit.py`: 通过 **0/52**)。必须同时加"交叉落在拐点上"的结构判据(`_has_joint_crossing`) |
| 22 | 用 `sinθ` 之类判据识别"接头退化" | ❌ 无区分度 | 接头处两条轨的方向一般**不平行**, CR/PR 无一 `sinθ < 1e-3`; 端点距离判据精确(退化组 40~96 个事件、已知良好组 **0** 个) |
| 23 | 放开缺陷 9 的**重归属护栏**(`_reservation_is_consistent` 恒真, 等价 `defect_report --variant no-guard`)让平滑利萨如"织起来" | ❌ 静默画错 | 护栏确实是拦路虎(offset ≤ 0.05 时逐位配对 **28/28** 全过、护栏判 `False`), 放开后也**不再降级**(2 条丝带); 但画面是**双带同绘**: C(交点被 2 条丝带覆盖 ×8)、D(过欠未交替)、E(**677/6115** 采样点被多条丝带重叠) —— 与 §4-19/§4-21 同一失败模式。必须先把"一次交叉的四个角点"归拢(按**交叉身份**配对), 不是放开护栏。证据 `media/_review/lissajous_relax_guard_probe.py` |
| 24 | 靠**缩小 offset 或加密采样**让平滑利萨如编织 | ❌ 无效 | offset 0.2→0.01 坏段 60/64/56/50/32/18(**不收敛于 0**), 采样 dt 0.1→0.005 稳定在 40/56/56/56/56; offset=0.005 不降级是**欠分辨**巧合(带宽 0.01 < 段长 0.02), 画面仍 C/D/E |
| 25 | ① 把"弧长逐位配对"换成**按交叉身份配对**(对方路径+轨道相同, 组内按段号就近); ② 把预演护栏改成"**只查键存在**"(不预扣) | ⚠️ 必要但**不足** | 契约确实恢复(`offset=0.05 dt=0.05`: 配对 28 对、护栏通过、降级 0、逐段不等 0); 且对其它配置**零影响**(逐段计数本来就相等的路径整条跳过, `N=40`/`N=24` 与基线逐项一致)。但画面仍"双带同绘"(C×4/D/E, 只切出 **2** 条丝带, 而粗配置是 7 条) → 缺口转移到 `_set_ribbons` 的片段构造(段内事件成对假设 `range(2, num_pairs-1, 2)` / 交替). 证据 `media/_review/lissajous_crossing_pair_probe.py`。**顺带查清护栏的真实缺陷**: 它的预演把"互为一对、共享同一把键"的两条记录当成两个独立搬运者(第一条 `discard` 后第二条就找不到键) → 只要有自交事件必然判 `False`, 与配对方式无关(`media/_review/lissajous_guard_diag.py`: 28 组共享键全是这种成对记录)。**配对判据三连否决**(均实测): ① "对方段号排序逐位" → 对内段差 100~266;② "几何最近邻" → 自交时两条分支在空间上同样近, 段差 200~422;③ "对方路径+轨道分组 + 自己段号就近" → 整条路径直接失败。**真因**(`media/_review/lissajous_crossing_dump.py`): 7 个自交点 = **5 个正常(4 角点) + 2 个相切自触(2 角点)**, 后者两条分支的角点两两重合、镜像记录缺失 → **与 CR/PR 一族的"两轨相切"完全同源(P0-1)**, 不是利萨如独有的几何 |
| 26 | 端头按"**对方线段标识完全相同**"配对(本侧左右轨各取一条镜像记录) | ❌ 判据错 | 自交时对方丝带在原点这类位置**也会跨段**: 左轨记录连的是对方段 502、右轨连的是 506, 标识并不相同 → 根本配不出"一次穿越"。正确判据是按**对方轨道**(1 / 2)配对, 见 `_cluster_pass_records`; 与之配套, "一次穿越的两个交点在同一段上"这个隐含前提在密采样下同样不成立(段载荷出现 `(3,3)` 的奇数段) |

> **判定的正确姿势**:判断"配对能不能成"要用**二分图最大匹配**(判定,不是启发式);判断"该修哪里"要先做
> **事件三分类**(cross/self/corner)与**总数对照**, 再看逐段归属。**2026-10-14 追加**:动手改算法之前先确认
> "这个红是真的还是**校验器的口径问题**" —— 本次 6 个红灯里 5 个是校验器假阳性, 顺着它改只会越堆越复杂。

---

## 5. 关键口径与红线

1. **非零环绕 ≠ 奇偶**: Manim/cairo 用**非零环绕**填充, `weave_checks.points_in_polygon` 用**奇偶**;
   对降级产出的自交环形带结论完全不同(实测 `CA n=16 L4` 奇偶报 8348 个"破洞", 非零为 0)。
   验收图一律用非零环绕(证据 `fill_rule_probe.py`)。
2. **回归底线**: `examples/lace_scenes.py` 前四个场景必须与重构前逐字节一致(§0.3)。
3. **收录门槛**: 不降级无残差 + 密度 `r ≥ 30` + 代表性(详见 §1 表头)。
4. **自交点 vs 路径间交点**: `centerline_crossings()` 只枚举不同路径之间;判断"到底在不在编织"要
   `crossing_count()` 的两个数一起看。C/D 的入口已统一走 `all_centerline_crossings()`(含自交)。
5. **判定与渲染必须同尺度**: 平铺的相切/近平行退化对浮点极敏感(同一组路径在 R=1 与 R=2.5 下结论
   相反);任何预检/筛选都要用与渲染完全相同的缩放与偏移(`campaign_tiling.py` 的 `gate()`)。
6. **容差必须尺度无关**: 判共线/平行一律比 `sinθ`, 不比叉积绝对量(否则采样一密的曲线会被删空或
   让角点事件丢失, 见缺陷 5/8)。

---

## 6. 实验脚本索引(`media/`,已被 gitignore;`tools/` 已入库)

| 分组 | 脚本 |
| --- | --- |
| **入库工具** | `tools/ab_render.py`(A/B 底线)、`tools/matrix_digest.py`(全矩阵指纹, 改动前后逐行 diff)、`tools/defect_report.py`(缺陷对照报告: 历史树 A/B 渲染图 → `media/defect_report/index.html`) |
| 验收 / 门禁 | `acceptance_render.py`(单配置面板 + 指标 + 缺陷标记 + `index.html`)、`campaign_rosette.py`、`campaign_tiling.py`、`campaign_kaplan.py`、`campaign_simple.py`(`--category`)、`screen_rosettes.py`、`flag_probe.py`、`fill_rule_probe.py` |
| 判定 / 归因 | `tiling_match.py`、`tangency_probe.py`、`two_circles_probe.py`、`crossing_count.py`、`after_metrics.py`、`closed_probe.py`、`ab_scene_probe.py`、`lace_review.py`、`plain_roses.py`、`tiling_feasibility.py`、`check_validate.py`、`label_debug.py`、`grid4_probe.py`、`step3_targets.py`、`cd_calib.py`、`weave_checks_head.py` |
| **缺陷 3 类型 B 钻取**(2026-10-14) —— **本批已删** | `mirror_probe.py`(逐轨列事件与弧长)、`odd_event_probe.py`(按几何聚类的"交叉团")、`gt_corners_probe.py`(理想 4 角点 ↔ 实际登记点, 含"多出来的 8 个事件")、`orphan_zoom.py`+`orphan_zoom.png`(局部放大)、`cross_centerline_probe.py` / `cross_centerline_matrix.py`(候选判据的影响面)、`drop_candidate_eval.py`(三种插入位置 + `check_picture` 验收) |
| **缺陷 9 钻取**(2026-10-14) | `matrix_digest.py`(全矩阵指纹的探针版)、`dangling_probe.py`(逐阶段数悬挂引用)、`reattr_debug.py`(按事件/按线段两种标识改写的差异)、`defect9_repro.py`(测试口径的复现)、`changed_cases_check.py`(受影响配置的 `check_picture` 对照) |
| **缺陷 10 钻取**(2026-10-14) | `vertex_crossing_layout.py`(拐点处两侧轨段与事件全貌)、`rail_sequence_align.py`(左右轨事件按弧长并排, 看配对从哪错开)、`tol_event_diff.py`(宽/严端点容差各自登记了什么)、`joint_crossing_probe.py`(接头交叉的分布)、`tol_audit.py` / `tol_wins_audit.py`(容差改动的影响面: 只改容差时 0/52 合格)、`guard_false_positive_audit.py`(新判据 0 误伤)、`changed_render.py`(改动前后渲染对照, 支持 `--strict`) |
| **阶段 1 第三步钻取**(2026-10-14) | `phase1_step3_diag.py`(通过序列 ↔ 配对位置差, 与 D 检查同源)、`phase1_step3_probe.py`(接线后每个交叉的覆盖/flags/C 原文)、`phase1_step3_dump.py`(段载荷与片段包围盒)、`phase1_step3_reattr_check.py`(新键折叠检测 + 事件到所辖线段的距离)、`phase1_step3_verify.py`(新路径的生效范围与画面判定)、`digest_diff.py`(两份全矩阵指纹的新旧状态对比) |
| **2026-10-14 复核** | `audit_bench` / `audit_stages`(耗时与阶段分解)、`audit_size`(规模与占比)、`audit_c_angle` / `audit_crossing_probe`(浅角假阳性)、`audit_g_exact` / `audit_g_cover` / `audit_g_e` / `audit_g_raster` / `audit_g_ribbons`(G 的分解差异与光栅口径)、`audit_clear_paths_fix` / `audit_dense_*` / `audit_merge_paths` / `audit_open_arc` / `audit_arc_events`(清洗、合并与角点事件诊断)、`audit_recheck` / `audit_curves_weave`(口径重扫与曲线织法)、`audit_two_rings*` / `audit_rings_*` / `audit_curve_scene*` / `audit_dense_scene` / `audit_zoom_scene`(渲染证据)、`check_rosette_free`(解耦检查) |
| **已删除**(结论留 §4) | 归因类: `attribute_missing` / `reason_probe` / `miss_probe` / `where_missing` / `shift_probe` / `seam_count`;匹配类: `match_fail` / `match_debug` / `pair_shape` / `reject_reason`;事件三分类: `step4_*`;判别力: `step3_scoping` / `policy_compare` / `controlled`;对比拼图: `compare` / `step2_effect` / `step31_effect`;杂项: `diagnose` / `probe_input` / `overlap_detail` / `rail_signals` / `per_rail` / `corner_aware` / `render_lace_scenes` |
| **2026-10-14 收尾再删** | **26 个文件**(23 个脚本 + 3 个附带产物),均为"已被否决的做法"或"已被定案取代"的一次性推导脚本: `why_curve_not_woven` / `mirror_probe`(+txt) / `odd_event_probe` / `gt_corners_probe` / `orphan_zoom`(+png) / `tangency_probe` / `cross_centerline_probe` / `cross_centerline_matrix`(+txt) / `drop_candidate_eval` / `lissajous_relax_guard_probe` / `lissajous_crossing_pair_probe` / `lissajous_guard_diag` / `lissajous_crossing_dump` / `phase1_group_dump` / `_patch_report` / `check_defects_parse` / `find_d6_case` / `pick_d4_case` / `show_card` / `v020_api_probe` / `validate_report_page` / `report_cases_check` / `report_meta_check` |

复现任一实验: `uv run python media/_review/<脚本>.py`(仓库根目录执行)。

---

## 7. 关键入口速查

| 想知道 | 看哪 |
| --- | --- |
| 算法四步流程 | `Interlacing` 类 docstring(`manim_lace/interlacing.py`) |
| 曲线输入如何折线化 | `manim_lace.lace.mobject_paths` / `CURVE_SAMPLES` |
| 输入清洗的尺度判据 | `_is_non_collinear`(比 `sinθ`;缺陷 5) |
| 求交的平行判据 / 角点补齐 | `PARALLEL_SIN_ATOL` / `_fill_rail_corners`(缺陷 8) |
| 事件重归属(CA 分支) | `_normalize_rail_attribution` / `_rail_events` / `_is_mirror_event` / `_reservation_is_consistent` |
| 重归属的提交与护栏(缺陷 9) | `_commit_rail_reattribution` / `_rail_references_are_consistent` |
| 求交的端点容差(缺陷 10) | `vectorized_intersection`(端点容差 = `DEFAULT_ATOL` ÷ 线段长度, 尺度无关) |
| 接头退化的结构判据(缺陷 10) | `_has_joint_crossing`(由 `_check_rail_geometry` 调用, 与"逐段计数不等"并列判降级) |
| 改动对既有配置的影响面 | `tools/matrix_digest.py`(全矩阵指纹) + `tools/ab_render.py`(示例场景逐字节) |
| 缺陷对照报告 | `tools/defect_report.py`(历史树 A/B 渲染 + 网页; 文案直接解析 `DEFECTS.md`, 不另维护) |
| 配对 / 降级策略 | `_set_ribbons` / `_check_rail_geometry` / `_plain_band` / `_align_all_rails` / `_align_rail_events` |
| 输入检查 / 派生几何诊断 | `validate_paths` / `VALIDATE_MODES` / `Interlacing.path_issues` / `rail_issues` / `_degraded_paths` |
| 丝带配色 | `Lace` 的 `ribbon_color` / `ribbon_swatch` / `ribbon_group_method` / `ribbon_groups` |
| 可见性模型与口径 | `tests/weave_checks.py`(`crossing_probe_distance` / `stats["skipped"]`) |
| 缺陷台账 / 变更历史 | `DEFECTS.md` / `CHANGELOG.md` 的 `[Unreleased]` |

---

## 8. 约定(别破坏)

- 参数非法抛 `ValueError`(类型问题 `TypeError`);几何不可实现必须显式报错, 不产出 `inf` / `nan`;
- 空输入退化为空结果;输出多边形统一逆时针且首尾点重复;
- **任何容差都要尺度无关**(比 `sinθ`, 不比叉积绝对量);
- **核心(代码与测试)不依赖玫瑰线**;曲线输入必须走 `mobject_paths()`;
- 改核心逻辑必须补 `tests/` 用例 + `ruff check` / `ruff format --check` 全绿;
- **任何改动都要过 §0.3 的 A/B 字节级对比**;变更记入 `CHANGELOG.md`。
