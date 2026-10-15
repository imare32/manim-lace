# 自交路径在 ribbon 后端的"交叉处横向短线"问题

> 状态：**已修复并实机验证**（2026-10-16）
> 触发输入：`examples/scene_gallery.py::StarGallery`（真五角星 `{5/2}`，`offset=0.12`，`weave_mode="free"`，默认 `ribbon_backend="boolean"`）
> 复现渲染：`python examples/build_gallery.py --only StarGallery`，产物 `media/gallery/StarGallery.png`
> 复现量化：`pytest tests/test_regions.py -k section_cuts`、`pytest tests/test_optional_manim.py -k "seams or straight"`
>
> 本文旧版（2026-10-15）把根因判为"切口（notch）边界被碎断"，**这个判断是错的**，落地过程中被实测推翻：真正的横穿短线是**分段接缝弦本身被描边**。见 §3 与 §7 的 B/C 两行。

---

## 1. 现象

五角星的每个自交交叉处都能看到 4～9 条**横向短黑线**（像梳子齿），而不是两条干净的"上方股线边缘压过下方股线"的对角线。丝带总宽只有 `2 * offset = 0.24`，所以任何横穿股线的线在视觉上都呈现为"短线段"——这既是现象也是干扰判断的地方：**并非所有短线都是缺陷**（沿股线方向的短边是真实轮廓），但横穿股线的短线一条都不该有。

| 版本 | 切口 | 交叉处外观 |
|---|---|---|
| 初版（自交跳过切口） | `removed_area = 0` | 完全是平涂五角星 + 分段接缝短线，**没有编织关系** |
| 切口修复后 | `removed_area = 0.232899` | 有上下关系，但每个交叉多出 4～9 条横向短线（本问题） |
| 现在 | 同上 | 每个交叉 2 条对角线（上股边缘压过下股），无横穿短线、无接缝白线 |

---

## 2. 机制回顾：遮挡怎么实现，接缝与切口分别是什么

渲染层**没有画任何遮挡用的四边形**：

- `src/manim_lace/render/regions.py`（boolean 后端）对每个交叉做
  `visible_strip[under] = visible_strip[under].difference(lens)`，
  其中 `lens = _local_lens(under_band, over_band, crossing.point)` 是两条**偏移带**在该交点处的交叠分量（"偏移带求交切口"）。
  上方那一遍面积不动，靠 `draw_index`（被压者先画）让它的填充与描边落在上面。
- arrangement 后端同效果，但归属按平面剖分逐面判定。
- stroke 后端是中心线分段 + 加宽断口（`offset / |sinθ|`）+ 绘制顺序。

自交要成为"两遍"，路径必须被切成分段（`build_sections(..., pass_windows=True)`，仅 boolean 后端）：每个自交的**每一遍两侧**各切一刀，否则两个切点之间的那一整段同时装着两遍的料，切它会把压在上面那一遍也挖掉。切分点落在折线顶点上时报 `REGION-SECTION-SEAM`。

这条切分线在渲染层有两种完全不同的身份，本问题的全部难点都在这里：

| | 分段接缝（seam） | 切口边（notch） |
|---|---|---|
| 几何 | 切分点处**横跨股线**的弦（从一条侧边到另一条侧边） | 下股停在**上股侧边**上的那一段边界 |
| 股线走向 | 股线从这里笔直穿过去，两侧是同一条股线的料 | 股线在这里真的停了，另一侧是上股的料 |
| 描边 | **不能描**：描了就是股线中间的一道横线（本问题的梳子齿） | **必须描**：这就是用户看到的编织对角线 |
| 标记 | `RibbonRegion.flush_edges` | 不在 `flush_edges` 里 |

两者在局部**长得一样**（都是"穿过/贴着股线的直线段"），而且在自交上切口边正好落在上股的轮廓线上——这决定了没法用"共边匹配"把它们分开（见 §3(b)）。

---

## 3. 根因（修正后的判断）

### (a) 主因：`_stroke_runs` 把接缝边自己也描了（off-by-one）

旧实现按顶点遍历环形折线，遇到接缝边时先把"下一个点"追加进当前 run，再判断该边是否 flush：

```python
if vertex in flush:            # 判断用 vertex，但 appended 的是 following
    ...
current.append(points[following])   # ← 接缝边的终点先被塞进 run 了
```

