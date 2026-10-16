# Changelog

## Unreleased — 画廊卡片：stroke 面板线宽对齐 ribbon 面板，且**不画描边**

用户先指出卡片里 stroke 面板的线条比其它面板粗、且没有黑色描边；加了描边之后又指出，那个描边在
**交叉处**给不出正确的上下关系，反而不如没有。最终定案：**线宽对齐保留，描边全部去掉**。

- Fix (`examples/scene_gallery.py`, `StrokePanel`): a card that fits its composition into the frame
  goes through `Mobject.scale`, which shrinks geometry but **leaves stroke widths alone** — so the
  stroke panel's strands stayed full size while the ribbon bands beside them shrank (measured on the
  `RosetteWeave` card: 22 px against 11 px; `RibbonGallery` avoids the mismatch by not scaling at
  all, and its own comment says why). `StrokePanel.refit(factor)` re-strokes the strands for the
  fitted scale — measured after the fix: `RosetteWeave` 12/11/11 px and `RosetteWeaveCA7` 27/25/27 px
  across stroke/boolean/arrangement. The rosette weave cards measure the fit factor and call it; the
  channel card is already unscaled, since the widths are set up in the constructor.
- 去掉描边（这是最终状态，中途试过一版"黑边"已作废）：这个通道的切口在交叉处是**严丝合缝相接**
  的（`cover_allowance = 0`），所以黑边没有地方可以"分开"两股丝带，两种画法都不成立——压在全部
  片段下面时，邻段的身体会把它盖掉，接头融成一片（`media/border_order_zoom.png` 左栏）；各自
  贴在自己那段下面（按绘制顺序交错）时，接头确实有线了，但那条线同时勾出"相接的两个端面"，读起来
  是"两股都描了边、在同一层"——恰是编织**不是**的样子（同图中间栏，右栏是 boolean 参考）。实测
  `RosetteWeaveCA7` 卡：stroke 面板黑像素 **0**，boolean/arrangement 仍各 3405 / 3288。
  `StrokePanel` 因此不再包任何图层，就是 `Lace(render="stroke")` 本身加一个 `refit`。
- 关于"能不能让这个通道自己读出上下"，两条路都实测过，都不成立（`media/gap_demo.png`、
  `media/gap_demo_zoom.png`）：引擎的 `cover_allowance` 方向和直觉相反——它把下股的切口**收短**、
  端点更往压住它的那股**底下塞**（`0 <= allowance <= overshoot`，此配置 overshoot=0.03），与
  `allowance = 0` 相比只有 **0.8% 的像素不同、面积 100.1%**，等于没变；反过来"给下股留缝"也不是
  免费的：要缝看得见就得把端点缩回不少（0.02，即半宽的 20%），实测 **63% 的像素改变、面积掉到
  82.4%**，环碎成一截一截——因为浅角交叉处上股的带沿下股方向延伸 `offset / |sinθ|`，绕开它要退
  一大截。这个通道读不出上下是它切**中心线**的代价，上下关系由另两个切**面积**并给切口描线的
  面板负责。
- Test: `test_the_stroke_panel_wears_the_cards_strand_width` — `refit(0.4)` scales the strands by the
  fit factor, the panel adds no layers of its own (`len(submobjects) == len(ribbons)`), and the
  channel card's stroke panel is one of these.
- 验证：`pytest -q` → 393 passed；`ruff check` 干净；用到 stroke 面板的 5 张卡已重渲。

## Unreleased — ribbon 描边：断在丝带中间的描边（ROSETTE_RIBBON_OUTLINE_TICKS 第四轮）

用户接着指出 `RosetteWeaveCA7` 卡左侧还有两处不对（一个"V"、一个"X"）。定位到**第四类根因**：
boolean 后端用**被分段窗口裁剪过的透镜**去切下股丝带，切口因此比真实重叠小，剩下的一块材料
伸到切口之外——环上就没有边沿缺口末端，描边无处可接，**断在丝带中间**（放大图上就是一根戳进去
就停的线；两处相邻的断头凑成"V"或"X"的样子）。arrangement 后端一直用两条臂带求交的真实形状，
所以它没有这个问题。

- Fix (`regions.render_region_geometry`): the cut now removes the overlap of the two passes'
  *own bands* — the same footprint the arrangement backend cuts with — intersected with the
  pass on top's **visible** material, which keeps the old guarantee that a cut never opens a
  gap the over pass does not cover. The weave geometry recorded for the marking uses that
  footprint too (the clipped lens's boundary carries section caps, which are seams, not
  notches). Measured on `n = 7` CA: 6 stroke ends dangling → 0; on `n = 10` PA level 1+2:
  0 before and after (its two "ends" were 3e-6 from another stroke, i.e. joined).
- Fix (`benchmarks/weave_audit.py`): the `dangling` column was measuring nothing — every end
  matched its *own* stroke line (distance 0) and counted as joined, and the point query it
  used is a bounding-box test that misses a stroke running a hair away. It now excludes the
  end's own stroke and queries with a buffered point; with that fixed it reports 6 on the
  old cut and 0 on the new one.
- 复测结果：48 组（n = 5…13 × 五花型 × 两后端）里 46 组 **缺陷/漏轮廓/缺口/断头 四项全 0**；
  剩余 `n5 CA L2 o12`（缺口 6 处/1.44、断头 5 处）与 `n5 PO L2 o12`（缺口 5 处/0.835、断头 12 处）
  仍是共点交叉退化配置（`REGION-COINCIDENT-CROSSINGS` / `REGION-LENS-APPROXIMATION` /
  `GEOM-NEAR_TANGENT` / `TOPOLOGY-ALTERNATION-RELAXED`），arrangement 后端在同样的配置上干净。
- 测试：`test_the_boolean_backend_leaves_no_stroke_end_inside_the_ribbon`（参数化两张卡：原卡
  `n10 PA L1p2 o08` 与报告的 `n7 CA L2 o10`），判据直接复用 `benchmarks/weave_audit.py` 的
  `dangling_ends`，实测在旧切口状态下失败（列出 6 处断头，正含用户指出的两处）。
- 验证：`pytest -q` → 392 passed；`ruff check` 干净；画廊 25 张卡全部重渲。

## Unreleased — ribbon 描边：编织缺口在丝带中间断掉（ROSETTE_RIBBON_OUTLINE_TICKS 第三轮）

用户核对第二轮的 `RosetteWeaveCA7` 卡时指出：boolean 面板上有一条描边"戳进丝带里面"。复测方法升级后
（见下）定位为**第三类根因**，与前面两轮都不同：

- Fix (`regions.mark_flush_edges`, `is_hidden`): the "covered side" test — an edge on the region's
  own band boundary, covered on the far side — used to run *before* the weave test, so an edge
  that is both a notch and a band edge was hidden as a covered side. That is exactly the case the
  pass **on top** is in: its own lateral edge crossing the pass below *is* the notch. Where the
  pass below does not carry that piece — its cut is clipped by the section windows it works
  through — nothing stroked it and the notch stopped in the middle of the ribbon. Measured on the
  `n = 7` CA card: a 0.461-long lens edge was stroked over 0.373 (81%), the last 0.088 left
  unstroked; the same edge in the arrangement backend was 100%. The notch test now runs first and
  asks the visible material: the edge is stroked when this region owns one side of it *and* the
  last-painted region changes across it; when some later strand is on top of both sides the notch
  is hidden underneath (its own outline is the one owed), and when the same region is on top of
  both sides the line is inside its own fill and is hidden as before. `topmost` now returns the
  region (index) instead of just its path, which also halves the point-in-polygon queries.
- Fix (`regions.render_region_geometry`): the Boolean backend recorded the *removed* lens as its
  weave geometry. That lens is clipped to the section windows the cut works through, so its
  boundary also carries section caps — and those made the renderer treat a seam as a notch and
  left the far end of the real notch unrecognised. It now records the boundary of the overlap of
  the two passes' own bands, which is what the arrangement backend builds its lens from.
  `_arm_strip` moved from `arrangement.py` to `regions.py` (both backends use it).
- 复测方法升级（`benchmarks/weave_audit.py`）：原审计的缺陷签名只能看见"多画的线"，看不见
  "**少画的线**"。新增第三栏 `notch gaps`：把每条记录的透镜边与区域实际发出的描边做一维区间
  比较，未被覆盖、且两侧可见归属确实不同（描边在此是应画的）的区间计为缺口。48 组里现在
  46 组为 0；剩余 `n5 CA L2 o12`（6 处/1.44）与 `n5 PO L2 o12`（4 处/0.72）属引擎已声明不可靠的
  共点交叉配置（boolean 报 `REGION-COINCIDENT-CROSSINGS`，arrangement 报 `REGION-LENS-APPROXIMATION`，
  另有 `GEOM-NEAR_TANGENT`、`TOPOLOGY-ALTERNATION-RELAXED`）——同一处 arrangement 后端画得完整，
  属该方法在退化配置下的诚实降级，不是本轮回归。
- Tests: `test_the_weave_notch_is_stroked_even_where_it_is_its_own_band_edge`（合成三条区域：一条
  共享边是缺口必须描、一条被后画区域两面盖住必须隐藏）与
  `test_the_boolean_backend_strokes_every_self_crossing_notch_whole`（在 `n = 7` CA 卡上，对每个
  自交的缺口边逐点检查"附近有同向描边，且该处两侧可见归属不同"）。两条都实测在旧顺序下失败。
