# Development roadmap

Markers: `[x]` done and covered by tests, `[~]` partially done, `[ ]` not started.
Last reviewed 2026-10-15 against the state of `main` after the pixel-aligned stroke
width, fine-grained trace, coordinate consistency check, configurable animation
plan and aesthetic-policy work.

## Where we are

- **M0 done.**
- **M1 done** — all six bullets complete. Pixel-aligned stroke widths are
  implemented (`render/pixels.py`, `px_to_stroke_width` / `px_to_units` /
  `stroke_width_to_px`, integrated into the `Lace` facade via
  `stroke_width_px`). FR-036 intersection refinement is done for inputs whose
  source curve is evaluable. The Manim CE adapter is tested against the single
  supported version `0.22.0` (older versions `0.19`–`0.21` are out of scope).
- **M2 done** — event policies, minimal conflict witnesses and the FR-045 conflict
  strategy switch are implemented and tested.
- **M3 done** — seam handling, dropped-geometry diagnostics, stated limitations, cap
  policy, draw dependency order and the renderable/geometry regression pair.
- **M4 done** — all three bullets: the Boolean region backend with tagged faces/holes and
  validated area conservation, the planar-arrangement backend, and the comparison between
  them (including what each one reports instead of approximating).
- **M5 done** — every fine-grained trace is emitted: candidate pairs
  (`crossing.candidate_pairs`), constraint propagation (`topology.propagation`),
  adaptive subdivision (`sampling.subdivision`) and face walks (`region.face_walk`);
  animation coordinates and IDs are verified against final
  geometry; animation plan durations and stage membership are configurable,
  including in the Manim adapter (`Lace.build_animation` now accepts
  `durations` and `stage_modes` and uses plan stage durations instead of
  hardcoded `run_time` values) and `algorithm`/`debug` mode overlays the real
  subdivision and face-walk numbers.
- **M6 done** — palettes, path/piece grouping, border design, cut-end treatments
  and density-aware visual simplification all ship behind
  `manim_lace.style`, and the Manim facade consumes them.
- Next in line: the performance/API-hardening items listed in `README.md`
  (index construction cost, refinement coverage for paths without a source
  curve) and the arrangement backend's half-edge exposure.

## M0 — Starter kit (done)
- Core data model, graph/parametric samplers, line-segment crossing detector.
- Alternating/free/manual assignment modes.
- Stroke polyline cutting, trace records, optional Manim facade.
- Unit tests and example scenes.

## M1 — Input and crossing correctness
- [x] Test current Manim CE VMobject layouts on the supported version: the adapter
      and a full scene render pass on Manim CE `0.22.0`
      (`tests/test_optional_manim.py`, `examples/scene_weave.py`). Older CE
      versions (`0.19`–`0.21`) are out of scope.
- [x] Pixel-aligned stroke-width conversion: `render/pixels.py` provides
      `px_to_stroke_width`, `stroke_width_to_px` and `px_to_units` that convert
      between desired output-pixel thickness and Manim's frame-relative
      `stroke_width`. The `Lace` facade accepts `stroke_width_px`,
      `pixel_height`, and `frame_height`; when `stroke_width_px` is set it
      overrides the heuristic `max(1.0, 200.0 * offset)`. Tests cover the
      conversion, round-trip, and all quality presets (`tests/test_pixels.py`).
- [x] Map sampled points back to source parameters (`PolylinePath.parameters`,
      preserved across breakpoint splits in `geometry/sampling.py`).
- [x] Add adaptive intersection refinement on the source curve (FR-036): when both
      paths expose an evaluable source curve (`PolylinePath.curve`, filled in by
      `sample_parametric`, `sample_graph` and the Manim Bezier adapter) plus the
      source parameter mapping, each hit is re-solved with a damped Newton iteration
      on `gamma_a(t) - gamma_b(u) = 0`, restricted to the parameter window that
      produced it. Refined events carry the source parameters, the curve arc length
      and an angle sine from the true local tangents. It is fail-open and
      fail-honest: no probe, a probe that raises or returns non-finite values, a
      non-convergent iteration, a solution outside the local window, or a path that
      genuinely kinks at the crossing all keep the chord estimate.
      `tests/test_refine.py` covers the analytic accuracy gain, the vertex-angle
      replacement, the corner refusal, the fallbacks and determinism;
      `tests/test_optional_manim.py` covers the Bezier probe on real Manim data.