结果是**接缝弦整条留在 run 里被描边**，于是每条接缝都在股线中间画一道贯穿的线。五角星 31 个片段**全都带接缝**（`flush_edges` 非空），所以每个交叉的每条接缝都画了出来，实测修复前被描的接缝边 **82 条**——这就是梳子齿。现在改成"边 `vertex→following` 是接缝就**先收口当前 run**、再从接缝之后重新起 run"，接缝一定不进任何 run。

### (b) 标记本身也不可靠：共边启发式在自交上不可能对上

旧 `mark_flush_edges` 用 `_overlaps` 找"两个片段共有且共线的整条边"。这在自交上不成立：

- 接缝弦只是邻片段某条边的**一段**（两次布尔运算把同一条弦切成不同数量的共线小段），端点级比较必然漏；
- 更要紧的是自交的**切口边正好落在上股的轮廓线上**（被减掉的 lens 就是以它为边界），所以"共边"这件事在切口边和接缝上同时成立，无法区分。

现在接缝的判据是几何本身：`_section_boundary_arcs` 取出该路径**真正被切分**的弧长点，`_cut_lines` 在每点按切向做法线得到横跨股线的弦（`point ∓ normal * 4 * offset`），`mark_flush_edges` 只标记**落在这些弦上的片段外边**。两个后端都把自己那一份 cuts 传进来（boolean 有窗口弦、arrangement 只有交叉弦）。

### (c) 次要：一条直边被切成共线碎段

布尔运算与多边形化会把一条直边切成 2～3 段共线小段，逐段描边就是"一排短划线"。`_rejoin_collinear` 在描边前把这类中间顶点并回直线（垂直距离 < 1e-7），**但保留"走回头路"的零宽尖刺顶点**——删掉它会缩短笔画、在轮廓上留缺口。实测五角星修复前有 **6 处**共线中间点，并回后为 0。

**结论**：几何一直是对的（面积核算、切口、上下关系全部正确），坏的是"哪些边该描、描的时候怎么切段"。每个交叉本来只需要 2 条编织对角线，现在就是 2 条。

---

## 4. 已确认的事实（当前数据，五角星 `offset=0.12`）

```text
31 个可见区域 / 5 个自交 / 诊断 ['REGION-OVERLAPPING-SECTIONS'](info)
removed_area   = 0.232899
band_area = union_area = painted_area = covered_area = 2.892729
region_area_sum = 2.962651（比可见面积多 0.069922 = 分段之间的真实重叠）
flush_edges：59 条，分布在 31/31 个区域上；接缝弦 57 条（每弦 2～4 个点）
outlines：111 个 mobject = 54 条开口折线（run） + 57 条"填色重述"接缝
ribbons：31 = 可见区域数（一一对应）
描边线段 88 条；其中 < 0.15 的 20 条全部沿股线方向（13 条侧边碎片 + 7 条切口边）
```

1. **切口几何正确**：`bow` / 八字（90°）`removed_area = 0.040000 = 4·offset²`（解析 lens）；五角星 5/5 自交全部切口。
2. **覆盖精确**：`painted_area == union_area == band_area`，可见区域把丝带恰好铺满一次（`painted_area` 是区域并集）。
3. 两个后端在自交上也面积逐位一致（`tests/test_arrangement.py` 断言）。
4. 五角星现在报 `REGION-OVERLAPPING-SECTIONS`（info）：分段之间确实重叠 0.069922（= `region_area_sum - painted_area`），这是 boolean 后端"分段 + 绘制顺序"模型的已知代价，如实上报而不是藏起来；旧版文档里"region_area_sum == painted_area、4.4e-16 浮点噪声"是更早一次构建的记录，已过期。
5. 跨路径输入（圆 + 直线）`flush_edges` 为空、`outlines` 为空——问题**只出现在自交**（`tests/test_optional_manim.py::test_a_cross_path_crossing_needs_neither_seams_nor_open_outlines`）。
6. 自交输入的 `flush_edges` 非空（31/31 区域），且**切口边不在其中**：接缝弦的中点落在股线中心线上且长度等于一个带宽，切口边则沿上股侧边、中点距中心线一个 `offset`（`tests/test_regions.py::test_a_self_crossing_marks_the_section_cuts_as_seams_not_the_notches`）。arrangement 后端另有一条对应断言：它的每条边界都被 noding 切开，所以接缝到那里是被切成小段的切分线，判据改为"线段所在直线过交点"（`tests/test_arrangement.py::test_the_arrangement_marks_a_self_crossing_cut_as_a_seam`）。
7. 描边 run 中没有共线中间点，唯一允许保留的共线顶点是零宽尖刺（`tests/test_optional_manim.py::test_outline_runs_keep_a_straight_edge_straight`）。