- 验证：`pytest -q` → 390 passed；`ruff check` 干净；画廊 25 张卡全部重渲。

## Unreleased — 状态画廊：玫瑰线编织从 1 张卡增加到 5 张

用户核对第一轮修复后要求"多画几个玫瑰线编织的例子"，于是把审计覆盖的配置直接做成卡片——
每一张都是修复前真的中过缺陷签名的配置，是证据而不是凑数：

- `RosetteWeaveCA7`（n=7 CA level 2，offset 0.10）：第一个命中缺陷签名的配置。收敛尖端把交叉的
  两刀切弦正好落到丝带侧边上，一条外边一半是接缝一半是切口，`mark_flush_edges` 曾同时把它判反
  两个方向。一个 29 点闭合 strand、14 处交叉全是自交。
- `RosetteWeaveCR11`（n=11 CR level 2，offset 0.07）：命中 `_drop_folds` 批删 bug 的配置——薄楔形
  的楔尖被当成噪声折返删掉，环上少一整块。一个 45 点闭合 strand、22 处交叉全是自交。
- `RosetteWeaveThin`（n=10 PA level 1+2，offset 0.05）：与 `RosetteWeave` 同源同解，只把丝带半宽
  减半，让透镜整个落在被压丝带内部——arrangement 面归属与面积核算的形状，也曾误报
  `REGION-AREA-MISMATCH`。
- `RosetteWeaveTypes`（n=10 level 2 五种花型 × boolean/arrangement 两排）：两排必须逐列长出同一种
  编织；对不上就是这类问题的原始签名。每格一个 41 点闭合 strand、20 处交叉全是自交，下排 0 诊断。
- 重构：`build_rosette_weave_trio` 参数化（默认值即原来的 `RosetteWeave`，测试钉不死的行为不变），
  卡片逻辑上收 `_RosetteWeaveCard` 基类；每格 caption 带上实测的交叉/可见面数；画廊 note 分支改为
  读场景自己的 `SOURCE`，不再把 n=10 PA 写死。
- 修：`RosetteWeaveTypes` 的行标签原来挂在左侧，把组版中心拉离原点，而 `_fit_frame` 绕自身中心
  缩放——缩放后整组左沿冲出画幅（标签被裁成 "ean"/"ent"）。行标签改为行题，`_fit_frame` 增加
  `move_to(ORIGIN)`（对已居中的现有卡片是无操作）。
- 测试：`test_the_weave_cards_paint_the_whole_ribbon_in_both_backends`（参数化遍历三张新卡的
  SOURCE）：`band_union - painted` 与 `painted - band_union` 都必须为空（前者抓住 fold 丢楔形和
  并集丢面，都已实测会在旧代码上失败），且每个有面积的孔必须被另一个区域盖上。
  `test_the_flush_indices_address_the_ring_the_renderer_draws` 新增：合成区域精确复现"一条边被
  split、一对共线边被 merge、点数抵消"的场景，钉住环必须换成 joined 环（旧逻辑下实测失败）。
- 验证：`pytest -q` → 388 passed；`ruff check examples src tests` 干净；五张卡全部重渲，
  页面 25 张卡片；审计 48 个配置×后端组合缺陷签名仍为 0。

## Unreleased — ribbon 描边：同一条"丝带中间的线"的三个后续根因（ROSETTE_RIBBON_OUTLINE_TICKS 第二轮）

上一轮修完透镜归属后，用户反馈"还没有真正修好"。对 24 个玫瑰线配置（n = 5…13 ×
PA/PO/PR/CA/CR × offset 0.05…0.12，含单层与双层合并）× 两个 ribbon 后端按缺陷签名
复测（被描边、两侧都被已绘区域覆盖、同路径在上、不在任何透镜边界上），原投诉的那张卡
（n = 10 PA level 1+2，offset = 0.08）确实是 0，但另有 6 个配置命中——全部落在下面三个
根因上，全部已修：

- Fix (regions, `mark_flush_edges`): the ring was rebuilt from the judged pieces but only
  *replaced* when the point count changed. One edge can be split (a vertex inserted) while
  another pair of near-collinear edges is joined (a vertex folded away) — the two cancel out,
  the count stays the same, and the original ring is left wearing `flush_edges` indices that
  address the joined ring. The renderer then strokes the half of an edge that is a seam and
  hides the half that is outline: measured on `n = 7` CA level 2 (offset 0.10), Boolean
  backend, `P0000#14.region0` edge 1 was split into visible + hidden + hidden but the ring
  kept the full edge — a 0.111-long line across the ribbon — while edge 3 (real silhouette)
  was hidden. The replacement now happens whenever the joined ring differs from the original
  *point by point*, and a ring that joins into fewer than three runs (a zero-area sliver)
  keeps its original ring with an all-or-nothing flush set. A piece that spans a whole edge
  keeps the ring's own points, so a ring nothing happened to stays byte for byte what it was.
- Fix (arrangement backend, new `_node_geometry`): a node's faces were merged with a one-shot
  `unary_union`, and the overlay engine can **drop a face that only touches another along an
  edge** — which of the two survives depends on the operand order. Measured on `n = 7` CA
  level 2: the union lost a 2.3e-3 face and left a hole in the painted ribbon (`gap.union(f1)`
  kept it, `f1.union(gap)` dropped it, both orders of `unary_union` dropped it). The union is
  now checked against the sum of the faces' areas — the faces of a planar arrangement are
  interior-disjoint, so the sum is exact — and when it cannot be trusted the faces are kept as
  they are and drawn as the separate regions they are (their shared edge is interior to one
  colour and gets flushed like any other section boundary). `painted_area` is now the exact
  sum of the faces' areas for the same reason.
