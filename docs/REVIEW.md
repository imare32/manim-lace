# 编织效果人工审查（Human review）

`media/gallery/index.html` 回答的是「现在做出来了什么」：把项目引以为傲的图案按各自
发布时的配色摊开。这一页回答另一个问题：**测试与基准用的那些图形，编织结果对不对。**

答案是两层，缺一不可：

1. **程序判定**（`examples/review_checks.py`）—— 每个案例、每个渲染通道都给出一组可证伪的
   读数与不变量：按类型分的交叉数、自交数、交替缺陷、上下关系来源、精化数、最差 `sinθ`、
   面积核算、环的有效性、`benchmarks/weave_audit.py` 的三类缺陷签名、以及「解两次是否逐位
   一致」。失败的检查默认展开，通过的收在折叠里。
2. **人眼审核** —— 通过 / 存疑 / 有问题，加一组缺陷标签与自由备注，存在浏览器里，可导出成
   JSON。

**为什么要两层。** 检查只能抓住它被写出来要抓的东西。一个「丝带中间多出一条线」的缺陷，
在面积、环有效性和片段不变量上全都是绿的；而「程序全通过、人眼有问题」的那些格子，正是
检查还缺的那一类断言。所以页面把失败的检查、静默通过的检查和人审备注并排放在一起，
工具栏里也直接给了「只看『程序通过但人审有问题』」这个筛选。

## 运行

```bash
python examples/build_review.py                    # 渲染全部案例并生成页面
python examples/build_review.py --probe            # 只测量不渲染，打印逐案例读数表
python examples/build_review.py -q h               # 高分辨率（默认 m = 720p）
python examples/build_review.py --category rosette # 只做一类
python examples/build_review.py --cases deg-bow,spec-simple
python examples/build_review.py --no-render        # 复用已有媒体，只重算判定与页面
python examples/build_review.py --no-audit         # 跳过 weave_audit 签名（probe 更快）
python examples/build_review.py --no-determinism   # 跳过「解两次」检查（probe 最快）
python examples/build_review.py --verdicts docs/review-verdicts.json   # 载入上一轮人审
```

产物都在 `media/review/`（`media/` 不入库），打开 `media/review/index.html` 即可。

## 页面上的六类案例

案例目录是 `examples/review_catalog.py`，它同时是页面、探针和测试的唯一来源，
所以一个案例不会在两处被描述两次。共 59 个案例、177 个待渲染通道
（另有 4 个通道按实测开销声明为「本轮未纳入」）。

| 分类 | 数量 | 内容 | 审的是 |
|---|---|---|---|
| `spec` | 4 | SPEC §10.2 要求覆盖的四类输入 | 最基本的情形对不对；这四类也是 `make bench` 报时的那四类 |
| `index` | 9 | `tests/test_index.py` 的九个场景（按路径加载该测试模块，不重抄） | 剪枝有没有悄悄改变结果 |
| `degenerate` | 17 | 每个图形瞄准一种事件分类：近切、浅角、端点接触、共线重叠、多线共点、零长路径、整条被切、薄楔塌陷、三种连接策略、交替与自由模式对照 | 不该硬猜的地方有没有硬猜 |
| `adapter` | 9 | 真实 Manim 对象：`Circle`/`Line`/`Arc`/`Polygon`/`ParametricFunction`/手工折线/嵌套 `VGroup`，含两个**必须失败**的输入与一个自我重叠的 `Arc(angle=3π)` | 从 Manim 拿到的几何对不对，错误是否明确 |
| `gallery` | 9 | 已发布画廊图案；源几何直接从 `scene_gallery` 的 builder 取回（`Lace.target_mobject`） | 统一风格下已发布图案是否仍然正确 |
| `implicit` | 6 | 独立等值线提取器（`sample_implicit`）：圆、环、双曲线、退化自触的十字与八字、极点造成的假等值线 | 从方程直接取到的曲线对不对；两件做不到的事（交点丢失、假等值线）能不能接受 |
| `rosette` | 5 | 玫瑰线编织，含两个文档承认的退化配置 | 密集自交（70 交叉 / 20 处自交）下还站得住吗 |

每个案例渲染五个面板（`原始输入` → `stroke` → `ribbon(boolean)` → `ribbon(arrangement)` → `编织结果（交叉编号）`）。
**第一个面板是原始输入**：引擎拿到的中心线本身，按同一条股线的颜色画细线，并把检出的交叉点与交叉编号标在上面——
没有它就没法把"引擎看错了几何"和"引擎织错了"分开。交叉数不超过上限时才加最后那张标注图
（`annotate=False` 的案例没有它，见 `Case.annotate`）。

