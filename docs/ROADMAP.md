# Development roadmap

## M0 — Starter kit (current)
- Core data model, graph/parametric samplers, line-segment crossing detector.
- Alternating/free/manual assignment modes.
- Stroke polyline cutting, trace records, optional Manim facade.
- Unit tests and example scenes.

## M1 — Input and crossing correctness
- Test current Manim CE VMobject layouts across supported versions.
- Add source-parameter-aware curves and adaptive intersection refinement.
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
- Add explicit endpoint and multiway event policies.
- Implement constraint explanation paths / minimal conflict sets.
- Make manual override precedence and strictness settings explicit.

## M3 — Production stroke renderer
- [x] Correct cyclic interval handling around closed-path seams: a cut that wraps
      the seam emits one `piece-seam` plus the remaining arc, an open path whose
      cut reaches both ends emits no piece and reports `RENDER-PATH-FULLY-CUT`,
      and pieces of one path never overlap in arc space (`tests/test_stroke.py`).
- [x] Report dropped geometry (`RENDER-PIECE-DROPPED`, `RENDER-MISSING-ASSIGNMENT`)
      instead of silently shortening the centerline.
- Add draw dependency order, round/butt/square cap policy, and visual regression examples.
- State limitations for alpha compositing and shallow-angle crossings.

## M4 — Region renderer
- Prototype Shapely-based Boolean regions vs a dedicated half-edge arrangement.
- Define faces and holes independently of rendering fill rules.
- Validate polygon boundaries, intersections, and area conservation.

## M5 — Algorithm animation
- Trace adaptive subdivision, candidate pairs, event classifications, constraints, and face walks.
- Add inspectable stage objects and fine-grained duration/visibility controls.
- Verify animation highlights are at the same coordinates and IDs as final geometry.

## M6 — Aesthetic policies
- Pluggable palettes, path/piece grouping, border design, cut-end treatments, and density-aware visual simplification.