- [x] Strengthen event clustering at polyline vertices and closed-path seams:
      vertex crossings on interior segments and with repeated points stay
      `transverse`, a crossing at a closed seam is reported once at arc 0, and a
      zero-length path is reported as `GEOM-DEGENERATE-PATH` instead of being
      silently ignored. Regression tests live in `tests/test_crossings.py`.
- [x] Add a deterministic spatial index and performance benchmarks: a uniform
      grid over expanded segment boxes prunes candidates, results are asserted to
      be identical to the brute-force strategy, and `manim_lace.benchmarks` plus
      `benchmarks/bench_crossings.py` cover the four input classes of SPEC §10.2.
- [x] Act on what the benchmark measured: the per-pair bounding-box rejection now
      runs on scalar values instead of NumPy scalars, which cut the dense-curve
      scenario from ~15 ms to ~4.5 ms and the reference strategy from ~190 ms to
      ~12.5 ms. Remaining work here: candidate index construction and per-segment
      bookkeeping, plus crossing refinement for sampled curves (FR-036).

## M2 — Weave topology robustness
- [x] Add explicit endpoint and multiway event policies: `EventPolicy` (engine knob
      `event_policy`, accepting an object, a partial mapping or one value for every
      field) decides per event class whether a candidate is kept as a diagnosed fact
      (default), promoted into the over/under solver (`weave`, point-like contacts
      only, reported through `GEOM-CONTACT-WOVEN`) or kept without its warning
      (`ignore`). An overlap is an interval and a multiway node has more than two
      strands, so those two classes can only be diagnosed or ignored. Diagnosis keeps
      every event in `result.crossings`; the policy never deletes geometry.
      `tests/test_event_policy.py` covers the policy matrix, the validation paths and
      an end-to-end promoted T-junction that is actually cut.
- [x] Implement constraint explanation paths / minimal conflict sets:
      `TOPOLOGY-ALTERNATION-UNSAT` and `TOPOLOGY-ALTERNATION-RELAXED` report one
      witness per conflict — the shortest alternative path that closes an odd cycle,
      or a self-crossing whose two passes share a parity — and `crossing_ids` is now
      the union of those witnesses instead of every crossing in the conflicting
      component.
- [x] Make manual override precedence and strictness settings explicit: the FR-045
      switch `conflict_strategy` (engine and `solve_weave`) selects `relax` (default:
      keep the automatic solution and relax only what has to give, so the default
      weaves as far as the geometry allows), `error` (report the witnesses and return
      no assignment, for callers that must not accept an approximation) or `manual`
      (the user's over sides become hard constraints and the automatic ones that
      contradict them are relaxed).
      Both relaxing strategies mark every relaxed crossing with `source='relaxed'`
      and report `TOPOLOGY-ALTERNATION-RELAXED`; manual sides stay authoritative as
      before (`TOPOLOGY-MANUAL-OVERRIDE`), and two contradicting manual sides on one
      path are now reported as `TOPOLOGY-MANUAL-CONFLICT`.
      `tests/test_conflict_strategy.py` freezes witnesses, strategies, determinism
      and JSON-safe diagnostic details.

## M3 — Production stroke renderer
- [x] Correct cyclic interval handling around closed-path seams: a cut that wraps
      the seam emits one `piece-seam` plus the remaining arc, an open path whose
      cut reaches both ends emits no piece and reports `RENDER-PATH-FULLY-CUT`,
      and pieces of one path never overlap in arc space (`tests/test_stroke.py`).
- [x] Report dropped geometry (`RENDER-PIECE-DROPPED`, `RENDER-MISSING-ASSIGNMENT`)
      instead of silently shortening the centerline.