- Fix (regions, `_drop_folds`): folds were removed in batches — every vertex that looked like
  a zero-area reversal in one pass went at once. A crossing whose two cut chords meet on a
  band's lateral edge leaves the tip of the wedge as several copies of one point differing
  only in the last bits (the polygon boolean's noise); each copy looks like a zero-area
  reversal on its own, and dropping them all removed the vertex the ring really turns at —
  and with it the whole wedge (a 2.8e-3 triangle, i.e. a hole). Measured on `n = 11` CR
  level 2 (offset 0.07), Boolean backend, `P0000#20`. Folds now come off **one at a time**,
  re-judging the ring after each drop, which is what the docstring always claimed; the last
  copy is then judged against the ring's real corners and kept.
- Fix (regions, `_covered_area` + `mark_flush_edges`): the one-shot `unary_union` over *many*
  parts is unreliable in the same way — measured on `n = 13` CA level 2 (offset 0.05), 40 of
  158 valid parts came out uncovered and the area 5e-2 short, in every operand order. The
  area accounting (`painted_area`, `union_area`, `hidden_area`) now unions the parts one at a
  time and verifies that the result covers every part, trying the orders both ways (a lossy
  union is a lower bound, so a verified attempt is exact); that also removes the spurious
  `REGION-AREA-MISMATCH` this render used to report. The interior test inside
  `mark_flush_edges` no longer asks a union at all — it asks region by region, so a part the
  union would drop can no longer make the edges around it look like the silhouette.
- Tests: `test_a_zero_area_fold_is_dropped_and_a_real_thin_corner_is_kept` now expects the
  excursion to collapse to the straight run (the turnaround vertex goes; the point it returned
  to stays, and the ring covers the same area — asserted with the polygon area), and
  `test_a_wedge_whose_tip_is_near_duplicate_points_survives` is new: a wedge whose tip is
  three noise copies of one point keeps its vertex and its area. `pytest -q` → 384 passed,
  `ruff check src tests examples` clean (`ruff format --check` fails on 41 files on `main`
  already, unchanged by this round).

## Unreleased — arrangement 后端：自交的透镜归“压住对方的那一遍”

- Fix (arrangement backend): the faces inside a self-crossing's lens were given to whichever
  covering section sorted first, so at some crossings the lens went to the **under** pass and
  the weave reversed there. The Boolean backend cuts the under pass of a self-crossing by the
  same local overlap (``under_arc``/``over_arc`` from the assignment), and the stroke backend
  cuts the same pass too; only the arrangement named the over side by *path* — which is the
  same path on both passes of a self-crossing — and then broke the tie by node id.
- Measured on the gallery rosette (70 crossings, 20 self-crossings, all on P0002): at
  ``X0050`` (point (+1.1135, −0.809), ``s_a`` = 0.5257 on the horizontal pass, ``s_b`` =
  49.9221 on the steep pass, ``sin θ`` = 0.9511) the assignment says ``under_side = "a"`` —
  the horizontal pass goes under. The stroke panel confirms it (its pieces near arc 0.5257
  have a gap there; ``P0002.piece1`` starts at 0.6122) and the Boolean panel cuts it (strips
  0/1 carry the notch). The arrangement handed the lens to ``P0002#0`` — the section
  [0.5257, 1.9021], i.e. the *under* pass — leaving the horizontal ribbon whole and cutting
  the steep one.
- What the user saw (docs/ROSETTE_RIBBON_OUTLINE_TICKS.md §1, world ≈ (+1.03, −0.80)): the
  Boolean panel stroked the weave diagonal **L′** from (+1.1716, −0.729) to (+1.2236, −0.889)
  across the purple ribbon — the second of the crossing's two notch lines — which the
  arrangement did not draw; and the arrangement stroked a **0.110-long horizontal stub**
  (``P0002#26.region1`` edge 3, (+1.2236, −0.889) → (+1.1135, −0.889)) along the band's
  bottom edge *inside* the lens, i.e. a black line in the middle of the ribbon.
- The fix names the over side by its sections: ``over_sections_of[crossing_id]`` holds the
  sections that meet the path at the **over** arc (``_StripBuilder.adjacent``), and a lens
  face goes to them; only when none of them covers the face does the choice fall back to the
  path order. Measured after the fix: the lens at X0050 belongs to ``P0002#26`` /
  ``P0002#27`` (the steep pass) — the pass the Boolean backend leaves whole — the arrangement
  now strokes the same L′ (``P0002#0.region0`` edges 8–9, ``P0002#26.region1`` edge 3) and the
  stub is gone; the Boolean panel is unchanged.
- The decomposition is untouched: the arrangement's ``region_area_sum`` stays exactly equal to
  its ``union_area`` (15.498939905 on the rosette, 0 diagnostics), and the fills do not move —
  both passes are P0002, so the lens changes owner inside one palette colour.
- The doc's §2 criterion (“stroked edge strictly inside its own band, off every other band”)
  counts 323 (Boolean) / 395 (arrangement) edges: those are the weave notches — the lens
  boundary inside the under band, which §3.2 correctly refuses to flush. Measuring the defect
  signature directly (an edge covered on **both** sides by the painted union, with the same
  path on top on both sides, and on no lens boundary) finds **0** such edges in either
  backend, before and after the fix.
- Tests: ``test_the_under_pass_of_a_self_crossing_does_not_own_the_lens`` now checks the lens
  against the sections at the *over* arc instead of merely the path id (it uses the pentagram
  {5/2}, whose crossings are far enough apart for the sections to tell the passes apart), and
  ``test_both_backends_cut_the_same_pass_of_a_self_crossing`` is new: a probe on the under
  strand just inside the lens must be painted by the over strand's sections in **both**
  backends. Both fail when the ownership decision is patched back to the section order.
- Still present: where the sections are too coarse to tell the passes apart — a path with a
  single self-crossing, where both passes touch both sections — the arrangement still falls
  back to the section order. The fix is a no-op there, so nothing regresses, but that
  configuration's weave is not expressible in the long-section decomposition this backend
  uses.

## Unreleased — 布尔后端：切口不再在丝带中间留下“洞”

- Fix (Boolean backend): a cut that lands *inside* the under band without reaching its edges
  used to be emitted as an occlusion **hole**. The over strand's local footprint is subtracted
  from the under band, and near a miter corner the footprint can sit strictly inside it, so the
  subtraction leaves the band connected *around* a hole instead of severing it. A hole cannot be
  rendered as a gap — Manim fills an exterior ring solid — so the adapter paints it in the paper
  colour, which only works while the piece covering the footprint is painted *later*. The painter
  order cannot always arrange that: two strands that cross more than twice alternate their
  over/under into a cycle no total order satisfies (the backend reports
  ``REGION-DRAW-ORDER-CYCLE`` there). Measured on the gallery's rosette: the Boolean panel had a
  **148 px background-coloured bite at (+0.81, +1.59)**, exactly the exposed
  ``P0002#92.region0`` occlusion hole (0.031643 world², covered by ``P0000.region0`` at a *lower*
  paint index). The minimal reproduction is small — n=10 level 1, 2 loops, 10 crossings, 7
  regions, 1 hole — and per-crossing measurement shows that exactly one of the ten congruent
  crossings leaves it.
- The fix opens such a hole into a **notch on the piece's own boundary**:
  ``regions._open_occlusion_holes`` splits the piece along that crossing's cut chord, so the fill
  itself stops at the cut and the over strand's region — which always covers its own footprint —
  is what shows through, whichever order the two are painted in. The split chord joins the
  existing flush-seam bookkeeping, so it is never stroked and the fill is closed over it
  (verified: no enclosed background component appears along it in the render).
  ``source_contour`` holes are untouched — those are genuine gaps (the inside of a closed loop).
- Measured after the fix: the simple 10-crossing rosette goes from 1 occlusion hole to 0 and from
  7 to 10 regions (the offending piece splits into two equal halves of 0.581759, matching its
  neighbours); the gallery rosette goes 158 → 159 regions with 0 holes and
  ``band_union - union(exteriors) = 0.000000``; both ribbon panels of the **re-rendered card**
  now have zero pixels inside the band union that no region paints (the Boolean panel had exactly
  one such area before). The stroke panel is unchanged (19 tiny 1–27 px gaps, its own known
  butt-cap character), and the dark pixels inside the ribbon panels are the card's intentional
  2 px strand outlines, not seams.
- The opened bite's own boundary is registered as a flush seam as well, so the piece never
  strokes it: half of it lies on the *over* strand's side (which the strand on top outlines
  itself) and the other half on the under strand's own side, which is merely hidden under that
  strand rather than ended. Measured: the bite's ring has 2 edges on the over band's side and 2
  on the under band's side; the under-side pair turns out not to be part of any piece's
  exterior at all, and the over-side pair was being stroked twice. On the rendered card that
  was a doubled 2 px black stroke on the indigo/purple boundary at the bite (measured: 60 px
  of black over fill, arrangement panel 0 px) — now a single stroke, with the weave diagonal
  still drawn by the over strand's own outline.
- Tests: ``test_the_ribbon_panels_leave_no_occlusion_hole`` asserts for both ribbon backends that
  no region carries an occlusion hole and that the union of the region exteriors covers the band
  union exactly.

## Unreleased — stroke 后端：闭合路径不再在自己的接缝处被劈成两段

- Fix (stroke backend): a closed path whose seam falls *inside* a visible arc is now emitted as
  **one wrapping piece** instead of two pieces butting at the seam. The seam is not a cut: when
  nothing cuts the path there, the visible arc runs through arc 0 and the two halves are one and
  the same piece. Splitting them painted two butt caps back to back, and because each cap is
  perpendicular to its *own* local polyline chord rather than to the tangent, the pair left a
  hairline wedge of background at the seam. Measured on the channel card's ring: the stroke
  channel drew it as 2 pieces of 61 points meeting at (+1, 0) — exactly the crossing where the
  ring passes *over* the bar — with end-segment directions +91.42° / +88.58°, i.e. two caps
  2.84° apart; the wedge between them is 0.4 px wide 8 px from the seam and 1.5 px wide at
  dx = +31, which is exactly the 1-px light line the render shows from dx 8 to 31. The ring is
  now one piece of 121 points (arc 3.3679 … 9.1973 on a 6.2826-long loop) and the wedge is gone.
- The wrap-around is the rule, not a special case: for a closed path the visible set is the
  complement of the cuts *on the circle*, so exactly one visible arc can contain the seam and it
  is emitted as a single piece through ``_slice_arc(path, last_start, length + first_end)`` — the
  same construction the existing ``piece-seam`` branch already used for the mirror situation (a
  cut that *covers* the seam). Both directions are pinned:
  ``test_closed_path_seam_inside_a_visible_arc_stays_one_piece`` is new,
  ``test_under_cut_wrapping_the_closed_seam_does_not_duplicate_geometry`` is unchanged.
- Why the ribbon backends never showed it: they cut polygons, and a bite out of an annulus does
  not disconnect it. The channel card's ring is one region there, its cut edges are exactly
  y = ±0.2200 (angle +0.00° / +180.00°), and its cut end meets the bar's edge at a measured
  distance of 0.000000.
- Still present, and measured — not fixed here: in the stroke channel the *under* strand's cut
  face is a butt cap perpendicular to the local chord, so it is not parallel to the strand on
  top of it. At the channel card's left crossing (the ring goes under the bar) the cap is tilted
  **12.71°** to the bar (piece ends at (−0.9742, ±0.2246), last-segment directions −102.71° /
  −77.29°) — the cut sits ``offset/|sin θ| + overshoot·offset`` = 0.2266 from the crossing, and
  a chord of the unit circle at that arc distance is tilted 0.2266 rad ≈ 13°. The ribbon
  backends cut the same crossing exactly parallel to the bar.
- Also still present: ``overshoot`` (0.03 × offset = 0.0066 ≈ 0.9 px, up to a 3 px crescent
  where the ring's curved band edge pulls away from the bar's straight cap) is hard-coded in the
  engine and not reachable from ``Lace``, so the under strand stops just short of the true
  crossing and a thin crescent of paper remains at that junction.

## Unreleased — 画廊三处示例修正：玫瑰线的白描边、玫瑰线的不交替、绘制通道卡看不清

- Fix (rosette card): ``RosetteWeave`` no longer forces ``weave_mode="free"``. The three loops
  have 70 crossings (20 of them self-crossings) and strict alternation solves **all** of them:
  measured zero "same side on two consecutive visits" on every loop (60 such defects under
  ``free``), every assignment carrying ``source="alternating"``, no relaxation, and no
  ``TOPOLOGY-ALTERNATION-*`` diagnostic — the strict ``error`` strategy produces the identical
  assignment, so nothing had to give. The stricter assignment also simplifies the cut: 165 →
  158 visible pieces and 2 → 1 holes. The old wording — "a single path cannot resolve its own
  over/under with alternation constraints" — was simply wrong: a self-crossing is an ordinary
  transverse event, as the pentagram card has shown since the default changed.
- Not fixed, and deliberately not claimed: the *boolean* backend still reports
  ``REGION-DRAW-ORDER-CYCLE`` + ``REGION-OVERLAPPING-SECTIONS`` on this dense input, and it
  reports them under ``free`` and under ``alternating`` alike — they come from the geometry,
  not from the assignment. The same input is diagnostic-free in the arrangement backend (90
  pieces) and in the stroke channel (70 pieces, after the seam-split fix in the section above —
  it was 73 before, one extra piece per closed loop); the gallery note prints whichever each
  card really has.
- Fix (rosette card): the ribbon panels are now stroked in black (``stroke_color=BLACK``,
  ``stroke_width_px=2.0``) and their holes are painted in the paper colour. The facade's
  default stroke colour is white, so on the card's white paper every strand edge was drawn in
  paper colour and the weave read as a soft blur; the outline is what makes the cuts legible.
- Fix (channel card): ``RibbonGallery`` used one colour for both strands *and* a black
  background with ``hole_color=BLACK``, so the two ribbon panels rendered as a single flat
  silhouette — the card compared nothing. The strands now take two colours from a palette
  (``natsu``), the paper is white, the ribbon pieces keep a black hairline, and each panel
  carries a one-line caption naming its mechanism.
- Fix (both comparison cards): the panels are no longer scaled. ``Mobject.scale()`` leaves
  stroke widths alone, so scaling fattened the stroke panel's strands (whose width *is* a
  stroke) while the ribbon bands shrank — the three panels were no longer the same input.
  Measured after the fix: the ring's outer bbox differs by 1–2 px between the three panels,
  and the band half-width in the render is 29 px = ``offset`` 0.22 exactly, in all three.
  Panels are arranged on the laces alone and captions are attached afterwards, so a wider
  caption cannot push its panel sideways.
