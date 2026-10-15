# Algorithm trace and animation contract

Trace events are immutable records emitted while the engine runs. They are not generated from an imagined storyboard after the fact.

## Trace event stages

| Stage | Events | Current data |
|---|---|---|
| `input` | `path.normalized` | path ID, point count, closed flag, length and estimated sampling error |
| `crossings` | `crossing.candidates` | candidate strategy, segment count, candidate pairs, narrow-phase checks, grid cells, brute-force pair count, number of events refined on the source curve |
| `crossings` | `crossing.detected` | crossing ID, kind, position, path arc lengths, angle sine, refined flag and — when refined — the source-curve parameters |
| `topology` | `crossing.assigned` | which side is over/under, source of assignment (`alternating`, `manual`, `free` or `relaxed`) and explanation |
| `construction` | `stroke.piece` | piece ID, source path, number of points, arc interval and `draw_index` (records are emitted in that order) |
| `construction` | `region.polygon` | region ID, source path, area, ring/point counts and the role of each hole (`source_contour` / `occlusion`) |
| `construction` | `region.accounting` | band area, removed area, union area and covered area of the ribbon backend, so the conservation invariant is visible |
| `diagnostics` | `diagnostic` | stable code, severity, details, hints |
| `complete` | `result.complete` | counts for paths, crossings and output pieces |

## What animation can truthfully show in v0.1

- Actual normalized paths and sample vertices.
- Actual detected crossing points and their IDs/types, plus the fact that — and where — a
  crossing was re-solved on its source curve.
- Actual solved over/under assignment for crossings with a solution, including whether it
  came from alternation, a user override, free mode or a relaxation of an unsatisfiable
  constraint.
- Actual conflict witnesses when strict alternation has no solution: the diagnostic
  `details` carry the minimal cycles (crossing IDs and paths) that make it unsatisfiable.
- Actual stroke pieces emitted by the renderer, including the painter order they are meant
  to be created in (the animation in `examples/scene_gallery.py` uses exactly that order).
- Actual ribbon regions with their areas and hole roles, plus the area accounting that says
  how much was removed and whether the visible areas still cover the band union.
- Actual diagnostics for unsupported or ambiguous cases.

## What is not recorded yet

The current sampler does not expose every recursive subdivision decision, the crossing detector records only aggregate candidate counters (`crossing.candidates`) instead of every candidate segment pair, and the future region renderer does not exist. Therefore v0.1 cannot honestly animate a complete internal search tree or face-walk algorithm. These details should be added as first-class `TraceEvent`s when the corresponding algorithms become robust, not simulated with decorative events.