- [x] Add draw dependency order, round/butt/square cap policy, and visual regression
      examples. Every piece now carries a deterministic `draw_index` computed from the
      over/under assignments (an under path is always painted before the paths over it,
      with cycles broken deterministically), `cap_style` selects `butt` (the cut stops
      exactly at the gap) or `round`/`square` (the paint protrudes half the ribbon width,
      so the gap is widened by `offset` and `RENDER-CAP-EXTENSION` says so), and the Manim
      facade applies the matching `CapStyleType` plus `z_index`. `examples/scene_gallery.py`
      renders the cap comparison and the painter order, while `tests/test_stroke.py` freezes
      the piece geometry through `manim_lace.benchmarks.piece_digest` (the headless stand-in
      for a pixel baseline, since CI has no renderer) and asserts the ordering invariant.
- [x] State limitations for alpha compositing and shallow-angle crossings
      (`README.md` 重要语义 and the numeric assumptions in `docs/ARCHITECTURE.md`).

## M4 — Region renderer
- [x] Prototype Shapely-based Boolean regions vs a dedicated half-edge arrangement: both
      implementations ship behind `ribbon_backend` (`render_mode='ribbon'`, the optional
      `geometry` extra) and are compared by `tests/test_arrangement.py`.
      The Boolean one (`render/regions.py`) cuts the exact crossing-local intersection out
      of the under band, and cuts self-crossing paths into section pairs whose overlapping
      regions are resolved by the painter order (`render/order.py::paint_order`, shared with
      the stroke backend). It reports what it cannot express:
      `REGION-OVERLAPPING-SECTIONS`, `REGION-COINCIDENT-CROSSINGS` +
      `REGION-AREA-MISMATCH`, `REGION-SECTION-SEAM`, `REGION-MISSING-ASSIGNMENT`.
      The arrangement one (`render/arrangement.py`) nodes all ribbon boundaries (band rings
      plus the section boundaries that put a real edge through a self-crossing overlap),
      extracts faces with `polygonize`, and gives every face exactly one owner, so regions
      never overlap (`region_area_sum == painted_area`) and coverage stays exact even for
      coincident crossings. What it cannot decide from geometry is reported:
      `REGION-CONFLICTING-OVERLAP`, `REGION-OFF-CROSSING-OVERLAP`,
      `REGION-DROPPED-SLIVER`, `REGION-LENS-APPROXIMATION`.
      The comparison result: identical painted/hidden areas on ordinary crossings, and
      disagreement exactly where the Boolean model approximates (self-crossing hidden area
      `0` vs the analytic lens; coincident crossings lose coverage only in the Boolean one).
- [x] Define faces and holes independently of rendering fill rules: `RibbonRegion` holds
      an exterior ring plus tagged hole rings (`exterior` / `source_contour` /
      `occlusion`), exteriors counter-clockwise and holes clockwise; the Manim facade
      paints holes as its own layer because Manim has no even-odd fill, and the geometry
      layer never depends on that choice.
- [x] Validate polygon boundaries, intersections, and area conservation: tests assert
      every ring is closed, simple and valid, that the removed area equals the Boolean
      lens (no radius heuristic), and that the visible areas sum to the union of the
      bands, with `REGION-AREA-MISMATCH` when three or more ribbons overlap off-crossing.

## M5 — Algorithm animation
- [x] Trace adaptive subdivision, candidate pairs, event classifications,
  constraints, and face walks: candidate pairs are traced individually
  (`crossing.candidate_pairs` with per-pair `status`), constraint
  propagation steps are traced (`topology.propagation` with `seed`/`propagate`/
  `reject` steps), the adaptive sampler reports every subdivision decision it took
  (`sampling.subdivision`: per-curve counters plus a bounded list of
  split/accept/depth-cap/drop decisions, handed to the engine through
  `LaceEngine(..., sampling_trace=...)`), and both region backends report the
  traversal that produced their regions (`region.face_walk`: the boolean backend's
  weave/cut/skip steps per crossing, the arrangement backend's per-face ownership
  decisions, plus comparable counters). Payloads are bounded
  (`manim_lace.tracing`) so the counters stay exact while the record lists cannot
  grow with the input; see `docs/ALGORITHM_TRACE.md`. What is still aggregated is
  listed there under "What is not recorded yet" (the refinement iterations).