- Verification: sampling the rendered crossing pixels of all three panels reproduces the
  solver's assignment exactly (right crossing: ring over; left crossing: line over) — the
  weave alternates and the three channels agree, pixel for pixel at the crossings.
- Docs: the rosette section of ``README.md`` and the ``build_star``/``RosetteWeave``
  docstrings were corrected (the pentagram's strict alternation *is* solvable; "40 处自交" was
  really 20; the rosette panel is no longer described as falling back to a non-alternating
  assignment).

## Unreleased — ribbon 环去掉布尔折返尖刺（端点处的"小胡须"）

- Fix: ribbon rings no longer keep the zero-area *folds* a polygon boolean leaves behind when
  a cut only touches the boundary (the tip of a weave lens is the usual case): the ring runs
  out along a line and comes straight back to where it started. The fold encloses no area, so
  the fill always looked right, but the fold is part of the ring — stroking it drew that line
  as a short whisker poking into the neighbouring ribbon, and a slightly open fold drew as a
  thin dark sliver inside the ribbon. Both were visible on the trefoil, the 2×2 circle grid
  and the chain cards.
- The fix is `regions._drop_folds`, applied wherever a ring is converted for the region
  backends (``regions._ring_points``, so the boolean and the arrangement backend and their
  holes all get it): a vertex is dropped only when the ring *turns back into itself* and the
  triangle it spans holds no area (``<= 1e-12`` world units²), and the removal repeats until
  none is left because dropping one fold can expose another. A genuine corner — even a thin,
  sharp one like the cusp where three boundaries meet — turns back but spans area, so it is
  never touched. Measured on the three cards: 0 of the fold vertices survive, and the total
  ring area changes by 0.0 (the folds contributed nothing).
- Tests: `tests/test_regions.py::test_a_zero_area_fold_is_dropped_and_a_real_thin_corner_is_kept`
  (the rule, including that a real cusp and a degenerate ring are left alone) and
  `test_a_ribbon_ring_never_keeps_a_folded_vertex` (the chain card's three circles: every ring
  the backend hands out is fold-free — this one fails without the fix).

## Unreleased — 默认即"尽可能交替编织"（`conflict_strategy` 默认改为 `relax`）

- Change: ``conflict_strategy`` now defaults to ``"relax"`` (engine, ``solve_weave`` and the
  ``Lace`` facade) instead of ``"error"``. The project's point is a woven pattern, so the
  default path must weave: strict alternation is kept at every crossing where it can hold and
  only the constraints that have to give are relaxed, each relaxed crossing carrying
  ``source="relaxed"`` and a ``TOPOLOGY-ALTERNATION-RELAXED`` warning (with the minimal
  witnesses and the ``relaxed_crossing_ids`` that were actually relaxed). Before this, an
  unsatisfiable input fell back to *no assignment at all* by default, which a renderer can
  only show as an un-woven pattern (every transverse crossing reported as
  ``REGION-MISSING-ASSIGNMENT``/``RENDER-MISSING-ASSIGNMENT``).
- ``error`` is unchanged and still available for callers that must not accept an
  approximation; the tests that pin "no assignment, full pieces, witnesses only" now ask for
  it explicitly (``tests/test_conflict_strategy.py``, ``tests/test_stroke.py``,
  ``tests/test_topology.py``).
- Tests pin the new contract from both ends: ``solve_weave``/``LaceEngine`` default
  (``test_the_default_strategy_relaxes_the_same_input_instead_of_giving_up``,
  ``test_the_default_engine_strategy_relaxes_and_marks_instead_of_giving_up``) and the facade
  default (``test_the_facade_also_weaves_as_far_as_it_can_by_default``: full assignments,
  ``TOPOLOGY-ALTERNATION-RELAXED`` present, ``TOPOLOGY-ALTERNATION-UNSAT`` absent).
- The spiral gallery card now uses the default mode too: two of its four crossings are
  relaxed and reported, the other two keep strict alternation. The lemniscate card stays on
  ``weave_mode="free"`` because strict alternation there makes the two crossings at the shared
  point remove their overlap in opposite directions (``REGION-AREA-MISMATCH``), which is a
  geometry-accounting problem rather than a parity one.
- Docs updated where they named the old default: README (feature table, 重要语义, gallery
  section), ``docs/ARCHITECTURE.md`` (conflict strategy) and ``docs/ROADMAP.md``.

## Unreleased — 画廊里的编织图案改用严格交替模式

- Fix: the showcase weaves that can be solved by strict alternation now use it instead of
  ``weave_mode="free"``. Free mode's deterministic default alternates the *side letter* by
  crossing index, not the strand (``topology/solver.py``), so a strand could land on the same
  side twice in a row: the cross grid's vertical line crossed three horizontal lines and came
  out over, under, under. The same input under the project's default ``alternating`` mode
  solves cleanly (no ``TOPOLOGY-ALTERNATION-UNSAT``) and gives the expected over, under, over.
  Fixed on the cross grid, the 2×2 circle grid, the trefoil, the chain, the sine/line card and
  the pentagram; their gallery tags now say 交替模式 and their prose states what the weave does.
- The pentagram card no longer claims that strict alternation is impossible for it. A
  self-crossing path is walked as ten passes (an even number), so the alternation constraint
  is satisfiable there and the solver assigns all five self-crossings with ``source=
  'alternating'``; the measured pass sequence is ``OuOuOuOuOu``. The card's output is
  unchanged, only its description was wrong.
- The two cards that genuinely cannot alternate keep ``weave_mode="free"`` and now say why on
  the card: the spiral reports ``TOPOLOGY-ALTERNATION-UNSAT``, and the lemniscate's coincident
  crossing makes strict alternation remove the shared overlap in opposite directions, which
  the area accounting reports as ``REGION-AREA-MISMATCH``.
- The README's ``free`` bullet now spells out what its default really is (side-letter
  alternation by crossing index), since that is the part that surprises: it does not promise
  a per-strand over/under sequence.

## Unreleased — 自交分段不再在股线上画横线（ribbon 轮廓修正）

- Fix: a self-crossing ribbon drew a row of short transverse ticks across the strand at every
  crossing instead of two clean weave edges. The section split that gives a self-crossing its
  two passes leaves a *seam* — a chord across the strand where two regions of the same strand
  abut — and that chord was being stroked like a real outline: `_stroke_runs` appended the
  closing point of a run before checking whether the *next* edge was a seam, so the seam edge
  itself stayed in the run. The pentagram showed 82 stroked seam edges; it now strokes 54
  outline runs and no seam at all.
- Fix: `mark_flush_edges` no longer guesses seams from shared edges. On a self-crossing that
  heuristic cannot work: the under pass's notch lies exactly on the over pass's outline, so
  the two kinds of edge are indistinguishable *and* a seam is only ever part of the
  neighbouring region's edge. Seams are now the edges that lie on a real section cut chord,
  computed by the new `_cut_lines` from the arcs where the sections were actually split
  (`_section_boundary_arcs`); both region backends pass their own cuts in.
- Fix: outline runs no longer contain collinear middle vertices. Boolean subtraction and
  polygonisation cut one straight edge into several collinear pieces, and stroking each piece
  on its own is a row of ticks; `_rejoin_collinear` re-joins them first, while keeping a
  vertex the boundary walks back along (a zero-width spike) so a stroke is never shortened
  into a gap. Six such midpoints remain on the pentagram and are removed before stroking.
- `Lace` gains an `outlines` layer: a piece whose exterior carries seams is filled without an
  outline stroke and stroked through open runs *between* the seams, one mobject per run (one
  mobject with several subpaths would link them with exactly the seam line this avoids). A
  scene that draws `lace.ribbons` must draw `lace.outlines` with it — `build_animation` and
  the gallery scenes do.
