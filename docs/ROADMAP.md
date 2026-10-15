# Development roadmap

Markers: `[x]` done and covered by tests, `[~]` partially done, `[ ]` not started.
Last reviewed 2026-10-15 against the state of `main` after the crossing, stroke-boundary
and candidate-index work.

## Where we are

- **M0 done.**
- **M1 in progress** — 4 of 6 bullets done, 1 partial (Manim CE version matrix),
  1 open (FR-036 intersection refinement).
- **M3 started early** — 3 of 4 bullets done. The stroke backend boundaries were pulled
  forward on request, so M3 runs ahead of the still-unstarted M2.
- **M2 is all-partial** (events are diagnosed but not policy-controlled, conflicts are
  reported but not minimised), **M4 not started**, **M5 partially scaffolded**,
  **M6 not started**.
- Next in line: FR-036 intersection refinement (M1) → M2 event policies → M3 caps and
  draw order → M4 region backend.

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
- [ ] Add adaptive intersection refinement on the source curve (FR-036): crossings
      are still computed on the sampled polyline, and a vertex crossing takes its
      angle from the segment pair rather than the true local tangents.
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
- [~] Add explicit endpoint and multiway event policies: endpoint contacts,
  near-tangents and multiway nodes are classified and reported, but there is no
  user-facing policy knob for them yet.
- [~] Implement constraint explanation paths / minimal conflict sets:
  `TOPOLOGY-ALTERNATION-UNSAT` lists the conflicting crossings and path pairs, but
  the reported set is not minimised.
- [~] Make manual override precedence and strictness settings explicit: a manual
  assignment wins over the alternating solver and emits `TOPOLOGY-MANUAL-OVERRIDE`;
  the FR-045 conflict-strategy switch does not exist yet.

## M3 — Production stroke renderer
- [x] Correct cyclic interval handling around closed-path seams: a cut that wraps
      the seam emits one `piece-seam` plus the remaining arc, an open path whose
      cut reaches both ends emits no piece and reports `RENDER-PATH-FULLY-CUT`,
      and pieces of one path never overlap in arc space (`tests/test_stroke.py`).
- [x] Report dropped geometry (`RENDER-PIECE-DROPPED`, `RENDER-MISSING-ASSIGNMENT`)
      instead of silently shortening the centerline.
- [ ] Add draw dependency order, round/butt/square cap policy, and visual regression examples.
- [x] State limitations for alpha compositing and shallow-angle crossings
      (`README.md` 重要语义 and the numeric assumptions in `docs/ARCHITECTURE.md`).

## M4 — Region renderer
- [ ] Prototype Shapely-based Boolean regions vs a dedicated half-edge arrangement.
- [ ] Define faces and holes independently of rendering fill rules.
- [ ] Validate polygon boundaries, intersections, and area conservation.

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
