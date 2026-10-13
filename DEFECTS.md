# interlacing 算法缺陷清单（待修）

> 2026-10-13 对 `Lace` / `Interlacing` 做了一次系统性正确性测试后整理, 共 **3 个缺陷**,
> 均带复现、根因与验收标准。修复时请按仓库约定补 `tests/` 回归用例并记入 `CHANGELOG.md`。

## 0. 测试方法（复验用）

不只看"能跑通", 而是按 **画家顺序可见性模型** 做几何验证:
`Lace` 先画全部 `holes`、再按列表顺序画 `ribbons`(后者居上),
对每个交点/中心线采样点计算"最终可见多边形", 检验:

| 编号 | 检查项 |
| --- | --- |
| A | holes/ribbons 顶点全部有限; 多边形闭合、逆时针、正面积、无重复连续顶点 |
| C | 每个中心线**真交点**处恰好一方"压上": 沿双方中心线离交点 ±0.5×offset 的 4 个探针, 可见丝带归属本方且为同一条(压上方的丝带连续穿过交点, 被压方断开) |
| D | 沿每条闭合曲线按弧长遍历, 过/欠**严格交替**(闭合曲线还需首尾相接交替) —— 编织效果的定义性质 |
| E | 密集中心线采样(步长 0.05×offset)无跨带重叠(≥2 条不同归属丝带覆盖同点)、无背景破洞 |
| F | 每个孔洞至少部分可见(未被丝带完全涂盖) |
| G | holes/ribbons 整体在旋转 2π/n 下不变(玫瑰线的对称性保持) |
| H | `Lace(rosette)` 端到端可建, 数量与 `Interlacing` 一致 |

判定为"编织正确"的配置: n=12 PA L2(示例场景同款)、n=9 CA L1、n=8 PA L4、PA n=10 L3、
CA n=12 L4, 以及 X 形两线基准; 上述性质在 offset = 0.6% / 1.5% / 4% × r_max 三档下稳定。
测试脚本为临时脚本、已删除; 需要固化为 `tests/` 回归用例时可以再说一声。

---

## 缺陷 1: 无自交点的闭合曲线渲染成实心团块

**症状**: 花瓣互不相交的玫瑰线(所有 level=0)与普通 Circle/Rectangle 类简单闭合图形,
`Lace` 输出一个实心色块 —— 内部孔洞被丝带涂盖, 丝带结构完全消失。

**复现**:

```python
import numpy as np
from manim_lace import StarRosette
from manim_lace.interlacing import Interlacing

rose = StarRosette(7, 0, "PO")
paths = [np.asarray(sp, float) for m in rose.family_members_with_points() for sp in m.get_subpaths()]
inter = Interlacing(paths, 0.05)
# holes=1, ribbons=2; 在图形内部采样, 可见的是 ribbon 而不是 hole
```

预期视觉 = 环形丝带(中间露出孔洞色); 实际 = 实心团块。

**根因**: 无自交点时, 每条偏移线段的 `d_seg_intersects` 只含相邻段的共享顶点
(端点相交会被正常登记), `num_pairs == 2`, 于是 `_set_ribbons` 的 U 型补形循环
`for k in range(2, num_pairs - 1, 2)`(`manim_lace/interlacing.py:762`)为空,
每条线段只贡献"沿线"边 —— per-path 图退化为**左右两条完整的偏移环**,
ribbons = 两个"圆盘"大多边形。两者都填丝带色, 内圆盘后绘制把 hole 盖死
(`manim_lace/interlacing.py:712` `_set_ribbons`)。

即: 这类路径从未产出应有的**环形(annulus)丝带**(外环 + 反向内环合成一个多边形),
也没有阻止内轮廓丝带覆盖孔洞。`tests/test_interlacing.py:142`
`test_closed_square_produces_a_single_hole` 只断言了 holes 数量, 未覆盖视觉效果。

