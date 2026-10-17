# 缺陷排查手册：怎么量、怎么被自己的量法骗、哪些路已经走死了

> 用途：这份文档记的是**方法**与**负结果**，不是功能说明。每次有人花半天定位一个缺陷，
> 复盘的产出应该落在这里，而不是散在提交信息里。
> 配套：现象与判定口径见 `docs/REVIEW.md`；几何/描边的专题见
> `docs/SELF_CROSSING_OUTLINE_TICKS.md` 与 `docs/ROSETTE_RIBBON_OUTLINE_TICKS.md`。

---

## 1. 先量，再改：三条被实测否掉的修法

本轮的目标是 `spec-self-intersecting` 上"缺口手臂断在丝带内部"（`audit.dangling_ends`
24 处）。动手之前先后否掉了三条看起来都很有道理的修法，**每一条都先做了实验**：

| 修法 | 结果 | 结论 |
|---|---|---|
| 让 arrangement 的面沿透镜足迹切开（`_cells` 的 noded 输入加上透镜环） | 剖分确实变了（`raw_face_count` 230 → 258），但区域与 24 处断头**一个没变** | 那处足迹两侧归**同一个所有者**，多切出来的面被 `_node_geometry` 又并了回去。病灶在**归属**，不在剖分。改动已撤回 |
| 按方案 1 字面实现：同色即无边界（关掉"缺口必须描"那条规则） | 断头 24 → **0**，但 `notch_gaps` 从 3 段 / 0.0386 涨到 **723 段 / 12.26**（boolean）、**961 段 / 15.45**（arrangement） | 自交两股**同色**，这条规则会把所有缺口一起抹掉，编织糊成一片。缺口规则不是"模型缺陷"，是让编织可读的必要条件 |
| 让透镜从"参与归属的截面带"算出来（而不是窗口臂带求交） | 断头仍 24，`notch_gaps` 反而从 0 涨到 **67 段 / 5.19** | 共点处有**三个**弧长交于一点，参与归属的带不止两条，"某一次交叉的两股交"根本不是归属边界 |

三条路都走死之后，**真凶才露出来**（见 §2）。教训：断头/缺口这类签名，先花十分钟量清楚
"它到底缺什么"，比直接照文档给的候选修法动手便宜得多。

## 2. 闭合路径：弧长 0 与弧长 L 是同一个位置

`spec-self-intersecting`（闭合，长度 27.2169）与 `deg-figure-eight`（闭合，长度 9.429）的
自交点都落在**闭合接缝**上：

```
spec-self-intersecting:  X0000 = (s_a= 0.0000, s_b= 6.7335)
                         X0015 = (s_a= 6.7335, s_b=27.2169)   # 同一个交叉
deg-figure-eight:        X0000 = (s_a= 0.0000, s_b= 4.7145)   # 4.7145 × 2 = 9.429 = 长度
```

接缝那一点对一个报告是弧长 0、对另一个是弧长 L，于是**同一个交叉被报成两个事件**。
`geometry/intersections.py` 的去重按**相同角色**配对（`s_i` 比 `s_i`），而这里两个弧
**互换了角色**，所以漏掉。

**规则**：任何按弧长做的簿记，闭合路径上一律先取模再比较。自交的两个弧可交换，跨路径的
`s_a`/`s_b` 不可交换——去重因此只在 `path_i is path_j` 时接受交换配对。

这个重复事件伪造出的下游现象很能骗人：一个"共点交叉"、一条无法满足的交替约束
（14 处被放宽、28 处逐次同侧）、以及在 boolean 上多出来的 1 段未描缺口。修掉之后
`spec-self-intersecting` 的 32 → 31 个交叉、交替缺陷 0、`REGION-COINCIDENT-CROSSINGS`
消失；`deg-figure-eight` 从"1 个共点交叉 + 绘制顺序成环"变成 1 个交叉、0 诊断。

