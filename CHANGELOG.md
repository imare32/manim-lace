# Changelog

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