**修复方向**: 闭合路径无交点(或交点数不足)时, 把左右偏移环合并成环形丝带;
或在内轮廓 ribbon 上"挖洞"(按画家顺序先画内轮廓再画外轮廓也可得到环形,
但更稳的是直接产 annulus)。

**验收标准**: 对 65 边形圆环 / 任意 level=0 玫瑰线, holes ≥ 1 且每个 hole 有部分
可见(检查 F 通过); 视觉为环形。

---

## 缺陷 2: `Lace(Circle)` 输出完全空白

**症状**: README 与 `Lace` docstring 里的示例输入 `Lace(Circle(radius=2), offset=0.2)`
渲染结果**什么都没有**: `num_holes == 0 and num_ribbons == 0`。

**复现**:

```python
from manim import Circle
from manim_lace import Lace

lace = Lace(Circle(radius=2.0), offset=0.2)   # 0 holes, 0 ribbons -> 空白
```

**根因链**(已逐环实验证实):

1. manim `Circle` 的 `get_subpaths()` 返回 32 点(锚点 + bezier 控制柄);
2. `clear_paths` 去重去共线后剩 18 点(17 边形): 45°/135°/225°/315° 的锚点因两侧
   控制柄对称共线被删;
3. 0° 锚点 `(2, 0)` 成为闭合点, 其前后两段边 `(2,-0.530)→(2,0)` 与 `(2,0)→(2,0.530)`
   **共线**(同在 x=2 上) —— 这是"绕回"型共线, `clear_paths` 的连续三点扫描
   (`manim_lace/interlacing.py:104-110`)看不见闭合点处的情况, 冗余顶点被保留;
4. `generate_offset_lines` 在该顶点的 miter 输出使偏移线的首末段共线;
5. `_cal_intersections` → `vectorized_intersection`: 两条共线且共享端点的线段
   `denom ≈ 0` 被判"平行", `mask=False`(`manim_lace/interlacing.py:348`)——
   唯一交点丢失;
6. `_set_ribbons` 中首尾两段的 `num_pairs == 1 < 2` 被 `continue`
   (`manim_lace/interlacing.py:748-749`), 两条偏移环在闭合点断开 → 无环 →
   `ribbons = 0`; `_set_holes` 同样无环 → `holes = 0`。

对照实验: 手工删掉该冗余顶点(17 边形 → 16 边形)后恢复 `holes=1, ribbons=2`。

**修复方向(二选一或都做)**:

- `clear_paths` / `merge_paths` 对闭合路径处理**绕回共线**(闭合点处的连续三点,
  含首尾边); 这是根治点, 也顺带消除退化的 miter;
- `vectorized_intersection` 或 `_cal_intersections` 对"共线且共享端点"的相邻线段
  补登记交点(与现有非平行相邻段的处理一致)。

**验收标准**: `Lace(Circle(radius=2), offset=0.2)` 非空; 任意"首尾边共线"的闭合
路径不再空输出(可构造: 65 边形首点前后都沿切线方向各插一点)。

---

## 缺陷 3: PR/CR 高阶及部分小 n 低阶配置编织错乱

**症状**: 这些配置下每个交点处的上下穿插关系混乱: 双带同绘(重叠)、丝带缺失
(背景破洞)、孔洞被盖死、旋转对称破坏, 还偶发重复顶点 ribbon。

**扫描规模**: n=5..16 × 5 花型 × 可行阶(≤6), 共约 200 组, **84 组损坏**。
判据 = 存在线段左右偏移线交点数不相等(现象级根因, 见下)。

| 花型 | 损坏规律 |
| --- | --- |
| PR | **所有 n≥5 的 L≥3** 全部损坏(每段左右交点数差 1 且为奇数) |
| CR | **所有 n≥7 的 L≥3** 全部损坏; 另有 CR n=5 L2-4、n=6 L4 |
| CA | CA n=5 L2-4、n=6 L2-3、n=7 L5、n=9 L5、n=15 L5、n=16 L4-5 |
| PO | PO n=5 L2-3、n=6 L2 |
| PA | 仅 PA n=5 L4-5、n=7 L5(超出/贴近可行上限的极端阶) |