**注意它没有修掉的那一半**：断头仍是 24 / 26 处。断点处的透镜足迹两侧归**同一个所有者**
（都是 `#15`，材质没变），所以手臂到那里就是到头了——那是另一件事，仍记在
`docs/REVIEW.md` 的「还没解决的：缺口手臂该断在哪」。

## 3. 别被自己的量法骗：重复描边会伪装成"接上了"

第一版测量报告"24 个断头到最近一条描边的距离**全是 0**"，看起来像是纯数值吸附问题。
那是假的：**同一条边会被相邻两个区域各描一遍**，所以"最近的描边"往往是这条线自己的副本。
排除副本（与自己入点的边同一条）之后，读数变成 3.5e-4 ~ 2.3e-2，再排除**同一条折线的
后续段**（折线是分段的，V 到第二段的距离天然是 0.0216）之后，才能得到"这里确实没有描边
接上来"这个结论。

`benchmarks/weave_audit.py::dangling_ends` 的口径已经处理了这件事（要求另一条描边以
**自己的方向**离开顶点，或**穿过**顶点）；自己写测量时必须同样小心。

## 4. 逐对穷举是这类引擎的固定病

同一天修掉的三处性能悬崖，病根是同一个形状：**把一个本该用索引回答的问题写成了逐对穷举**。

| 位置 | 原样 | 改法 |
|---|---|---|
| `_open_occlusion_holes` | 假设"切一刀就少一个孔"，而切弦可能切不到那个孔 → 那半边带着孔进入下一轮，每轮只把 piece 数翻倍（实测一个 piece 切了 **32 万次**仍未终止） | 切弦定位到被瞄孔的中心 + 轮数预算 |
| `mark_flush_edges` 的接缝判定 | 每条区域边对**本路径全部切弦**比对：1965 × 3730 = **733 万次** / 17.2s | 切弦进 `STRtree`，边只问外接框命中的几条（判定本身未改） |
| `mark_flush_edges` 的足迹判定 | 只问"这点是否落在某条已切透镜的足迹上"，却先做了一次 `unary_union`，逼叠加引擎把每两条相交足迹结点化——~13k 条足迹，**一次**调用占 78s 里的 65s | `STRtree` + `dwithin` 谓词，不求并 |

同样的形状在 `_covered_area`（三种顺序 × 逐个 union × 每个部件 `covers` 校验）上也出现过，
那里改成"部件数 ≤ 64 才走精确路径"。**看到"每条 × 每条"就先想索引**，尤其是查询是
"某个点/线段附近有什么"的时候——那本来就是空间索引要回答的问题。

## 5. 工具与流程

- **先画图再看数**。本轮三次判断是看着渲染出来的局部放大图纠正的（填色 + 描边 + 隐藏边 +
  透镜足迹分色画在一张图上）；纯看坐标列表把三处关系看反过两次。
- **用 profile 定位，不要猜**。`cProfile` 的 `tottime` 直接给出 733 万次 `_on_cut` 和
  65s 的 `union_all`，比读代码猜快一个数量级。
- **`--skip-heavy`**（`tests/conftest.py`）把与 ribbon 无关的重案例摘出去：651 项
  217s → 639 passed + 12 skipped / 77s，默认行为不变，另有 `make test-fast`。
- **审计数字要能重跑**。`docs/REVIEW.md` 里出现过的数一旦和代码对不上，就是文档缺陷：
  本轮回查发现 `random-walks` 的 `dangling_ends` 记的 20/18 与实测 53/76 不符
  （用 HEAD 的引擎 + HEAD 的审计独立复测确认不是回归），已按实测改写。

## 6. 环境陷阱：沙箱里的 Python 崩溃不是引擎的错

在受限环境里跑 `.venv` 的 Python 会以 `0xC0000142`（DLL 初始化失败）结束，Windows 还会为
每个这样的进程弹一次错误框——它看起来非常像"引擎触发了原生崩溃"，上一轮就是这样把
`render_region_geometry` 里的一个"GEOS 访问违例"当成真 bug 追了很久。**判断方法**：同一个
命令在非受限环境下能否跑通；`python -c "print(1)"` 都失败时，问题一定不在被测代码。