- Two rendering details the seams need: each stroke run's ends are extended by half a stroke
  width so the runs either side of a seam overlap instead of meeting in a single antialiased
  point, and each seam is restated in the fill's own colour at `z_index = -0.5`, below every
  fill, because two abutting polygons each paint only part of the pixels on their shared edge
  and the background otherwise shows through as a hairline across the strand. Being below the
  fills as well as below the outlines, that hairline cannot nick either.
- Tests: `tests/test_regions.py` pins that a self-crossing marks the section cuts as seams and
  the weave notches are not among them, and `tests/test_arrangement.py` pins the same for the
  arrangement backend; `tests/test_optional_manim.py` pins that a cross-path crossing needs
  neither seams nor an outline layer, and that no stroke run keeps a collinear middle vertex.
- The weave gallery's card titles are drawn in black: `_WeaveGallery` sets a white camera
  background and left the title text in the default white, so the eight woven-pattern cards
  had no visible title in the image.

## Unreleased — 自交也按偏移带求交切口编织（ribbon boolean 后端）

- Fix: the Boolean ribbon backend no longer leaves self-crossings to the paint order. A
  self-crossing's two passes are two different sections of one path, so the under pass is
  now cut by the local overlap of the two offset bands — the same construction used at a
  cross-path crossing. On the 90-degree bow and figure eight the hidden area is exactly the
  analytic ``4 * offset ** 2``; the pentagram's five self-crossings are all cut and its
  visible pieces cover the ribbon exactly (``painted_area == band_area``, no holes).
  ``tests/test_regions.py`` pins the cut and that each pass keeps its own material beside
  the crossing; ``tests/test_arrangement.py`` pins that both backends now hide the same
  area on a self-crossing instead of disagreeing.
- ``build_sections`` gains ``pass_windows`` (used by the Boolean backend only): a window
  either side of every self-crossing pass, so one pass's local material is its own
  geometry. Without it the piece between a crossing's two split points carries the material
  of *both* passes, and cutting it would erase the strand that stays on top (this was
  visible as an ``REGION-AREA-MISMATCH`` and an over-large ``removed_area``). The
  arrangement backend keeps the plain crossing splits and its output is unchanged.
- ``REGION-AREA-MISMATCH`` now measures the visible area against the *ribbon* union as soon
  as a split point lands on a vertex (``REGION-SECTION-SEAM``), where the union of the
  sections is not the ribbon; before it compared against that smaller union and warned about
  a mismatch that did not exist. ``REGION-SECTION-SEAM`` and ``REGION-DRAW-ORDER-CYCLE`` now
  say what they mean (overlap or missing corner area; the cycle no longer decides any
  crossing), and ``REGION-OVERLAPPING-SECTIONS`` is emitted only when pieces really overlap.
- Fix: ``_sections_around`` no longer feeds a generator over the list it extends — on a
  closed path that grew the list without bound and hung the render.

## Unreleased — 玫瑰线示例（examples/rosette.py）

- Add `examples/scene_rosette.py`, a five-scene gallery for the migrated star-rosette
  module: `RosetteGallery` (the five star types at n=10 level 2, each labelled with its
  real largest usable level), `RosetteLevels` (level 0 to the largest level `n=10 PA`
  supports, with the merged loop/point counts per level), `RosetteConstruction` (the
  documented pipeline panel by panel: kernel + x-axis mirror → rotated petals →
  `sort_petals` order → the merged loops as `StarRosette` draws them), `RosetteWeave`
  (the merged loops are closed self-crossing strands, so they go straight into
  `manim_lace.Lace` in all three channels) and `RosetteLimits` (the real feasibility
  boundary plus the actual `ValueError` text). Each scene prints the numbers it drew.
- `examples/rosette.py` holds the star-rosette geometry (it is example support, not
  package code: `manim_lace` never imports it and it is outside `src/`), and
  `examples/scene_rosette.py` imports it through an explicit examples-directory path
  entry so the scenes run from any working directory.