三个编织通道用同一套配色与线宽：股线按路径取 `natsu` 配色（ribbon 的切口只有变成换色才看得见），
描边统一黑色细线；原始输入面板沿用同一份配色方案（从 `Lace` 的 `style_plan` 按片段反查回路径），
所以同一条股线在四个面板里颜色一致。线宽按输出像素换算（`px_to_stroke_width`，2.4 px），
不随案例缩放的，因此任何 `-q` 下都读得一样。

## 判定口径

这些口径不是文档抄来的，是量出来的（见 `tests/test_review_catalog.py` 与
`python examples/build_review.py --probe`）：

- **面积契约**：`painted_area == union_area`（引擎构建出的丝带并集）。`band_area` 是
  **各丝带面积之和**，所以它比可见面积大出「被隐藏的交叉重叠」，拿它当参考会在**每一个**
  普通交叉上报失败——这一点是先用数据验过才写成检查的。引擎报 `REGION-SECTION-SEAM` 时，
  参考面积换成整条丝带并集（`render/regions.py` 自己就是这么切的），因为那时分段并集
  并不等于丝带（细丝带那一档两者相差 27 个世界单位）。
- **并集不可能大于各部件之和**：`region.painted_le_sum` 只用两个引擎已经算好的数字做算术，
  不需要几何。这正是抓「静默记账错误」最便宜也最硬的一条：细丝带玫瑰线上 boolean 后端报
  `painted_area` 37.702956，而它自己 161 个区域之和是 10.183419。
- **独立重算**：用 Shapely 把渲染器发出的环重新并一遍，必须复现引擎报告的
  `painted_area`。用的是引擎自己的 `_covered_area`（逐个 union + 校验 + 试两种顺序），
  因为一次性 `unary_union` 会悄悄丢掉与邻居只共享一条边的部件——那正是它存在的原因。
  这条重算在区域数超过 64 时**跳过**（它是 O(n²)），由上面那条算术判据兜底。
- **环的方向**：外环逆时针、孔洞顺时针；孔洞按 `exterior` / `source_contour` / `occlusion`
  分类计数。
- **`no_overlap` 只对 arrangement 是硬判据**：boolean 后端按分段输出，允许相邻分段重叠并会
  自报 `REGION-OVERLAPPING-SECTIONS`，所以那里只记为读数。
- **编织缺陷签名**复用 `benchmarks/weave_audit.py`，不重写一遍：
  `defect_edges`（描边两侧都被覆盖、且不在任何透镜边界上 = 多画的线，阈值 0）、
  `notch_gaps`（缺口边有未被描到的区间 = 少画的线，阈值 0）、
  `dangling_ends`（描边端头悬在丝带内部，阈值 0）。`dangling_ends` 这一轮改准了，
  因为旧口径把**人眼看得见**的一类端头放过去了：两个区域共享同一条边时都会描它一遍，
  于是在那个顶点上"另有一条描边"——旧规则就此判为"接上了"，可两条描边方向相同，
  那**正是一条线断在这里**。现在的口径要求另一条描边以**自己的方向**离开该顶点
  （线的延续、拐角或 T 形接合），被后画的填充盖住的端头也不报（读者看不到它），
  并按**可见端头**计数而不是按描边条数（同一条线被两个区域各描一遍只算一处）。
  实测：`spec-self-intersecting` 两个通道各有 24 处（旧口径 0 处），`n=7` CA 卡片
  两个面板都是 0（旧口径 boolean 4 处），`n=5` CA 的 boolean 面从 28 降到 17。
- **通道一致性**：三通道必须报告相同的交叉数、事件类型分布与上下关系来源（FR-040）。
  不一致会直接显示为失败芯片，并让该案例的「目录预期」判为不符。
- **确定性**：同一案例解两次，交叉指纹与几何指纹必须逐位相同。这是**每个案例验一次**
  （在它的第一个通道上），因为它是案例的属性而不是某个后端的属性，而且它会把最重输入的开销
  翻倍；页面上的该条检查因此只出现在第一个通道的面板里。
- **求解耗时**是一条读数（不是判据）：页面同时也是发现「某个后端在某类输入上意外昂贵」的地方
  （例：1501 点的自交曲线，boolean 后端约 16.6s，arrangement 约 6.0s，stroke 0.13s）。