**同一族的第二种，只跟执行顺序有关**：`examples/build_review.py` 里"先把隐式案例量完、其余放
后面"的顺序不是速度优化，而是绕开这族污染——先建一堆 Manim/Cairo 对象，纯 NumPy 的
marching-squares 提取器随后就会读到坏内存。实测按目录顺序跑（隐式案例在最后）、即使 `--no-render`
（不渲染面板，但仍会为每个案例建 Manim 源），必在最后一个隐式案例 `imp-pole` 崩掉，而且报错对象
每次不同：

```
File "src/manim_lace/geometry/implicit.py", line 316, in _cell_segments
    if (a >= level) == (b >= level):
TypeError: '>=' not supported between instances of 'cell' and 'float'
# 另一次是 '>= not supported between instances of 'dict_itemiterator' and 'float'
```

`cell`、`dict_itemiterator` 就是被污染的值——`_cell_segments` 收到的不再是浮点采样值，所以这不是
提取器的逻辑错（单独量那 6 个隐式案例两次都过）。修法是把那条顺序判据对所有非 `--probe` 运行都
生效（本轮 `build_review.py` 如此改：`if not args.probe:`），页面仍在写盘前按目录顺序重排，所以
变的只是执行顺序。**教训**：这种"报错值明显不属于该类型"的崩溃，先看是不是环境/顺序问题，再去
读被测代码。

## 7. 区域环不是唯一的轮廓载体

区域后端最初把 `RibbonRegion` 的每个外环当成完整的墨水源。这个假设在两个地方失效：

1. **短 flush 绕行**：布尔运算会给出 `stroke → flush detour → stroke`，两条正常边界之间
   只有 `~1e-3` 的直连接桥；只描非 flush 边会留下两个可见断头。
2. **归属合并**：剖分面先归属、后并成区域时，同一个 owner 的两侧会让真实编织缺口落到多边形
   内部。此时缺口既不在外环上，也不在 `flush_edges` 里，区域环无论怎么筛选都画不出来。

修法不是放宽 `mark_flush_edges` 的阈值，而是让结果显式携带 `outline_edges`：它记录“可见但
没有任何区域环承载”的边界，渲染器在全部填充之后补描。短绕行只桥接端点几乎重合的情况；
arrangement 的短透镜缺口只在一端确实是未接续描边、且与缺口共线时补；长切弦不靠这个局部
规则猜测，避免把真正的横向接缝描成丝带内部的线。arrangement 的可见外环/run 也统一在
全部填充之后绘制，后画面不能再把先画 stroke 削掉一半。

这条经验也适用于下一次区域问题：**先问结果模型是否能表达目标几何，再问哪条边应该被隐藏**。

## 8. 理想射线会在端点处漏过下一条描边

hybrid 的桥接规则本来是"从布尔可见断头沿反向笔画方向射一条**理想射线**，取第一条相交的
布尔边界"。在 `spec-self-intersecting` 的四角上它只补住 2 个（蓝角），另外 2 个（红角）
**一条都没找到**。原因不是几何缺失：

```
红角 P = (-0.455375, 0.917773)，断头判定的 outward = [-0.9979, -0.0641]
arrangement 在该处的边界方向与它差 ~0.9°
缺口 P -> Q 长 0.0302 world
```

0.9° 在笔画尺度上完全看不见，但在一条长 `0.0302` 的连线上，横向偏离已达
`0.0302 * sin(0.9°) ≈ 4.7e-4`——刚好越过 `tolerance = 1e-6` 量级，于是理想射线从
目标描边的**端头旁边**擦过去，`intersection` 为空。这不是阈值调大能解决的：射线模型本身
就假定"断头方向 = 边界方向"，而这个假定在真实断头处不成立。

