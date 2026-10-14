# manim-lace 进度

> **唯一进度入口**: 记状态、已完成(带证据)、正在做、待做, 以及"**已经试过并被否决的做法**"。
> 本文件只写**结论 + 证据指针**; 逐条实测数据与推导过程在各条目的证据文件里, 不要重复堆表格。
> 相关文档: `DEFECTS.md`(缺陷台账)、`CHANGELOG.md`(按版本)、`AGENTS.md`(工程约定)、`README.md`(用法)。

**更新于 2026-10-14** · 版本 `0.3.0` · `uv run pytest -q` → **426 passed** · `ruff check .` / `ruff format --check .` 全绿

---

## 0. 状态快照

| 项 | 值 |
| --- | --- |
| 分支 / checkpoint | `master`;可回滚点 commit `7ede551`(tag `pre-step3`,v0.3.0 重构 + 缺陷 1/2 修复) |
| 未提交 | 14 个文件改动(`+1782/−110`)+ `PROGRESS.md` / `tools/`(未跟踪)—— 见 §2 第 1 条 |
| 未入库 | `media/`(1001 文件 / 84.7 MB,含全部探针脚本、渲染图、验收页);基线快照 `media/_review/head_tree/` |

```bash
uv run pytest -q                                  # 426 passed
uv run ruff check . && uv run ruff format --check .   # 全绿
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

1. **收尾**: 删除 `media/_review` 里已被否决的归因类探针(结论已留在 §4), 再把改动分批提交
   (① 缺陷 1/2/3 与测试台 ② 丝带配色 API ③ 输入检查/降级 ④ 2026-10-14 复核: 缺陷 5~8、曲线保真、
   校验口径、玫瑰线降级;含 `PROGRESS.md` 与 `tools/`)。每批都过 `pytest` + A/B。
   说明: ①②③④ 的改动在 `interlacing.py` / `test_lace.py` / `weave_checks.py` 等文件里**互相缠绕**,
   无法按文件干净切分(逐 hunk 切会产出跑不过测试的中间提交)。

---

## 3. 未完成

### P0(决定"降级机制能否退役")

- **0. 平铺(与 CR/PR 同源)的瓶颈 = "缺镜像事件"(类型 B)**, 不是相切本身: 相切档(`PA n=6 L2 @2.00R`)
  出现"两侧**事件总数**都不等"的路径, 而稳健档(`@1.80R`)全是类型 A(完美匹配)。修法与 P0-1 的接头
  拓扑是同一件事。判定要用**二分图最大匹配**(`tiling_match.py`)。
- **1. 接头拓扑**: `generate_offset_lines` 的 miter + `MITER_LIMIT = 5.0` 强行封角, 接头附近产生额外
  交点;换成真正的偏移拓扑后 `CR n=10 L3` / `PR n=10 L3` / `CR n=8 L4` / `PO n=5 L2` 的"缺失镜像事件"
  才会真实存在。⚠️ 会改变**所有**配置的几何 → 需先定新 A/B 基线策略。
- **2. 残差收敛(按新口径)**: `CA n=9 L5` D=3+E=1、`CA n=16 L5` D=2+E=1、`CA n=16 L4` E=1(≈0.05%
  采样点)、`CA n=15 L5` E=1。量级极小, 优先级低。
- **3. 浅角/近平行交叉没有自动检查**: θ ≲ 42° 的交叉被 C/D 跳过(`stats["skipped"]`), 需要尺度无关的
  判据(例如直接比较"两侧可见丝带片段是不是同一片")。
- **4. `merge_paths` 会改写开放路径的起点/方向**(`longest_chain` 从哪个端点起步取决于字典序):
  几何不变但左右偏移线互换, 影响 `by_path` 分组与 D 的遍历方向。

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
| **入库工具** | `tools/ab_render.py`(A/B 底线) |
| 验收 / 门禁 | `acceptance_render.py`(单配置面板 + 指标 + 缺陷标记 + `index.html`)、`campaign_rosette.py`、`campaign_tiling.py`、`campaign_kaplan.py`、`campaign_simple.py`(`--category`)、`screen_rosettes.py`、`flag_probe.py`、`fill_rule_probe.py` |
| 判定 / 归因 | `tiling_match.py`、`tangency_probe.py`、`two_circles_probe.py`、`crossing_count.py`、`after_metrics.py`、`closed_probe.py`、`ab_scene_probe.py`、`lace_review.py`、`plain_roses.py`、`tiling_feasibility.py`、`check_validate.py`、`label_debug.py`、`grid4_probe.py`、`step3_targets.py`、`cd_calib.py`、`weave_checks_head.py` |
| **2026-10-14 复核** | `audit_bench` / `audit_stages`(耗时与阶段分解)、`audit_size`(规模与占比)、`audit_c_angle` / `audit_crossing_probe`(浅角假阳性)、`audit_g_exact` / `audit_g_cover` / `audit_g_e` / `audit_g_raster` / `audit_g_ribbons`(G 的分解差异与光栅口径)、`audit_clear_paths_fix` / `audit_dense_*` / `audit_merge_paths` / `audit_open_arc` / `audit_arc_events`(清洗、合并与角点事件诊断)、`audit_recheck` / `audit_curves_weave`(口径重扫与曲线织法)、`audit_two_rings*` / `audit_rings_*` / `audit_curve_scene*` / `audit_dense_scene` / `audit_zoom_scene`(渲染证据)、`check_rosette_free`(解耦检查) |
| **已删除**(结论留 §4) | 归因类: `attribute_missing` / `reason_probe` / `miss_probe` / `where_missing` / `shift_probe` / `seam_count`;匹配类: `match_fail` / `match_debug` / `pair_shape` / `reject_reason`;事件三分类: `step4_*`;判别力: `step3_scoping` / `policy_compare` / `controlled`;对比拼图: `compare` / `step2_effect` / `step31_effect`;杂项: `diagnose` / `probe_input` / `overlap_detail` / `rail_signals` / `per_rail` / `corner_aware` / `render_lace_scenes` |

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