---

## 5. 修复内容（已落地）

| 位置 | 改动 |
|---|---|
| `render/regions.py::_section_boundary_arcs` | 取出一条路径真正被切分的弧长点（排除开放路径自己的 0/length 端帽） |
| `render/regions.py::_cut_lines` | 由切分点 + 切向法线构造横跨股线的弦（`point ∓ normal * 4 * offset`），供标记使用 |
| `render/regions.py::mark_flush_edges` | 改写为"标记落在这些弦上的片段外边"；两个后端各自传入 cuts |
| `manim_api.py::_ring_paths` / `_stroke_runs` / `_seam_chords` | 同一套环形遍历拆成两条互补输出：接缝之间的轮廓 run（并回共线点）与接缝弦本身 |
| `manim_api.py::_rejoin_collinear` | 并回共线中间顶点，保留零宽尖刺（否则笔画被缩短、轮廓出现缺口） |
| `manim_api.py::_outline_mobjects` | 每条 run 一个描边 mobject（一个 mobject 里放多条子路径会被 `start_new_path` 用**正是那条接缝**连起来） |
| `manim_api.py::_region_groups` | 带接缝的片段填充不描边，轮廓进 `Lace.outlines`；同层再放一份"填色重述"的接缝，`z_index = -0.5` |
| `manim_api.py::_extend_ends` | run 两端沿自身末边外延半个线宽，让接缝两侧的 run 互相搭接，而不是在两个 butt 端点上留下一个半透明白点 |
| `manim_api.py::build_animation` / `examples/scene_gallery.py::_outline_animations` | 播放 `lace.outlines`（否则带接缝的片段丢轮廓） |

两个渲染细节值得单独说：

- **接缝为什么要补一笔填色**：相邻两片是各自独立的多边形，共享边上两个多边形各自只覆盖一部分像素，不补的话股线中间会透出一条背景色细线。补的这笔画在**所有填充之下**（`z_index = -0.5`，纸层是 -1），因此每个填充都会重新盖住它、只在抗锯齿的缝里露出来，同时也不会啃到任何轮廓线。
- **run 端点为什么要外延**：一条 run 停在接缝处、另一条从接缝另一侧接上，两个 butt 端点在同一个点上相遇，抗锯齿会让那个点只被覆盖一半——填色重述会从这里透出来变成轮廓上的一个灰点。外延量取半个线宽，且不超过该末边长度的一半，所以只会落在这条边本来就在的直线上。

---

## 6. 验证

修复前后用同一套脚本在五角星上量的数字（`offset=0.12`，boolean 后端）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 被标记的接缝边 | 82 | 59（全部落在真实切分弦上） |
| 被描边的接缝边 | 82（每条都画了出来） | 0 |
| `outlines` 的开口折线（run） | 82 | 54 |
| 描边线段总数 | 150 | 88 |
| 其中短于 0.15 的 | 31 | 20（全部沿股线方向） |
| run 里的共线中间点 | 6 | 0 |

外观验证（对着 `media/gallery/StarGallery.png` 的交叉点裁切放大）：每个交叉只剩上股两条侧边压过下股，股线内部既没有横穿短线、也没有接缝白线；轮廓在接缝处连续（run 搭接生效）。

---

## 7. 已排除的假设（都做过实验，不要再走一遍）