**改法**：把射线换成一条**细带**（`LineString.buffer(max(tolerance, 0.02 * offset))`），
用 `shapely.ops.nearest_points` 取描边上离射线最近的点，再按"沿方向 >0 且 <= 桥长上界、
横向 <= 带宽"筛选。带宽取笔画尺度的 2%（`0.02 * offset`），比 0.9° 造成的偏离大两个数量级，
但远小于一个丝带宽度，因此不会把无关的描边吸进来。

**同一轮量到的另一件事**：布尔 overlay 里有 10 条长度 `0.0003..0.0018` 的 `outline_edges`，
中点都落在**它自己填充的内部**，绘制顺序又在所有填充之上——它们就是"孤立黑点"的来源。
hybrid 现在把"亚像素（`<= 0.05 * offset`）且中点在填充内"的布尔 overlay 直接丢弃；4K 下
与 boolean 的差图里，那 10 个黑点消失只贡献约 127 px 的抗锯齿差，且不再有任何整块的孤立墨点。

**教训**：用"射线/直线求交"表达"从 A 走到对面的 B"时，先量一下 A 处的实际方向与
假定方向差多少——差几分之一度就足以让理想射线在长连线上整体偏出目标宽度之外。

## 9. 被 `flush` 否掉的缝，会被 `outline_edges` 当成"没描的边界"重新描上

人眼第二轮点名的"小突出物"（`spec-self-intersecting` 四角中的两个）不是桥接画出来的，
是**布尔 overlay 自己的两条 stub**：`0.0112` 与 `0.0163`，方向横穿丝带，一端接在角点上、
另一端悬在丝带内部。它们为什么会被描：

```
两条 stub 恰好等于某条区域环边，且那条环边的 flush = True
  0.016254  (-0.45642,0.93399)->(-0.45538,0.91777)  = #55.region0 #4  flush=True
  0.011190  (+0.44682,-0.92948)->(+0.44627,-0.91831)  = #82.region1 #1  flush=True
flush=True 的含义是"这条缝不要描"；它之所以还存在，是
missing_weave_outlines 又在 recorded lens edge 里看见了它
```

根因在 `render/regions.py` 的自交分支：真正拿去做切除的是**去掉截断面的**
`footprint`（`arm_lens ∩ over_visible`，代码注释自己写明 clipped 版"carries section caps
(seams, not notches)"），但记进 `weave_edges` 的却是**带截断面的 `arm_lens` 边界**
（`weave_edges.extend(_boundary_segments(arm_lens))`）。于是 `missing_weave_outlines`
把一条截断面当成"区域环承载不了的可见透镜边"，重新升成 overlay，画在全部填充之上——
正是 `docs/REVIEW.md` §206 早就记下的那根"44 px 竖刺"，只是它当时以 `notch_gaps` 的名义
出现，现在换成了 `outline_edges`。

**为什么"重合即丢弃"一定对，而不是为了好看**：`mark_flush_edges` 的 docstring 列了 flush
的三个家族，并明确说这三类都是"渲染器不该描的边"——**接缝**（截面切口，"描上去就是横穿丝带
的一笔"）、**被盖住的侧边**（"一条线穿过丝带中间"）、**非 weave 的内部边**（同色内部的一条
线）。所以一条 overlay 只要与 flush 边重合，画出来必然落进这三个已被判过的家族之一，不存在
"两侧真的需要它"的情形（那种情形区域环上根本没有这条边，flush 判据也就不会命中）。

**这条判据同时管两个后端**：`missing_weave_outlines` 不只 boolean 调——`render/arrangement.py:524`
也调同一个函数。所以上收之后两边一起变干净；上一轮"只改 hybrid、共享函数不动"的写法本身就挡不住
arrangement 侧的同一类误报（实测确实挡不住：arrangement 的 `index-random-walks-6` 少了 3 条）。

**量到的爆炸半径**（57 个可跑案例全量扫描，不是只看被点名的那张）。"判据前"是 hybrid 本地版
那一轮量到的 `outline_edges` 条数，"判据后"是共享判据下的同一读数；第二列括号里是判据后仍与 flush
墨迹重合的条数，即下文第二条规则的产物：