## 人眼这一层怎么用

1. 打开工具栏的 **开始逐一审核**：进入聚焦模式，一张图占满屏，右侧是同一套程序判定与
   人审控件。左上角标题栏右侧有 **退出逐张审核** 按钮（`F` 或 `Esc` 同样可以退出）。
2. 键盘：`←` `→` 切换案例，`1` 通过、`2` 存疑、`3` 有问题，`F` 或 `Esc` 退出。
   **切换案例会保持你当前看的通道**（通道名显示在标题旁），所以可以选定一个通道一路扫下去，
   不用每张重新点。
3. **闪烁对照 A/B**：在两个通道之间以 0.5 秒交替（也就是把两张图叠在同一个位置来回闪），
   这是看「两个后端有没有画出同一个编织」最快的方式——静止并排看会漏掉肉眼难以察觉的
   上下关系差异。
4. 点任意通道的缩略图进入聚焦（并从此固定在那个通道）；聚焦里点大图会用浏览器原生方式
   打开 PNG（原生缩放看细节）。
5. 缺陷标签可以多选（缺口 / 断头悬空描边 / 画进丝带内部的线 / 上下关系反了 / 少画了一块 /
   多画了一块 / 接缝端面可见 / 角点或曲线畸形 / 面积不守恒 / 颜色不可辨 / 与另一通道不一致 /
   形状本身不对），备注写清「在哪一处、和预期差在哪」。
6. 工具栏筛选器可以直接切到 **只看未审核**（扫尾）、**只看程序检查失败**（先看硬的）、
   **只看「程序通过但人审有问题」**（检查漏了的东西）。进度条同时给出通过/存疑/有问题
   的计数与上述不一致数。

## 人审结论怎么留下来

**默认就是浏览器持久化，不需要任何导入导出**：每点一次判定、每打一个字都立刻写进
`localStorage`（键 `manim-lace-review-v1`），刷新、关掉重开、重建页面都不会丢。工具栏右侧
一直显示当前状态：

- 绿色「本浏览器已自动保存 <时间>（N 条结论）：刷新或重开页面都会保留，不用再导入」
- 黄色「本浏览器禁用了本地存储：结论只在这个标签页有效，刷新会丢——请用「复制结论」留档」
  （隐私窗口、或把本地文件当第三方上下文时会出现；这时页面**明说**，而不是让你以为存住了）

要把一轮结论带进版本控制，用**剪贴板**，不用文件：

```bash
# 1. 在页面上点「复制结论（到剪贴板）」
# 2. 粘贴进仓库里的一个文件（例如 docs/review-verdicts.json）并提交
# 3. 下一轮生成时把它烧进页面；打开就是上一轮的基线，你在本机改过的结论仍然盖在它上面
python examples/build_review.py --verdicts docs/review-verdicts.json
```

反向也走剪贴板：点 **粘贴导入** 展开面板，直接 `Ctrl+V` 粘进 JSON，或点 **读剪贴板** 由页面
自己去读。面板会即时告诉你「解析到 N 条结论（导出时间 …），其中 M 条会覆盖本机已有的结论」，
确认后再点 **合并到本机结论**；合并规则是**按案例覆盖**（粘贴进来的同 key 覆盖本机旧结论，
其余保留），所以一轮复查看得出只改了哪几条。

浏览器不允许读剪贴板时（部分浏览器对 `file://` 会拒绝），按钮会明确说「读取被拒绝，请手动
Ctrl+V」，面板里那个输入框永远可用；复制那侧也一样，异步剪贴板 API 不可用时会退回到
`execCommand` 路径，再不行就把文本选中让你自己按 `Ctrl+C`——**不会静默失败**。

烧进页面的基线（`--verdicts`）与本机 `localStorage` 的关系是：**基线作底、本机覆盖**
（按案例逐条）。所以重建页面带来新一轮基线时不会被本机旧数据挡住，而本机改过的结论也不会
被重建清掉。

## 已知会带诊断的案例

页面不会把这些当缺陷：它们是**文档声明过的诚实降级**，在案例上写着 `look_for`，在程序判定
里显示为 `warn` 芯片而不是 `fail`：

