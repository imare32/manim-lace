# Changelog

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