```
                            布尔 overlay        其中仍与 flush 墨迹重合
spec-self-intersecting        12 ->  10          0（判据前那 2 条就是两条 stub）
index-random-walks-6          25 ->   6          3（2 条弦即那条 flush 边，1 条落在更长的 flush 边里）
index-random-walks-12         25 ->  13          9（9 条弦都即那条 flush 边）
adp-arc-overlapping          731 -> 727        397（本页只渲染 stroke 通道，未逐条归类）
ros-n5-ca-l2-o12               6 ->   0          0
其余 52 个案例                   0                0

                          arrangement overlay
index-random-walks-6           11 ->   8
adp-parametric                  2 ->   0
其余 55 个案例                   0
```

`ros-n5-ca-l2-o12` 那 6 条布尔 overlay 长度都是 `0.24 = 2 * offset`（整条横贯丝带），画上去就是
六道横切口，判据后归零；`index-random-walks-6/12` 与 `adp-arc-overlapping` 上去掉的是"被盖住的
侧边"与截面切口。把 720p/4K 上 boolean 与 hybrid 逐像素对照、把被去掉的墨迹标红后看到的正是这
两类：横穿丝带的短线、躺在丝带中间的粗笔画（画面随之变干净）。这一判据两个通道合计减掉 **48** 条
内部描边（boolean 43 条 = 2 + 19 + 12 + 4 + 6，arrangement 5 条 = 3 + 2），远不止人眼点名的那 2 条。

**面板逐像素对照**（`media/review` 对改动前备份 `media/_review_before`，通道差阈值 8/255）：全部
57 张可跑案例面板里只有 **6 张**变了——`spec-self-intersecting` boolean `46 px`（4 簇）、
`index-random-walks-6` boolean `207 px`（19 簇）与 arrangement `18 px`（2 簇）、
`index-random-walks-12` boolean `106 px`（11 簇）、`ros-n5-ca-l2-o12` boolean `1463 px`（22 簇）、
`adp-parametric` arrangement `3 px`（2 簇）；其余全部 `0 px`。两张实验性 hybrid 面板
（`spec-self-intersecting`、`ros-n5-ca-l2-o12`）都是 **0 px**：判据上收是行为等价的搬运，hybrid 的
画面一点没动。其中 `ros-n5-ca-l2-o12` 的 hybrid 面板现在与同案 boolean 面板也逐像素相同（`0 px`），
因为布尔 overlay 归零之后，hybrid 既没有可减的亚像素黑点、也没有可加的桥接。

**最后一列不是"判据没生效"，而是第二条规则的产物**：`max_flush_bridge` 的 flush 绕行桥接在一条
flush **边串**的两端之间画一条弦，用来把两段正常描边接起来（否则留一个"悬空端头"）。当边串只有
一条边时这条弦恰好等于那条 flush 边本身——这就是上表 overlaps 的来源（walks-6 2 条、walks-12 9 条；
walks-6 另 1 条落在另一条更长的 flush 边之上）。这类弦按构造都短于 `0.05 * offset`（≈1 px），
本轮**未动**：它属于"接断头"而不是"把被否掉的缝重新描一遍"，且它在画面上的效果是补上两个断头
之间 1 px 的缝。两个后端的 overlay 通道都还各有这类弦压在 flush 墨迹上（boolean：
`index-random-walks-6` 3 条、`index-random-walks-12` 9 条、`adp-arc-overlapping` 397 条、
`ros-n5-ca-l2-o12` 0 条；arrangement 另有 2 个案例——`index-random-walks-6` 1 条、
`index-random-walks-12` 5 条），共享判据只覆盖第一条规则，所以它们原样留下。这两族是本轮留下的残余。