- `examples/build_gallery.py` gains a rosette section: it probes `StarRosette` the same
  way it probes `Lace`, so the cards report the real n/level/star_type, merged loop
  counts, crossings, visible regions and diagnostics, and the page carries a table of
  the largest usable level per `(n, star_type)` found by probing `cal_kernels` (level 12
  means "at least 12" for odd n's PA/PO/PR; even n is finite everywhere).
- `make lint` and CI keep their existing targets
  (`ruff check src tests examples benchmarks`); the moved module is covered by
  `examples` like everything else in that directory.

## Unreleased — 状态画廊生成器与场景修正

- Add `examples/build_gallery.py`: renders every showcase scene with the current
  checkout and writes `media/gallery/index.html` from the objects those scenes really
  build. A probe records the `Lace` instances created while `construct` runs (with
  `play`/`wait`/`add` stubbed out, so collecting data is independent of rendering),
  which is where every number on the page comes from: crossings, visible
  regions/pieces, area accounting, diagnostics, palette choices, density
  simplification counts and trace-event statistics. The page also carries the
  palette card read from `manim_lace.style.palette`, a real `sampling.subdivision`
  payload, a table of the trace event types that were emitted, and a "diagnostics
  and honest degradation" table listing what the rendered patterns actually raised.
  Flags: `--no-render` (refresh the data only), `--skip-videos`, `--only <Scenes>`,
  `-q l|m|h|k`.
- Add `examples/scene_gallery.py::GALLERY`: each showcase weave is now described
  once by a `GalleryEntry` (title, blurb, tags, builder, framing) that both the
  scene class and the gallery page use, so a pattern is never described in two
  places and its prose cannot drift from its geometry. `RibbonGallery` shares
  `build_backend_trio()` with the page's accounting table.
- Fix two showcase patterns that the new measured page exposed as not doing what
  their prose claimed: `GridGallery` used four exactly *tangent* circles (zero
  crossings) and now uses really overlapping ones (centres 1.5 apart, radius 0.9,
  eight crossings), and `StarGallery` used a simple ten-sided star that does not
  self-intersect at all and is now a real pentagram (`{5/2}`, five self-crossings,
  cut into sections and resolved by paint order — reported as
  `REGION-DRAW-ORDER-CYCLE` / `REGION-OVERLAPPING-SECTIONS`). The sine and spiral
  blurbs no longer state crossing counts that the code does not produce.
- The rendered media and the page live in `media/gallery/` (the same ignored
  directory Manim renders into), so re-running the script leaves nothing untracked
  behind in `examples/`.

## Unreleased — fine-grained traces (M5 done)

- Add `manim_lace.tracing` with `BoundedRecords`: a trace payload that counts every
  record exactly while keeping a bounded, order-preserving prefix
  (`DEFAULT_TRACE_RECORD_LIMIT` = 64), emitted as `<key>` / `<key>_count` /
  `<key>_truncated` so a shortened list never looks complete. Every fine-grained
  payload now uses that scheme.
- Trace the adaptive subdivision (`sampling.subdivision`, stage `input`):
  `sample_parametric` and `sample_graph` accept a `subdivision_tracer`, which
  receives one summary per sampled source curve with the effective
  `max_error`/`max_step`/`max_depth`, exact counters (`interval_count`,
  `node_count`, `split_count`, `accepted_count`, `budget_capped_count`,
  `singular_count`, `max_depth_reached`, `dropped_interval_count`, `part_count`,
  `sample_count`) and a bounded `decisions` list of
  `{kind, reason, t0, t1, depth, error}`. Every recursion node ends in exactly one
  of split/accept/depth-cap/drop, so the counters add up; `sample_graph` adds
  `jump_split_path_count` when its optional jump splitting ran afterwards.
  Tracing does not change the samples.
- `LaceEngine` accepts `sampling_trace=` (the summaries of the paths it was given)
  and emits one `sampling.subdivision` event per summary before the
  `path.normalized` events; `LaceEngine.from_parametric` / `from_graph` fill it in
  automatically, so `Lace.from_parametric(...).result.trace` describes the
  subdivision that really happened instead of an inferred story. Passing paths as
  plain coordinates still produces no such event.
- Trace the face walk (`region.face_walk`, stage `construction`):
  `RegionRenderResult.face_walk` and the new `region.face_walk` event describe how
  the regions were produced. The Boolean backend records its weave and skip steps
  per crossing (with `under`, `over`, `lens_area`, `removed_area` or a `reason`)
  plus `cut_count`, `section_cut_count`, `missing_assignment_count`,
  `self_crossing_count`, `empty_band_count`, `lens_miss_count`, `hole_count` and
  `region_polygon_count`. The arrangement backend records every cell's ownership
  decision (`single` / `lens` / `conflicting-lens` / `off-crossing` / `uncovered`)
  and every dropped sliver, plus `raw_face_count`, `face_count`,
  `collapsed_count`, `subtraction_count`, `single_owner_count`,
  `lens_decided_count`, `conflicting_count`, `off_crossing_count`,
  `uncovered_count` and `sliver_count`. Both use the same key scheme for
  `backend`, `node_kind`, `node_count`, `band_count`, `section_count`,
  `crossing_count`, `owner_count`, `congested` and `removed_area`, so the same
  input can be compared across backends (`_cells` now returns its walk stats).
- `Lace.build_animation(mode="algorithm"/"debug")` overlays a short read-out of
  those events (real node counts, split counts, deepest level, backend and owner
  count); `overview`, `construction` and `custom` stay quiet about them.
- Add `examples/scene_weave.py::SamplingTraceDemo`, which samples a curve through
  `Lace.from_parametric` and shows the fine-grained read-out.
- Docs: `docs/ALGORITHM_TRACE.md` documents both payloads (including what is still
  aggregated, i.e. the refinement iterations), `docs/ROADMAP.md` closes M5,
  `README.md` gains a "fine-grained events" example.
- Tests: `tests/test_trace_payloads.py` (bounded payloads, subdivision counters
  and identities, depth cap, singularity drops, jump splits, the event in the
  trace and its JSON round-trip, both face-walk payloads and the backend
  comparison) plus two Manim-facing assertions in `tests/test_optional_manim.py`.

## Unreleased — aesthetic policies (M6 done)

- Add the `manim_lace.style` package (M6), renderer-neutral and decoration-only:
  palettes, grouping, borders, cut-end treatments and density-aware
  simplification.
- Add `style/palette.py`: a 56-colour card of traditional Japanese colours
  (name, kana reading, hex) plus seven named palettes (`haru` 春, `natsu` 夏,
  `aki` 秋, `fuyu` 冬, `matsuri` 祭, `wabi` 侘, `ayame` 菖蒲) with Chinese/romaji/
  English aliases and a `register_palette` hook for plugins. Palettes are ordered
  dark → light so the paper-like colour comes last and cycling hands out the
  visible colours first. `strand_colors` supports `cycle`, `even` and `shuffle`
  (`shuffle` takes a seed, so a random palette stays reproducible, SPEC FR-063).
  The swatch values are public traditional Japanese colour names; the grouping
  into palettes is inspired by Teruko Sakurai's *Japanese Color Harmony
  Dictionary*, whose own swatch pages and combinations are not reproduced.
  `render/palettes.py` (the earlier stub) is now a re-export shim.
- Add `style/grouping.py` and `style/policy.py`: `build_groups` partitions the
  visible geometry by `path`, `piece`, `layer` or `degree`, and `StylePolicy` +
  `apply_style` resolve that into a `StylePlan` with one `StyleAssignment` per
  piece/region. Styling is provably decorative: tests freeze crossings,
  assignments and piece coordinates across four different policies (SPEC FR-062,
  AT-018). A draw order that is not the geometry layer's own is reported as
  `STYLE-DRAW-ORDER-OVERRIDE` rather than applied silently.
- Add `style/border.py`: `BorderSpec`/`build_border` frame the *visible* geometry
  (cut-away pieces do not enlarge it) with `square`/`round`/`bevel` corners,
  concentric bands, an inset and a palette colour index. Rings are closed and
  counter-clockwise; a frame that would land inside the pattern, or a corner
  radius that does not fit, raises `ValueError` instead of being approximated.
- Add cut-end treatments: the stroke backend accepts `cover_allowance`, which
  shortens every under-pass cut by `cover_allowance * offset` per side so the
  lower strand tucks under the upper one (`RENDER-COVER-ALLOWANCE`; ribbon mode
  reports `RENDER-COVER-ALLOWANCE-IGNORED`). The allowance may only eat slack the
  cut already has, so `0 <= cover_allowance <= overshoot` is validated in
  `LaceEngine` construction and in `render_stroke_geometry`. `style/caps.py` adds
  `stroke_piece_outline`: the real paint polygon of a piece (butt/square/round
  caps, miter joins with a limit, and the hole ring of an uncut closed
  centerline), so the end shape is checked geometry instead of a renderer
  assumption. `CapTreatment` bundles cap style, allowance and arc sampling.
- Add `style/density.py`: `analyze_density` measures crowding (grid cell counts,
  hotspots, and connected clusters of crossings within a scale-derived radius),
  and `simplify_for_density` hides visible slivers shorter than the threshold
  *inside a dense cluster only*. Crossings, assignments and `result.pieces` are
  untouched; hidden piece IDs, the threshold and the cluster scale go into
  `RENDER-DENSITY-SIMPLIFIED`, the region backend reports
  `RENDER-DENSITY-SKIPPED` instead of quietly doing nothing, and a sparse pattern
  emits no diagnostic at all.
- Wire the policies into the Manim facade: `Lace` now accepts `palette`,
  `style_policy`, `border`, `border_color`, `paper`, `density_policy` and
  `cover_allowance`, colours every piece/region from the plan, draws the paper
  rectangle behind the weave (z-index -1) and the frame around it (stroke width
  `100 × BorderSpec.thickness`, the same world-unit convention as the
  `200 * offset` strand heuristic), and keeps `result.pieces` as the honest,
  un-simplified geometry while `lace.density` reports what was hidden.
  `palette` and `style_policy` are mutually exclusive.
- Export the M6 API from the package root (`PALETTES`, `Palette`, `get_palette`,
  `get_swatch`, `palette_names`, `register_palette`, `StylePolicy`, `StylePlan`,
  `StyleGroup`, `build_groups`, `apply_style`, `BorderSpec`, `build_border`,
  `CapTreatment`, `stroke_piece_outline`, `DensityPolicy`, `analyze_density`,
  `simplify_for_density`).
- Add `examples/scene_style.py` with `PaletteGallery`, `BorderGallery`,
  `CutEndGallery` (including the drawn piece outlines) and `DensityGallery`.
- Tests: `tests/test_style_palette.py`, `tests/test_style_policy.py`,
  `tests/test_style_geometry.py` and `tests/test_optional_style_manim.py`
  (95 new tests, 336 total).

## Unreleased — M1 + M5 done, gallery scenes, Manim CE 0.22.0 only

- Add `render/pixels.py` with `px_to_stroke_width`, `stroke_width_to_px`, and
  `px_to_units`: converts between desired output-pixel thickness and Manim's
  frame-relative `stroke_width`, so a caller can say "2 pixel thick lines" and
  get the right `stroke_width` for 480p/720p/1080p output. The formula is
  `pixel_thickness ≈ 0.01 × stroke_width × (pixel_height / frame_height)`, and
  the inverse undoes it exactly. Preset constants (`FRAME_HEIGHT_*`,
  `PIXEL_HEIGHT_*`) cover the standard Manim quality levels. The `Lace` facade
  gains `stroke_width_px`, `pixel_height`, and `frame_height` parameters: when
  `stroke_width_px` is given it overrides `stroke_width` through the converter,
  so the visual thickness is correct regardless of the frame or resolution. This
  closes the last M1 bullet ("pixel-aligned stroke widths").
- Add fine-grained trace events (M5): the engine now records every candidate
  pair that survived the bounding-box rejection and entered the exact segment
  test, and every constraint-propagation step (seed, propagate, reject) from the
  topology solver. Two new trace event types appear in `result.trace`:
  `crossing.candidate_pairs` (with `pair_count`, `hit_count`, and a per-pair
  `status` list) and `topology.propagation` (with `seed_count`,
  `propagation_count`, `rejection_count`, and a per-step `kind` list). Both are
  emitted only when there is data to report, so existing traces that had no
  crossings or used `free`/`manual` mode are unchanged.
- Add `verify_coordinate_consistency` (`animation/verify.py`, M5): checks that
  every crossing ID in the trace's `crossing.detected` events matches a crossing
  in `result.crossings`, and that the point recorded in the trace data matches
  the crossing's canonical point to within tolerance. Returns a
  `CoordConsistency` report with `consistent`, `crossing_ids_in_trace`,
  `crossing_ids_in_result`, and a `mismatches` list. This verifies the M5
  milestone item "animation highlights are at the same coordinates and IDs as
  final geometry."
- Make the animation plan configurable (M5): `build_animation_plan` now accepts
  `durations` and `stage_modes` keyword arguments to override per-stage durations
  and mode membership without editing the source. The defaults are exported as
  `DEFAULT_STAGE_DURATIONS` and `DEFAULT_STAGE_MODES` (both dicts) from
  `manim_lace.animation` and the package root. The previous signature
  (`build_animation_plan(result, mode)`) still works unchanged.
- Make the Manim adapter respect plan durations (M5 done): `Lace.build_animation`
  now accepts `durations` and `stage_modes` parameters (forwarded to
  `build_animation_plan`) and derives every animation's `run_time` from the
  plan's per-stage duration instead of using hardcoded values. The previous
  signature (`build_animation(mode)`) still works unchanged. Tests verify that
  custom durations propagate to the first animation, that stage-mode overrides
  change the total succession length, and that `custom` mode ignores overrides.
- Export `px_to_stroke_width`, `px_to_units`, `stroke_width_to_px`,
  `TraceCollector`, `ANIMATION_MODES`, `DEFAULT_STAGE_DURATIONS`,
  `DEFAULT_STAGE_MODES` from the package `__all__`. Add `render/pixels.py` to
  the `render` package exports.
- Add 9 new ribbon-backend gallery scenes to `examples/scene_gallery.py`
  (CircleLine / SineLine / Trefoil / Star / Spiral / Grid / Cross / Infinity
  / Chain). All use a white background with black ribbons and holes — the
  canonical "lace on paper" look. The original 3 demonstration scenes
  (CapStyleGallery, DrawOrderGallery, RibbonGallery) keep their colourful
  styles unchanged.
- Add a static gallery page that showcases the 9 lace patterns in a responsive
  grid layout, with per-tile Chinese descriptions, a click-to-zoom lightbox and a
  footer showing the render command. It is generated by
  `examples/build_gallery.py` (see the top section) into `media/gallery/`, next to
  the PNGs it references, so the repository never accumulates untracked renders.
- Drop support for Manim CE `0.19`–`0.21`. The project now targets only
  Manim CE `0.22.0`; `pyproject.toml` pins `manim==0.22.0` and the M1 version
  matrix item is closed as out of scope.

## Unreleased — planar-arrangement region backend and the backend comparison (M4 done)

- Add the second region implementation, `ribbon_backend='arrangement'`
  (`render/arrangement.py`, SPEC FR-054's "planar embedding or verified boolean
  algorithms"): all ribbon boundaries — band rings *plus* the section boundaries that put a
  real edge through a self-crossing overlap — are noded with GEOS and turned into faces with
  `polygonize` (nested faces are reduced so an annulus stays an annulus), and every face is
  assigned exactly one owner: the single covering strand, or the strand the local crossing
  says is on top, or the deterministic path order where geometry cannot decide.
- Properties this backend adds, each asserted in `tests/test_arrangement.py`: regions never
  overlap (`region_area_sum == painted_area`), `painted_area == union_area` even when several
  crossings share one point, a self-crossing needs no overlapping sections, and no painter
  order is needed for visibility (the layer numbers stay as `draw_index` for renderers).
- What it cannot compute from geometry is reported instead of smoothed over:
  `REGION-CONFLICTING-OVERLAP` (one face inside crossings with contradictory assignments,
  typically coincident crossings), `REGION-OFF-CROSSING-OVERLAP` (parallel strands with no
  crossing nearby), `REGION-DROPPED-SLIVER` (near-tangent face fragments, with count and
  area) and `REGION-LENS-APPROXIMATION` (a self-crossing whose local window is too short to
  contain its overlap, checked against the analytic `4 * offset^2 / sin(theta)`).
- Engine knob `ribbon_backend` (`boolean`, the default, or `arrangement`), validated at
  construction, with the public `RibbonBackend` type and a pass-through in the Manim facade.
  `build_bands` / `build_sections` are now shared helpers so "the ribbon" means the same
  thing in both backends.
- The comparison the milestone asked for: on ordinary crossings the backends agree exactly
  (same painted area, same hidden area, same region area sum, for circle × line and a
  three-line chain), and they differ exactly where the Boolean model has to approximate — a
  self-crossing shows hidden area `0` there (overlapping sections instead) against the
  analytic lens in the arrangement, and coincident crossings lose coverage only in the
  Boolean one. Both are kept on purpose; the tests pin the agreement *and* the differences.

## Unreleased — self-crossings in the region backend (M4)

- Weave self-crossings in `render_mode='ribbon'`. A path that crosses itself is cut into
  sections at its two passes (`_StripBuilder`, flat caps at interior splits, the configured
  cap at real path ends) and emitted as separate overlapping regions: the crossing is then
  resolved by the painter order instead of by cutting area, because removing the overlap
  from one band is a no-op when both passes are that same band. This is the same strategy
  the stroke backend uses, now shared: `render/order.py::paint_order` (moved out of
  `stroke.py`) computes the order for both backends from the same assignments.
- `RibbonRegion` gains `draw_index` and `RegionRenderResult` gains `ordered_regions()`,
  `painted_area` and `region_area_sum`. The invariant is now `painted_area == union_area`
  (the union of the visible regions equals the ribbon that was built); the plain sum is
  larger wherever sections of one self-crossing path overlap, which is by design and
  reported as `REGION-OVERLAPPING-SECTIONS` (info). `covered_area` remains as an alias of
  `painted_area`, and the Manim facade paints regions in `draw_index` order with a matching
  `z_index`.
- Report the situations this model cannot make exact instead of smoothing them over: a
  cyclic over/under relation with sections becomes `REGION-DRAW-ORDER-CYCLE` (info), a
  split that lands on a polyline vertex makes the sections tile slightly less than the band
  (`REGION-SECTION-SEAM`, info), and several crossings on one point make the per-crossing
  removals cancel each other out (`REGION-COINCIDENT-CROSSINGS` warning plus the existing
  `REGION-AREA-MISMATCH` with the difference and tolerance). `REGION-SELF-CROSSING-UNSUPPORTED`
  is gone: self-crossings are woven now, and the honest limits that remain are named.
- Extend `tests/test_regions.py`: a self-crossing path is emitted as overlapping ordered
  sections with `region_area_sum > painted_area` and unchanged coverage, the paint order
  puts the under pass before the over pass (probing both passes' material), and coincident
  crossings are reported with the mismatch they cause.

## Unreleased — area-based ribbon regions (M4)

- Implement the region backend (SPEC FR-052, FR-053, FR-054, FR-055, FR-057, FR-058):
  `render_mode='ribbon'` builds one offset band per path with a validated Boolean engine
  (Shapely, the optional `geometry` extra) and, at every woven crossing, removes from the
  under band the Boolean intersection with the over band **restricted to the component that
  contains the crossing point**. That component is the exact footprint of the over ribbon,
  so there is no radius heuristic, no shallow-angle clamp and no cap compensation.
  Intersecting the bands as whole geometries would have cut the under ribbon at every
  crossing the two paths share; `tests/test_regions.py` catches that through the area
  invariant.
- `render_mode='ribbon'` no longer raises `NotImplementedError`. `LaceResult.pieces` holds
  `RibbonRegion` objects: an exterior ring plus hole rings tagged `exterior`,
  `source_contour` (an interior contour the source shape already had) or `occlusion` (a gap
  the weave created), exteriors counter-clockwise and holes clockwise, with `area`,
  `removed_area`, `band_area` and `union_area` next to them for checking (FR-059).
- Validate instead of guessing (FR-055, FR-057, FR-058): a zero-length path reports
  `REGION-EMPTY-RIBBON`, an invalid offset outline is repaired through `make_valid` and
  reported as `REGION-INVALID-OUTLINE`, a crossing without an assignment reports
  `REGION-MISSING-ASSIGNMENT`, three or more ribbons overlapping away from a crossing
  reports `REGION-AREA-MISMATCH` with the difference and tolerance, and a self-crossing —
  whose two passes share one band — reports `REGION-SELF-CROSSING-UNSUPPORTED` instead of
  silently staying unwoven.
- Add `join` (`miter`/`bevel`/`round`) and `miter_limit` to the engine for the offset
  outline (FR-053), the public `JoinStyle` type, and `cap_style` now selects real cap
  geometry in this backend.
- Manim facade: `render='ribbon'` builds filled regions plus a separate hole layer
  (`Lace.holes`, `hole_color`, `draw_holes`) because Manim has no even-odd fill, and the
  three construction paths (`__init__`, `from_parametric`, `from_graph`) now share one
  `_attach_rendered` / `_from_engine` pair instead of duplicating the block. Unknown
  `render` values raise `ValueError` instead of `NotImplementedError`.
- Trace: `region.polygon` (area, ring counts, hole roles) and `region.accounting`
  (band/removed/union/covered areas) join the construction stage, so the area invariant is
  visible in the algorithm trace.
- Add `RibbonGallery` to `examples/scene_gallery.py` (stroke next to ribbon for the same
  input) and document the backend contract in `docs/ARCHITECTURE.md` and the README.
- Move `shapely` into the `dev` extra so CI actually exercises the region backend instead
  of skipping `tests/test_regions.py`.

## Unreleased — stroke cap policy, draw order and regression pair (M3)

- Every `StrokePiece` now carries a deterministic `draw_index`. The renderer layers the
  paths with a longest-path layering of the "under before over" relation, so a piece of an
  under path always precedes the pieces of the paths over it, and breaks a cyclic relation
  deterministically (path order). A cyclic relation is the normal case for two strands that
  cross an even number of times and is resolved by the cuts, so it is only reported as the
  new `RENDER-DRAW-ORDER-CYCLE` (info) where one of its cuts is a clamped shallow-angle
  approximation, which is the only place paint order hides the approximation.
  `StrokeRenderResult.ordered_pieces()` / `.draw_order` expose the order.
- Add the `cap_style` knob (`butt` default, `round`, `square`, validated at construction).
  `round` and `square` caps paint half the ribbon width past the centerline endpoint, so the
  cut gap is widened by `offset` and the new `RENDER-CAP-EXTENSION` (info) diagnostic says
  so; `butt` keeps the previous geometry exactly.
- The Manim facade applies both facts: ribbons are built in `draw_index` order, each one
  gets the matching `CapStyleType` and a repeated `z_index`, and the duplicated ribbon
  construction in `__init__` / `from_parametric` / `from_graph` is now one helper.
- Add `manim_lace.benchmarks.piece_digest` plus `tests/test_stroke.py` coverage for the cap
  geometry, the ordering invariant, the cycle reporting rule, determinism, the trace records
  and a frozen `piece_digest` golden for two standard inputs — the headless stand-in for a
  visual regression baseline, since CI does not render. `tests/test_optional_manim.py`
  checks the Manim-side cap style, `z_index` and piece geometry.
- Add `examples/scene_gallery.py` with `CapStyleGallery` (butt/round/square comparison) and
  `DrawOrderGallery` (pieces created in painter order, printing the diagnostics and the
  piece digest), both rendered on Manim CE 0.22.0.
- Add `.vscode/` and `.idea/` to `.gitignore`.

## Unreleased — event policies and conflict strategies (M2)

- Add `EventPolicy` (engine knob `event_policy`, public `manim_lace.EventPolicy`): the
  detector's handling of candidates that are not plain transverse crossings is now an
  explicit, validated choice per event class. `diagnose` (default) keeps the class and its
  warning, `weave` promotes a point-like contact (`endpoint_touch`, `near_tangent`) into
  the over/under solver and records the original class in a new `GEOM-CONTACT-WOVEN` info
  diagnostic, `ignore` keeps the geometry and classification but drops the warning. A
  collinear overlap and a multiway node only accept the latter two values, because neither
  has a single binary over/under decision. `event_policy` accepts an `EventPolicy`, a
  partial mapping such as `{"endpoint_touch": "weave"}`, a single value for every field, or
  `None`, and is normalised (and validated) at engine construction.
- Report minimal conflict witnesses instead of the whole conflicting component:
  `TOPOLOGY-ALTERNATION-UNSAT` (and the new `TOPOLOGY-ALTERNATION-RELAXED`) now carry
  `details["witnesses"]`, one per conflict — the shortest alternative path closing an odd
  cycle, or a self-crossing whose two passes share a parity — and `details["crossing_ids"]`
  is the union of those witnesses. `details["relaxed_crossing_ids"]` lists the crossings
  that actually received a relaxed assignment, which can be a strict subset because
  breaking one edge of a cycle suffices.
- Add the FR-045 conflict strategy switch (`conflict_strategy`, engine and `solve_weave`):
  `error` (default) keeps refusing to fabricate a solution, `manual` turns the user's over
  sides into hard parity constraints and relaxes the automatic constraints that contradict
  them, `relax` keeps the automatic solution and relaxes what has to give. Both relaxing
  strategies assign every transverse crossing, mark relaxed ones with the new
  `WeaveAssignment.source='relaxed'`, prefer the user's side when one was requested, and
  report `TOPOLOGY-ALTERNATION-RELAXED`. Two contradicting manual sides on one path are
  reported as the new `TOPOLOGY-MANUAL-CONFLICT` warning, keeping the smaller crossing ID.
  Manual overrides otherwise keep their documented precedence, and
  `TOPOLOGY-MANUAL-OVERRIDE` is now emitted only when the user's side actually disagreed
  with the automatic solution instead of for every manual crossing.
- Add `tests/test_event_policy.py` (policy matrix, validation shapes, an end-to-end
  promoted T-junction that is actually cut, and which path of a promoted contact gets
  trimmed) and `tests/test_conflict_strategy.py` (witness minimality, self-crossing
  witnesses, all three strategies, determinism and JSON-safe diagnostic details).

## Unreleased — statically visible lazy Manim facade

- Make `manim_lace.Lace` readable by static tools instead of only by a runtime
  `__all__.append`: `__init__` now declares the complete `__all__` literal, imports `Lace`
  under `TYPE_CHECKING` for checkers and IDEs, and only *removes* the name from `__all__`
  when `find_spec("manim")` says the optional dependency is missing, so
  `from manim_lace import *` keeps working without Manim. Runtime laziness (PEP 562
  `__getattr__`) is unchanged, `__dir__` now reports the facade whenever it is available,
  and a missing or unfindable Manim always yields the `pip install 'manim-lace[manim]'`
  hint while a genuine import failure with Manim installed surfaces unchanged.
- Add `tests/test_package_api.py` to freeze the namespace contract, including both
  no-Manim subprocess paths and the guarantee that importing the package never imports
  Manim.

## Unreleased — intersection refinement on the source curve

- Add adaptive local crossing refinement (SPEC FR-036, `geometry/refine.py`): a raw hit
  whose two paths both expose an evaluable source curve (`PolylinePath.curve`) and the
  source parameter mapping is re-solved with a damped Newton iteration on
  `gamma_a(t) - gamma_b(u) = 0`, bounded to the parameter window that produced the hit.
  `CrossingEvent` gains `refined`, `parameter_a` and `parameter_b`; refined events also
  carry a curve-accurate arc length and an angle sine computed from the true local
  tangents instead of the chord pair. `LaceEngine(..., refine=False)` and
  `detect_crossings(..., refine=False)` restore the sampled-polyline result exactly, and
  `CrossingStats.refined_events` plus the `crossing.candidates` / `crossing.detected`
  trace records report what was refined and where.
- Keep the samplers' source curve: `sample_parametric` / `sample_graph` store the
  evaluator on the path they emit (also across `jump_threshold` splits), and the Manim
  adapter builds a piecewise cubic Bezier evaluator over the `curve_index + local_t`
  parameter it already records, so real VMobject crossings refine as well.
- Refinement is fail-open and fail-honest: a missing probe or parameter mapping, a probe
  that raises or returns non-finite values, a non-convergent iteration, a solution that
  jumps outside the candidate's local window, or a path that genuinely kinks at the
  crossing all leave the sampled estimate in place. At a real corner the chord pair stays
  the reported angle, because no single local tangent exists there.
- State the refinement contract in `README.md`, `docs/ARCHITECTURE.md` and
  `docs/ALGORITHM_TRACE.md`; freeze it with `tests/test_refine.py` (analytic accuracy,
  vertex-angle replacement, corner refusal, fallbacks, determinism, engine wiring) and
  extend `tests/test_optional_manim.py` to cover the Bezier probe on real Manim data.
  Events on paths without a probe are byte-identical to before, which the frozen
  benchmark digests still assert.

## Unreleased — candidate indexing and benchmark set

- Add a deterministic uniform-grid candidate index (`geometry/index.py`) and
  separate candidate enumeration from the exact segment test. `grid` prunes;
  `brute_force` checks every pair. Both report identical events, diagnostics and
  piece geometry, which the tests assert scenario by scenario (SPEC FR-035).
- Report candidate pruning through `CrossingStats` (`LaceEngine(..., detection_stats)`,
  `CrossingDetectionResult.stats`) and a `crossing.candidates` trace event with
  strategy, segment, candidate and narrow-phase counters.
- Replace the O(crossings²) multiway clustering scan with bucketed neighbourhood
  clustering. Semantics are unchanged — verified against the previous O(n²)
  formulation on randomized point sets — while a 286-crossing fan drops from
  ~76 ms to ~7 ms. Also remove the unused O(n²) `adjacency` map that was built and
  never read.
- Add `min_piece_length`-style configurability for candidate enumeration:
  `candidate_strategy` on `LaceEngine` and `Lace`.
- Add a reproducible benchmark set (`manim_lace.benchmarks`, covering the four
  SPEC §10.2 input classes) plus `benchmarks/bench_crossings.py`, which times
  detection, compares grid against brute force and prints a stable event digest.
  `make bench` runs it; CI now lints the `benchmarks/` directory too.
- Use the benchmark to drive one more fix: the narrow-phase bounding-box
  rejection now compares scalar values instead of NumPy scalars. Dense curves
  drop from ~15 ms to ~4.5 ms and the reference strategy from ~190 ms to ~12.5 ms,
  with event digests unchanged.
- Validate every `LaceEngine` knob at construction (`position_tol`, `angle_tol`,
  `min_sin`, `overshoot`, `weave_mode`, `manual_over`) instead of failing halfway
  through `solve()`, and reject unknown `build_animation(mode=...)` values instead
  of silently returning an empty animation.
- Sync `README.md` with shipped behaviour: candidate strategy and
  `detection_stats`, stroke piece invariants, the diagnostic-code table, and the
  measured Manim CE 0.22.0 render of `examples/scene_weave.py` (which replaces the
  outdated "Manim is not installed here" caveat).

## Unreleased — crossing stability and stroke boundaries

- Fix stroke geometry when a cut wraps the seam of a closed path: the visible arc
  is now split into one `piece-seam` plus the remaining piece instead of emitting a
  full-length duplicate that covered the cut.
- Fix stroke geometry for an open path whose cut covers the whole centerline: report
  `RENDER-PATH-FULLY-CUT` instead of emitting a phantom seam piece.
- Keep the local branch rays of a curve position when a path repeats a vertex, so a
  genuine vertex crossing is no longer demoted to `endpoint_touch` and dropped from
  strict alternation.
- Report `GEOM-DEGENERATE-PATH` for zero-length paths instead of emitting an empty
  stroke piece; report `RENDER-PIECE-DROPPED` for visible arcs shorter than
  `min_piece_length`, which is now configurable on `LaceEngine` and `Lace`.
- Validate `overshoot` and `min_piece_length`, and document the piece invariants
  (disjoint arc intervals, never longer than the path).
- Add boundary regression tests: T-junctions, vertex crossings with repeated
  points, closed-path seams, self-crossing arc order, run-to-run determinism,
  degenerate paths, seam-wrapping cuts, fully cut open paths, shallow-angle cuts
  and dropped pieces.
- Make `ruff check src tests examples` clean, including the missing `DOWN`/`LEFT`
  imports in the optional Manim facade.

## 0.1.0 — Starter kit

- Establish pure NumPy 2D path model and optional Manim adapter.
- Add adaptive sampling for explicit graph and parametric curve sources.
- Add polyline crossing events, self-crossing support, special-event diagnostics, and deterministic over/under solvers.
- Add centerline stroke-piece construction and algorithm trace records.
- Add optional Manim facade and algorithm-oriented animation scaffolding.
- Mark the area-based Ribbon renderer as unimplemented rather than emulating it with an unreliable graph-cycle heuristic.