| 案例 | 预期诊断 | 说明 |
|---|---|---|
| `deg-collinear-overlap` | `GEOM-COLLINEAR-OVERLAP` | 共线重叠是区间，不存在唯一二元上下关系 |
| `deg-t-junction` | `GEOM-ENDPOINT_TOUCH` | 端点接触默认不进入交替求解 |
| `deg-shallow-angle` | `GEOM-NEAR_TANGENT` | 浅角切口必须被钳制并上报 |
| `deg-multiway-fan`、`index-concurrent-fan` | `GEOM-MULTIWAY-CROSSING` | 多线共点不发明唯一顺序 |
| `deg-degenerate-path` | `GEOM-DEGENERATE-PATH` | 零长路径被点名而不是静默丢弃 |
| `deg-figure-eight` | `REGION-COINCIDENT-CROSSINGS`、`REGION-DRAW-ORDER-CYCLE` | 闭合自交路径上 boolean 后端的已知降级（arrangement 同输入 0 诊断） |
| `deg-thin-wedge` | `REGION-AREA-MISMATCH` | 薄楔偏移塌陷，面积守恒降级 |
| `index-mixed-scale` | `REGION-AREA-MISMATCH` / `REGION-CONFLICTING-OVERLAP` | 相差三个数量级的几何 |
| `index-repeated-points` | `GEOM-COLLINEAR-OVERLAP`、`GEOM-NEAR_TANGENT` | 输入本身就共线且近切 |
| `index-random-walks-6/12` | `REGION-AREA-MISMATCH`、`REGION-CONFLICTING-OVERLAP`、`REGION-LENS-APPROXIMATION`、`REGION-OFF-CROSSING-OVERLAP` | 随机游走网络里大量近切 |
| `gal-spiral` | `TOPOLOGY-ALTERNATION-RELAXED` | 严格交替在螺线上无法全程成立，只放宽必需处 |
| `gal-infinity` | `REGION-COINCIDENT-CROSSINGS` | 自交点与直线交点重合，扣除互相抵消 |
| `ros-n5-ca-l2-o12` | `REGION-COINCIDENT-CROSSINGS` / `REGION-LENS-APPROXIMATION` | 共点交叉退化配置，**最需要人眼**的一张 |
| `spec-self-intersecting` | `REGION-COINCIDENT-CROSSINGS`、`REGION-DRAW-ORDER-CYCLE` | 这条曲线上有三个弧长参数（0.00 / 6.73 / 27.22）落在同一坐标，引擎在那里记录两个交叉事件，两处透镜互相重叠；boolean 后端按文档降级，arrangement 同输入 0 诊断。两个后端都在 24 处把缺口手臂断在丝带内部（`audit.dangling_ends`，人眼点名的四处「V」与两处「戳进丝带」都在其中），这是共点交叉处缺口手臂的本性，不是某一个后端的错 |
| `imp-saddle-cross` | `GEOM-IMPLICIT-AMBIGUOUS-SADDLE` | 四角交替的格子由双线性中心值裁决；中心值恰好等于 level 时配对会随网格翻转（实测 24/96/192 一种、48/384 另一种） |
| `imp-pole` | `GEOM-IMPLICIT-ERROR-TARGET-MISSED` | 极点不是零点：返回的「圆」上 `|F|≈400`，任何分辨率都达不到目标误差，诊断点名超标分支 |

当引擎自己报了 `REGION-AREA-MISMATCH` 时，`region.area_conserved` 会显示为**警告**而不是失败：
那条检查要抓的是**静默**的不一致，而不是复述引擎已经说过的降级。

## 本轮审查查出来的问题（实测）

这张页面存在的意义就是这些：程序判定与人眼各自补上对方的盲区。下面几件事是这一轮真的量出来的，
不是设想出来的。