**典型数据**(offset = 1.5% × r_max):

| 配置 | 左右交点数不等的线段 | 中心线采样双带重叠 | 背景破洞 | 被完全盖住的孔洞 |
| --- | --- | --- | --- | --- |
| CR n=10 L3 | 40/40 | 6401/31222 (20%) | 2797 (9%) | 4 个 |
| CR n=8 L4 | 25/25 | 519/31132 | 7689 (25%) | — |
| PR n=10 L3 | 40/40 | 10308/35282 (29%) | 2386 (7%) | — |
| PO n=5 L2 | 10/20 | — | — | holes=51, ribbons=92(数量失控) |
| CA n=5 L3 | 38/44 | — | — | 93 个多重交点警告 |

**复现**:

```python
import numpy as np
from manim_lace import StarRosette
from manim_lace.interlacing import Interlacing

rose = StarRosette(10, 3, "CR")
paths = [np.asarray(sp, float) for m in rose.family_members_with_points() for sp in m.get_subpaths()]
r_max = max(np.linalg.norm(sp[:, :2], axis=1).max() for sp in paths)
inter = Interlacing(paths, 0.015 * r_max)
# 每条线段 j: len(inter.d_seg_intersects[(0,1,j)]) != len(inter.d_seg_intersects[(0,2,j)])
# 且两侧总数为奇数(如 L=7/R=8, L=3/R=2 ...)
```

**根因**: `_set_ribbons` 假设"左右偏移线交点数一致", 用
`num_pairs = min(len(tgt_ids_l), len(tgt_ids_r))` 后**按索引 k 把左侧第 k 个交点与
右侧第 k 个交点配对**成 U 型(`manim_lace/interlacing.py:747`、`:762-784`)。
当左右交点数不等(这些配置下每段都差 1、总数为奇)时, 左右第 k 个交点往往属于
**不同的交点事件**, U 型连接错位 → 丝带跨过其它交点(双带同绘)或整段缺失(背景破洞)。
这正是 `tests/test_interlacing.py:159`
`test_lattice_with_asymmetric_offset_intersections` 记录的回归情形, 但该用例只有
个别线段触发, 而这些配置下**每段都触发**。

注意: 错乱**不只发生在多重交点附近** —— n=10 CR L3 的 6401 个重叠采样无一位于
中心线三重交点的 3×offset 范围内; 中心线上根本没有三重交点(多重警告全部来自偏移线)。
所以不能归咎于 README 已文档化的多重交点退化, 是配对逻辑本身的问题。

**修复方向**:

- 配对改为按**几何位置**对齐: 把左右交点按沿路径的弧长/参数排序后, 按交点事件
  (左右成对)匹配, 而不是按排序后的索引;
- 或者先在几何层消除奇数交点(检查偏移线切触点/相切情形), 保证每条线段左右交点
  成对且总数偶数;
- 修复后 `_set_ribbons` 里 `min(...)` 的兜底分支应仅在真正的边界情形出现,
- 可加告警: 奇数交点数目前是静默的。

**验收标准**: 对扫描表中全部 84 组, 检查 C/D/E/F/G 全部通过(至少 CR/PR 的 L≥3
全线通过); `len(d_seg_intersects[(i,1,j)]) == len(...[(i,2,j)])` 或配对按几何对齐。

---

## 附: 修复顺序建议

1. **缺陷 2**(空白)最独立、最伤(文档示例直接失效), 先修;
2. **缺陷 1**(实心团块)影响所有简单闭合图形, 次之;
3. **缺陷 3**(PR/CR 高阶)波及面最大但配方最复杂, 建议最后动, 动之前先把
   `tests/` 里的编织判定固化成回归用例(C/D/E/F/G), 防止修复引入新的错乱。
