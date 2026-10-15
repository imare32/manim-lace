# Architecture Notes

## Data pipeline

`Manim adapter or direct mathematical sampler -> PolylinePath -> CrossingEvent + Pass -> WeaveTopology -> StrokePiece/Region -> Manim renderer`

The topology layer must not depend on either rendering backend. In particular, crossing identity comes from centerline events, not from offset-rail intersections.

## Stable responsibilities

- `PolylinePath`: ordered 2D coordinates, stable ID, closed state, source metadata, optional source parameters.
- `CrossingEvent`: both path identities, both arc-length positions, point, crossing kind, segment references, and angle sine.
- `Pass`: one visit in a path's crossing sequence; self-crossings produce two passes on the same path.
- `WeaveTopology`: pass order, over/under assignments, conflict diagnostics.
- `StrokePiece`: geometry-only result; no Manim object in the core.
- `TraceEvent`: factual data emitted by the pipeline and later consumed by animation code.

## Numeric assumptions in v0.1

1. Current intersection computation is between sampled straight segments, not exact Bezier curves.
2. It uses deterministic all-pairs segment candidate checks. Replace candidate enumeration with a sweep line, uniform grid, or BVH after profiling.
3. Crossings classified as endpoint-touch or near-tangent are retained as diagnostics, but not sent to strict alternating assignment.
4. Collinear overlap is diagnostic-only; no automatic crossing relationship is invented.
5. Stroke cutting is a visual approximation. It cannot ensure exact area coverage around every shallow-angle crossing.
6. Region rendering is deliberately not implemented yet.

## Renderer guarantees (v0.1 stroke backend)

These are asserted by tests, not just intentions:

- Pieces of one path never overlap in arc space and are never longer than the path.
- A cut that wraps a closed seam becomes one `piece-seam` (covering
  `[last_start, length] U [0, first_end]`) plus the remaining visible arc. An open
  path whose cut reaches both ends yields no piece and a `RENDER-PATH-FULLY-CUT`
  diagnostic, because an open path has no seam to weave around.
- Geometry is never dropped silently: `GEOM-DEGENERATE-PATH`,
  `RENDER-PIECE-DROPPED`, `RENDER-PATH-FULLY-CUT` and `RENDER-MISSING-ASSIGNMENT`
  mark removed centerline arcs.

## Suggested extension contracts

A future `CrossingDetector` implementation should return `CrossingDetectionResult`, preserving `CrossingEvent` semantics. A future `RibbonRegionRenderer` must consume `WeaveTopology` instead of recomputing assignments. Every renderer should report diagnostics for dropped pieces or geometric repair.

A future detailed trace should record the same IDs used by final geometry. Trace events are not permitted to fabricate geometry for pedagogical reasons.