| 问题 | 实测 | 页面上怎么显示 |
|---|---|---|
| **boolean 区域后端在随机游走网络上病态** | `index-random-walks-6`（6 条路径 / 48 交叉）：boolean **>5 分钟且峰值内存 1.7GB**；同一输入 arrangement **2.1s**、stroke **0.2s**。`index-random-walks-12`（12 条 / 151 交叉）：boolean **>4 分钟未跑完**，arrangement **11.7s**。而 `spec-network`（27 条 / 196 交叉）boolean 只要 1.4s——所以不是交叉数的问题，是"许多短路径互相近切"这类输入 | 两张卡把 boolean 通道显式列为「本轮未纳入」，原因里带着上面的数字（`Case.omitted`） |
| **arrangement 后端在密集随机游走上留下悬空描边** | `index-random-walks-6`（48 交叉）：`audit.dangling_ends` **20 处**、`audit.notch_gaps` **3 段 / 0.0507**；`index-random-walks-12`（151 交叉）：悬空端头 **18 处**。两个案例同通道另有 `REGION-LENS-APPROXIMATION` 等 5 个诊断 | 该案显示为**失败**芯片，`look_for` 直接写明"需要人眼定位" |
| **Manim 参数曲线路径上也有一个悬空描边端头** | `adp-parametric`（`ParametricFunction` 的 Lissajous 3:2）boolean 通道：`audit.dangling_ends` **1 处** | 同上；这条说明该签名不只出现在手工构造的退化输入上 |
| **boolean 区域后端在细丝带玫瑰线上报出一个不可能的可见面积（静默）** | `ros-n10-pa-l12-o05`（n=10 PA 阶 1+2，offset 0.05）boolean 通道：`painted_area` **37.702956**，而同一份结果里 161 个区域的面积之和是 **10.183419**、分段并集 10.594701、整条丝带并集 10.183419；arrangement 后端在**同一输入**上给出 10.183419。比自己的区域之和还大 3.7 倍在数学上不可能（并集不可能大于各部件之和），而引擎的自检只判 `painted < 参考面积`，因此**没有** `REGION-AREA-MISMATCH`——一个不会自我暴露的错误数字。**这一档的画面本身看不出问题**（实机渲染的丝带干净、轮廓连续），错的是面积那本账 | `region.area_conserved` 与 `region.painted_le_sum` 都显示为**失败**，并写出两个数各自是多少；案例说明里写明这是本轮查出的缺陷、且画面看不出差异 |
| **`Arc(angle=3π)` 这类"超过一圈"的圆弧会让两个区域后端跑不完** | `adp-arc-overlapping`：`Arc(angle=3π)` + 一条直线。stroke 通道 **1.1s** 出 **175** 个事件（大量共线重叠/端点接触噪声）并把整条圆弧切光（`RENDER-PATH-FULLY-CUT`）；boolean 与 arrangement **>60 秒未完成、峰值内存 2.7GB**。原因不是交叉数，而是**圆弧自我重叠**（后半个圈原路重走前半个圈） | 该案只渲染 stroke 通道，两个 ribbon 通道作为「本轮未纳入」列出并带上面的数字 |
| **近零面积碎片环的朝向是数值噪声** | 各后端都会吐出面积 ~1e-19 的 sliver 环，其外环的 `shoelace` 符号随机（引擎自己的 `RegionRing.counter_clockwise` 同理） | 朝向检查跳过面积 ≤1e-12 的环并计数，不误报 |
| **布尔运算留下重复顶点** | 部分环带零长边（连续重复点），Shapely 因此判其无效；但实测 `region.area` 与环自身面积**逐位一致**，画面不受影响 | `region.rings_clean` 作为**读数**（不是失败）列出数量与前几个环名 |
| **审计探针的安装时机是个坑** | `benchmarks/weave_audit.py` 记录的是 `mark_flush_edges` **求解时**收到的数据；若在求解之后才 import，记录为空，于是所有自交边都被误报成"不在任何透镜边界上"（第一版判定就是这样误报了 5 个案例） | `review_checks.ensure_audit_probe()` 在首次构建前安装探针，`audit_signatures` 再校验记录的区域就是本次求解的对象，否则报 `skip` 而不是编造失败 |
| **人眼在 Lissajous 5:4 上点出的两类缺陷，旧检查一类也没报** | 这一轮的人审记录：boolean「四个交叉口处的 V 字形差一点点没有闭合」、arrangement「两处戳进了丝带当中」。实测 `spec-self-intersecting`：boolean `audit.notch_gaps` **3 段 / 0.0386**（旧检查已报）；两个通道各有 **24 处**可见描边端头断在丝带内部——旧 `dangling_ends` 报 **0 处**，因为同一条边被两个区域各描一遍，规则把"顶点上还有第二条描边"当成了接上（两条描边方向相同，那正是断头） | 判据改准之后，该案三个通道里有两个通道显示 `audit.dangling_ends` **失败**（boolean 47 条描边 / 24 处可见，arrangement 40 / 24），人眼点名的两处 arrangement 断头就在坐标 `(0.6472, 0.0530)` 及其镜像上；boolean 的四个 V 缺口两端也各是一个断头 |
| **`notch_gaps` 会点名一段不该描的切口** | 顺着上一条把 `notch_gaps` 报的 3 段描出来试过：它点名的是**穿过透镜的那道截面切口**（`#151.region0` 上 `(0.45538,0.91777)→(0.45642,0.93399)`，竖向 0.0163），描上去在丝带中间多出一条 **44 px** 的竖刺，而人眼看到缺的那一段（`(0.42519,0.91923)→(0.45538,0.91777)`，横向 0.0302）**没有被描到**——它不在记录的透镜足迹上（`weave_d` 0.0029–0.0268，阈值 1e-6），于是被归为「自己的丝带边被盖住」而隐藏 | 这条留在文档里，免得下一个人顺着 `notch_gaps` 往错的方向修；引擎未改（见下） |
| **把「自己的丝带边」整类描上会多出 245 条丝带内部的线** | 同一实验的第二种做法：让 `is_hidden` 对全部"本区域丝带边"都返回"要描"。结果四个角缺口的线**确实接上了**（全画面只变了 634 px），但 `audit.defect_edges` 从 **0 变成 245**（boolean）/**0 变成 6**（arrangement）——接上的是 4 处，多出来的是 241 处横线 | 因此本轮**不动几何**：把输入本身（共点交叉处手臂该断在哪）当成待定问题，见「还没解决的」 |

## 还没解决的：缺口手臂该断在哪

`spec-self-intersecting` 上两个后端都把缺口手臂断在同一批 24 个位置，所以合并来看它是一件
**输入本身**的事，而不是某个后端画错。三个数字说明它的形状：

- 手臂断点都在「共点交叉」的那一圈角上：`(0.6472, 0.0530)`、`(0.7673, -0.0527)`、
  `(0.7610, -0.5287)`、`(-0.9857, 0.7583)` 及其镜像，也就是弧长 0.00 / 6.73 / 27.22 三次经过
  同一坐标时两处透镜的角点。
- boolean 那四个「V 差一点点没闭合」的缺口长度是 **0.0302**，缺口两端一边是**背景孔洞的
  轮廓**（白色空缺的边），一边是**记录的透镜边界**（缺口线）；两者几乎共线，但中间那一段
  两侧可见材料相同（同一区域 `#150` 覆盖两侧），所以引擎判定"这里没有可见边界"。
- 把断点接起来有两条路，本轮都量过代价：只描 `notch_gaps` 点名的切口 → 多一条 44 px 竖刺；
  描全部"自己的丝带边" → 四个角接上了，但 `defect_edges` 多出 245 条。两条都不成立。

所以真正要做的是一件**设计**上的事，而不是调一个阈值：

1. 让 arrangement 的面也沿**透镜足迹**被切开（现在的面在共点交叉处会横跨足迹，于是足迹的
   一段落在某个面的内部、谁的环上都没有它，也就没人描）；
2. 或者把"欠下的描边"作为一层交给渲染器：`weave` 里那些**没有落在任何区域边上**的足迹段，
   由引擎连同可见性判断一起发给渲染器，画在所有填充之上。

两条路都要动 `render/regions.py` / `render/arrangement.py` / `manim_api.py` 的接口，并且要
在 `benchmarks/weave_audit.py` 的 22 个玫瑰线配置上验证没有回退——这正是本轮留在页面上的
问题，而不是顺手改掉的地方。

## 新增一个案例

1. 在 `examples/review_catalog.py` 里加一个 `Case`：几何、`offset`、`weave_mode`、
   通道、`prose` 与 `look_for`，以及**预期**（`expect_crossings` / `expect_diagnostics` /
   `expect_error`）。某个通道开销大到跑不动时用 `omitted=(("<通道>", "<实测数字与原因>"),)`，
   页面会把它作为「本轮未纳入」显式列出来（测试要求原因里带数字，避免"太慢"这种不可核对的理由）。
2. `python examples/build_review.py --probe --cases <key>` 看实测，把预期校准到事实——
   预期是给人看的承诺，所以必须与实测一致；对不上时页面会明确报「目录预期与实测不符」，
   `tests/test_review_catalog.py` 也会失败。
3. `pytest tests/test_review_catalog.py` 与 `python examples/build_review.py --cases <key>`。

## 与状态画廊的关系

| | `media/gallery/index.html` | `media/review/index.html` |
|---|---|---|
| 输入 | 项目展示用的图案 | 测试、基准与退化图形 |
| 风格 | 每张卡片自己的配色/线宽（发布形态） | 全部统一，三通道并排可比 |
| 数字 | 交叉/区域/面积/诊断/轨迹事件 | 上述之外再加不变量、缺陷签名、通道一致性、确定性 |
| 用途 | 看做到哪了 | 逐格签署：程序怎么说，人眼怎么看 |