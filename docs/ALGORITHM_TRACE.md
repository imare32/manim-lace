# Algorithm trace and animation contract

Trace events are immutable records emitted while the engine runs. They are not generated from an imagined storyboard after the fact.

## Trace event stages

| Stage | Events | Current data |
|---|---|---|
| `input` | `path.normalized` | path ID, point count, closed flag, length and estimated sampling error |
| `crossings` | `crossing.candidates` | candidate strategy, segment count, candidate pairs, narrow-phase checks, grid cells, brute-force pair count |
| `crossings` | `crossing.detected` | crossing ID, kind, position, path arc lengths, angle sine |
| `topology` | `crossing.assigned` | which side is over/under, source of assignment and explanation |
| `construction` | `stroke.piece` | piece ID, source path, number of points and arc interval |
| `diagnostics` | `diagnostic` | stable code, severity, details, hints |
| `complete` | `result.complete` | counts for paths, crossings and output pieces |

## What animation can truthfully show in v0.1

- Actual normalized paths and sample vertices.
- Actual detected crossing points and their IDs/types.
- Actual solved over/under assignment for crossings with a solution.
- Actual stroke pieces emitted by the renderer.
- Actual diagnostics for unsupported or ambiguous cases.

## What is not recorded yet

The current sampler does not expose every recursive subdivision decision, the crossing detector records only aggregate candidate counters (`crossing.candidates`) instead of every candidate segment pair, and the future region renderer does not exist. Therefore v0.1 cannot honestly animate a complete internal search tree or face-walk algorithm. These details should be added as first-class `TraceEvent`s when the corresponding algorithms become robust, not simulated with decorative events.
