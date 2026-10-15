# Changelog

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
