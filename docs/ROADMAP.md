# Development roadmap

Markers: `[x]` done and covered by tests, `[~]` partially done, `[ ]` not started.
Last reviewed 2026-10-15 against the state of `main` after the crossing, stroke-boundary,
candidate-index, intersection-refinement, event-policy, conflict-strategy, stroke
cap/order and region-backend work.

## Where we are

- **M0 done.**
- **M1 in progress** — 5 of 6 bullets done, 1 partial (Manim CE version matrix).
  FR-036 intersection refinement is done for inputs whose source curve is evaluable.
- **M2 done** — event policies, minimal conflict witnesses and the FR-045 conflict
  strategy switch are implemented and tested.
- **M3 done** — seam handling, dropped-geometry diagnostics, stated limitations, cap
  policy, draw dependency order and the renderable/geometry regression pair.
- **M4 in progress** — 2 of 3 bullets done: the Shapely region backend ships behind
  `render_mode='ribbon'` with tagged faces/holes and validated area conservation; the
  half-edge comparison and per-pass bands for self-crossings are open.
- **M5 partially scaffolded**, **M6 not started**.
- Next in line: finish M4 (self-crossing bands, half-edge comparison) → M5 fine-grained
  traces and verified animation coordinates.

## M0 — Starter kit (done)
- Core data model, graph/parametric samplers, line-segment crossing detector.
- Alternating/free/manual assignment modes.
- Stroke polyline cutting, trace records, optional Manim facade.
- Unit tests and example scenes.

## M1 — Input and crossing correctness
- [~] Test current Manim CE VMobject layouts across supported versions: the adapter
      and a full scene render pass on Manim CE `0.22.0`
      (`tests/test_optional_manim.py`, `examples/scene_weave.py`); the declared
      `0.19`–`0.22` range is still untested.
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
      switch `conflict_strategy` (engine and `solve_weave`) selects `error` (default:
      report the witnesses and return no assignment), `manual` (the user's over sides
      become hard constraints and the automatic ones that contradict them are
      relaxed) or `relax` (keep the automatic solution and relax what has to give).
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
- [~] Prototype Shapely-based Boolean regions vs a dedicated half-edge arrangement: the
      Shapely prototype is implemented (`render/regions.py`, `render_mode='ribbon'`, the
      optional `geometry` extra). Each path becomes one offset band; at every woven
      crossing the under band loses the exact Boolean intersection with the over band
      *local to that crossing* (component containing the crossing point), so no radius,
      no shallow-angle clamp and no cap compensation is involved. Self-crossings are
      reported as unsupported (`REGION-SELF-CROSSING-UNSUPPORTED`) because their two
      passes share one band, and a crossing without an assignment reports
      `REGION-MISSING-ASSIGNMENT`; neither is silently un-woven. A half-edge/planar
      arrangement comparison has not been started.
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
- [~] Trace adaptive subdivision, candidate pairs, event classifications,
  constraints, and face walks: candidate evaluation is recorded as aggregate
  counters only (`crossing.candidates`); subdivision decisions, individual
  candidate pairs and face walks are not traced.
- [~] Add inspectable stage objects and fine-grained duration/visibility controls:
  `AnimationStage` objects and the five plan modes exist, but durations and stage
  membership are hardcoded in `animation/plan.py`.
- [ ] Verify animation highlights are at the same coordinates and IDs as final geometry.

## M6 — Aesthetic policies
- [ ] Pluggable palettes, path/piece grouping, border design, cut-end treatments, and density-aware visual simplification.