| # | 假设 | 实验 | 结论 |
|---|---|---|---|
| A | 短线是"遮挡四边形"的边 | 读代码 + 逐片段清单 | 否；遮挡靠 `difference` + 绘制顺序，无覆盖几何 |
| B | 短线是接缝弦，只是没被标记 flush | 端点量化匹配（`digits=9`→`6`） | 只对了一半：标记确实不可靠（§3(b)），但**已标记的接缝弦同样在被描边**（§3(a)），所以"标记全对"也去不掉短线 |
| C | 端点匹配不够，要按共线包含匹配 | 改 `_overlaps` | 有效但只到 47 条；说明共边匹配这条路本身就区分不了切口边与接缝（切口边正好压在上股轮廓上） |
| D | 把切口后的分段并回去（`unary_union`）就没有缝了 | 改出片循环为按路径合并 | **否决**：缝没了，但切口边变成内部线，单色风格下编织关系完全消失（星形变成一块平涂） |
| E | 一个 VMobject 里放"闭合环（填充）+ 开口线（描边）" | 实机渲染实验 | **否决**：Manim 会把开口子路径也填充（右上三角形被填满） |
| F | 把窗口收紧到 lens 边缘（`1.25·offset/sinθ`）就能让弦落进切口里 | 解析推导 | 只有 u=0（交点本身）的弦整条落在 lens 内；窗口弦必须整条横穿股线，必然可见 → 不能靠放位置解决，只能不描 |
| G | 接缝不描边就完事，剩下的浅色细线不用管 | 放大渲染 | **否决**：不描边后相邻填充的共享边会透出背景色细线，必须补一笔填色重述（§5） |

---

## 8. 相关代码位置

| 位置 | 作用 |
|---|---|
| `src/manim_lace/render/regions.py:109` | `_section_boundary_arcs`（该路径真正被切分的弧长点） |
| `src/manim_lace/render/regions.py:131` | `_cut_lines`（切分点处的横跨弦） |
| `src/manim_lace/render/regions.py:191` | `mark_flush_edges`（只标记落在弦上的外边） |
| `src/manim_lace/render/regions.py:448` | `_self_crossing_reach`（窗口长度 `2·offset/max(sinθ,0.2)`） |
| `src/manim_lace/render/regions.py:647` / `835` | `build_sections` / boolean 后端开启 `pass_windows=True` |
| `src/manim_lace/render/regions.py:746` | `_self_crossing_lens`（自交切口 = 偏移带局部求交） |
| `src/manim_lace/render/regions.py:306` | `_drop_folds`（去掉布尔运算在环上留下的零面积折返尖刺；相邻缺陷，见 `CHANGELOG` 的 ribbon 环条目） |
| `src/manim_lace/render/regions.py:355` | `_ring_points`（环点转换，折返尖刺在这里被清理，两个后端与洞一起受益） |
| `src/manim_lace/render/regions.py:1113` | boolean 后端的 `mark_flush_edges(..., cuts=_cut_lines(...))` 调用点 |
| `src/manim_lace/render/arrangement.py:408` | arrangement 后端的同一调用点 |
| `src/manim_lace/manim_api.py:561` | `_region_groups`（返回 ribbons/holes/outlines） |
| `src/manim_lace/manim_api.py:688` | `_rejoin_collinear`（并回共线点，保留零宽尖刺） |
| `src/manim_lace/manim_api.py:712` / `747` / `757` | `_ring_paths` / `_stroke_runs` / `_seam_chords` |
| `src/manim_lace/manim_api.py:771` / `792` | `_extend_ends` / `_outline_mobjects` |
| `src/manim_lace/manim_api.py:558` | `_SEAM_FILL_Z = -0.5`（填色重述的层号） |
| `src/manim_lace/manim_api.py:320` | `build_animation`（construction 阶段播放 outlines） |
| `examples/scene_gallery.py:275` | `_outline_animations`（画廊场景播放 outlines） |

## 9. 当前未提交的改动

`src/manim_lace/render/regions.py`、`src/manim_lace/render/arrangement.py`、`src/manim_lace/manim_api.py`、`src/manim_lace/engine.py`、`src/manim_lace/topology/solver.py`、`tests/test_regions.py`、`tests/test_arrangement.py`、`tests/test_optional_manim.py`、`tests/test_conflict_strategy.py`、`tests/test_topology.py`、`tests/test_stroke.py`、`examples/scene_gallery.py`、`examples/scene_rosette.py`、`examples/build_gallery.py`、`README.md`、`CHANGELOG.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md`、`docs/SELF_CROSSING_OUTLINE_TICKS.md`（本文）。排查用的 `scratch_*.py` / `scratch_*.txt` / `scratch_*.png` 与临时对比图已删除。