- [x] Add inspectable stage objects and fine-grained duration/visibility controls:
  `AnimationStage` objects and the five plan modes exist,
  `build_animation_plan` accepts `durations` and `stage_modes` overrides
  (with defaults exported as `DEFAULT_STAGE_DURATIONS` / `DEFAULT_STAGE_MODES`),
  and the Manim adapter `Lace.build_animation` forwards the same parameters and
  derives every animation's `run_time` from the plan's per-stage durations.
- [x] Verify animation highlights are at the same coordinates and IDs as final
  geometry: `verify_coordinate_consistency` (`animation/verify.py`) checks that
  every crossing ID in the trace matches one in `result.crossings` and that the
  traced point matches the canonical point within tolerance.

## M6 — Aesthetic policies
- [x] Pluggable palettes: `style/palette.py` holds a card of 56 traditional
      Japanese colours (name, reading, hex) and seven named palettes (`haru`,
      `natsu`, `aki`, `fuyu`, `matsuri`, `wabi`, `ayame`) with zh/romaji/English
      aliases, a `register_palette` hook, and `strand_colors` with `cycle` /
      `even` / `shuffle` modes (`shuffle` takes a seed, SPEC FR-063). The grouping
      of the swatches into palettes is inspired by Teruko Sakurai's *Japanese
      Color Harmony Dictionary*; the swatch values are the public traditional
      names, and the book's own pages are not reproduced. Palettes are ordered
      dark → light so the paper-like colour comes last and cycling hands out the
      visible colours first. `render/palettes.py` stays as a re-export shim.
- [x] Path/piece grouping and style policies: `style/grouping.py` builds colour
      groups by `path` (the classic one colour per strand, empty paths kept so the
      mapping cannot shift), `piece`, `layer` (equal buckets of the painter order)
      or `degree` (busiest strand first); `style/policy.py` turns a `StylePolicy`
      into a `StylePlan` with one `StyleAssignment` per visible piece.
      `apply_style` is decorative only: `tests/test_style_policy.py` freezes the
      crossings, assignments and piece geometry across four different policies
      (SPEC FR-062 / AT-018). A draw order that is not the geometry's own is
      reported as `STYLE-DRAW-ORDER-OVERRIDE` instead of being applied silently.
- [x] Border design: `style/border.py` builds a frame from the *visible*
      geometry's bounding box (so cut-away pieces do not enlarge it), with
      `square`/`round`/`bevel` corners, concentric bands, an inset, and a palette
      colour index. Every ring is closed and counter-clockwise, and a frame that
      would land inside the pattern or a corner radius that does not fit is
      rejected rather than approximated.
- [x] Cut-end treatments: the stroke backend takes `cover_allowance`, which
      shortens every under-pass cut by `cover_allowance * offset` on each side so
      the lower strand tucks further under the upper one (`RENDER-COVER-ALLOWANCE`,
      `RENDER-COVER-ALLOWANCE-IGNORED` in ribbon mode). It may only eat the slack
      the cut already has, so `cover_allowance <= overshoot` is validated at
      construction. `style/caps.py` also exposes the real paint outline of a piece
      (butt / square / round caps, miter joins), including the hole ring of an
      uncut closed centerline, so the end shape is checked geometry rather than an
      assumption about the renderer.
- [x] Density-aware visual simplification: `style/density.py` measures the
      crowding (`analyze_density`: grid cell counts, hotspots, and connected
      clusters of crossings) and then, only inside a dense cluster, hides visible
      slivers shorter than the policy threshold. Crossings, assignments and the
      engine's pieces are untouched; the hidden piece IDs and the threshold are
      listed in `RENDER-DENSITY-SIMPLIFIED`, the region backend reports
      `RENDER-DENSITY-SKIPPED` instead of quietly doing nothing, and a sparse
      pattern produces no diagnostic at all.
- [x] The Manim facade takes the same policies: `Lace(..., palette=...,
      style_policy=..., border=..., border_color=..., paper=..., density_policy=...,
      )` colours each piece/region from the plan, puts the paper rectangle behind
      the weave and the frame around it, and keeps `result.pieces` as the honest,
      un-simplified geometry. `examples/scene_style.py` renders the palettes, the
      frames, the cut-end treatments and the density comparison.