**判据落在哪里**：上一轮只把它写进实验性 hybrid（"hybrid 不描自己区域走查判过 flush 的缝"），
共享函数 `missing_weave_outlines` 不动，好让 boolean 参考通道的数字保持可比。这一轮把它上收到
共享函数：`missing_weave_outlines` 现在把 flush 环边当作与描边同等的**覆盖**，一条 recorded lens
edge 只要落在某条 flush 环边上就不再升成 overlay；hybrid 里那份本地判据随即删除——同一个判决
不留两个副本，留两个就会在某一轮里得出两个结论。`benchmarks/weave_audit.py::notch_gaps` 也一并
学会同一件事，否则它会把"环自己判过不要描的缝"点名成"没描的缺口"（`docs/REVIEW.md` §206 早就
把它判成误报：顺着它描出来的是那根 44 px 竖刺）。两条改动与 §9 的根因同源：一条边是不是"该描"，
只能有一个地方回答。

**读数会动，动的部分要说清楚**：判据上收之后，命中案例上 boolean 通道的画面变干净（丝带内部
的横线和短刺消失），代价是审计读数回到"没有 overlay 兜住"的真实值：

- `notch_gaps`：`spec-self-intersecting` 两个通道都是 0 → 0——正因为同时教会了 `notch_gaps` flush
  覆盖，否则单点上收会在同一张上把它从 0 变成 2，那 2 段正是 §206 判过的误报。但这条子句不是
  空转：它一共让 **5 张卡的 arrangement 芯片**从"检查失败"变成通过——`index-random-walks-6`
  （`7` 段 / 0.7461）、`index-random-walks-12`（`22` 段 / 2.5151）、`ros-n5-ca-l2-o12`
  （`1` 段 / 0.0682）、`deg-figure-eight`（`5` 段 / 0.1795）、`gal-infinity`（`9` 段 / 0.1263）。
  这些段全都正落在 flush 环边上，所以是判据在拒绝把接缝说成缺口，**不是**这几张真的变健康了：
  `docs/REVIEW.md` 本轮审查那一节原先把密集随机游走的长切弦残余当真实缺陷看，而后两张是共点退化
  的展示案例（它们的 `REGION-COINCIDENT-CROSSINGS` 等诊断仍在，`notch_gaps` 不再搭车）。这属于
  "读数变好、画面没变"的一类，要看得见；
- `dangling_ends` 会**变多**，这是画面变干净的代价：`spec-self-intersecting` boolean `2 -> 4`、
  `index-random-walks-6` boolean `24 -> 36`、`index-random-walks-12` boolean `40 -> 48`，另外
  arrangement 通道上 `index-random-walks-6` `38 -> 39`（它也被判据覆盖：11 → 8 条 overlay）。这
  不是新缺陷，而是原先被 stub / 被覆盖边以 T 形接合"接上"的端头露出来了——它们本来就断在丝带
  内部（`spec-self-intersecting` 的 4 条 hybrid 桥接补的正是 4 个 V 形端头）。用一个不该画的短刺
  把审计"骗过去"不算通过。反过来也提醒：`adp-parametric` arrangement 的 overlay `2 -> 0` 而读数
  不变（仍 1 处），说明并非每条被去掉的边都托着一个端头；
- `index-random-walks-6/12` 的 boolean 通道本来就已经是 `FAIL`（24 / 40 处），变多不改变判定，只让
  数字更接近画面真实情况；全页合计因此是 **检查失败 14 → 9 项**（少的 5 项正是上一条的 5 张卡），
  警告 10 → 11 项（多的那 1 项是这一轮首次进页面的 `ros-n5-ca-l2-o12` hybrid 面板自带的
  `region.area_conserved`，见下条）；
- hybrid 的 `REGION-HYBRID-EXPERIMENTAL` 不再报 `dropped_seam_edges`：本地判据删掉后，它没有
  自己的丢弃计数，flush 覆盖是共享函数的职责。

**教训**：`flush` 是引擎对"这条缝不能描"的判决，任何把边重新升成描边的下游规则都必须
先问一句"它是不是已经被判过 flush"；否则同一个判决会在两个地方得出相反结论。
