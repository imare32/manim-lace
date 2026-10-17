# Algorithm trace and animation contract

Trace events are immutable records emitted while the engine runs. They are not generated from an imagined storyboard after the fact.

## Trace event stages

| Stage | Events | Current data |
|---|---|---|
| `input` | `sampling.subdivision` | one summary per sampled source curve: effective `max_error`/`max_step`/`max_depth`, exact counters (`interval_count`, `node_count`, `split_count`, `accepted_count`, `budget_capped_count`, `singular_count`, `max_depth_reached`, `dropped_interval_count`, `part_count`, `sample_count`) and a bounded `decisions` list of `{kind, reason, t0, t1, depth, error}` |
| `input` | `path.normalized` | path ID, point count, closed flag, length and estimated sampling error |
| `crossings` | `crossing.candidates` | candidate strategy, segment count, candidate pairs, narrow-phase checks, grid cells, brute-force pair count, number of events refined on the source curve |
| `crossings` | `crossing.detected` | crossing ID, kind, position, path arc lengths, angle sine, refined flag and — when refined — the source-curve parameters |
| `crossings` | `crossing.candidate_pairs` | one record per candidate pair that entered the exact test: `segment_a`, `segment_b` and `status` (`hit` / `no_hit`) |
| `topology` | `crossing.assigned` | which side is over/under, source of assignment (`alternating`, `manual`, `free` or `relaxed`) and explanation |
| `topology` | `topology.propagation` | seed, propagate and reject steps of the constraint solver, plus their counts |
| `construction` | `stroke.piece` | piece ID, source path, number of points, arc interval and `draw_index` (records are emitted in that order) |
| `construction` | `region.face_walk` | the traversal that produced the regions: `backend` (`boolean` / `arrangement`), `node_kind` (`band` / `face`), `node_count`, `band_count`, `section_count`, `crossing_count`, `owner_count`, `congested`, `removed_area`, backend-specific counters, and a bounded `steps` list |
| `construction` | `region.polygon` | region ID, source path, area, `draw_index`, ring/point counts and the role of each hole (`source_contour` / `occlusion`); records are emitted in paint order |
| `construction` | `region.accounting` | band area, removed area, union area, painted area (the invariant `painted_area == union_area`) and the plain area sum, which is larger where sections of one self-crossing path overlap |
| `diagnostics` | `diagnostic` | stable code, severity, details, hints |
| `complete` | `result.complete` | counts for paths, crossings and output pieces |

## Bounded payloads

A trace has to stay finite for any input size, so the fine-grained lists are bounded
(`manim_lace.tracing.DEFAULT_TRACE_RECORD_LIMIT`, 64 records) while the counters stay exact.
Every bounded list is emitted as three keys: `<key>` (the kept records), `<key>_count`
(how many were offered) and `<key>_truncated`. A consumer can therefore tell "there were
12" from "there were at least 12" instead of trusting a shortened list.

## Adaptive subdivision (`sampling.subdivision`)

The recorder is `_adaptive_interval` in `geometry/sampling.py`. Every recursion node ends in
exactly one of four outcomes, so `node_count == split_count + accepted_count +
budget_capped_count + singular_count`:

- `split` — the interval was halved because it was wider than `max_step` (reason
  `max_step`), because the midpoint deviated from the chord by more than `max_error`
  (`flatness`), or both (`max_step+flatness`);
- `accept` — neither bound was violated, so the interval is kept as one segment;
- `budget` — `max_depth` was reached, so a single midpoint is inserted instead of recursing
  (reported as `depth_cap+…`, never as a split that did not happen);
- `drop` — the midpoint is not finite (`not_finite`), i.e. the interval straddles a
  singularity and is omitted rather than joining two branches across it.

`max_depth_reached` and every counter are counted independently of the record list, so they
stay exact when `decisions_truncated` is true. The summary is handed over through
`sample_parametric(..., subdivision_tracer=...)`; `sample_graph` forwards it and adds
`jump_split_path_count` when the optional `jump_threshold` pass split the output afterwards.
`LaceEngine.from_parametric` / `from_graph` pass the summaries to the engine through
`sampling_trace=`, which is also the documented way to hand them over when you sampled first.

## Face walks (`region.face_walk`)

Both region backends describe the traversal that produced their regions with the same key
scheme, so traces of the same input can be compared across backends:

- boolean (`render/regions.py`): the walk visits path bands and the sections of a
  self-crossing path (`node_kind = "band"`). `steps` holds one record per woven crossing
  (`kind: "weave"` with `under`, `over`, `target`, `lens_area`, `removed_area`) or per
  crossing that could not be woven (`kind: "skip"` with a `reason`), and the payload counts
  `cut_count`, `section_cut_count`, `missing_assignment_count`, `self_crossing_count`,
  `empty_band_count`, `lens_miss_count`, `hole_count` and `region_polygon_count`. A cut band
  can break into several polygons, which is why that count is separate from `face_count` in
  the other backend. `outline_edge_count` is the number of visible weave boundaries that no
  final region exterior can carry; the facade strokes them as an explicit overlay.
- arrangement (`render/arrangement.py`): the walk visits the faces of the planar arrangement
  (`node_kind = "face"`). `steps` holds one record per cell (`kind: "face"` with `decision`
  in `single` / `lens` / `conflicting-lens` / `off-crossing` / `uncovered`, the chosen
  `owner`, `covering_count` and `area`) or per dropped sliver (`kind: "sliver"`), and the
  payload counts `raw_face_count` (faces out of `polygonize`), `face_count` (cells that got an
  owner), `collapsed_count`, `subtraction_count`, `single_owner_count`, `lens_decided_count`,
  `conflicting_count`, `off_crossing_count`, `uncovered_count`, `sliver_count` and the same
  `outline_edge_count`.

Keys shared by both: `backend`, `node_kind`, `node_count`, `band_count`, `section_count`,
`crossing_count`, `owner_count`, `congested` (the arrangement backend reports it but, unlike
the boolean one, does not resolve overlaps by paint order) and `removed_area` (the area hidden
at the crossings, computed by each backend's own method).

## What animation can truthfully show in v0.1

- Actual normalized paths and sample vertices.
- How the sampler actually subdivided the source curve, including which decisions hit the
  depth budget and which intervals were dropped at a singularity.
- Actual detected crossing points and their IDs/types, plus the fact that — and where — a
  crossing was re-solved on its source curve.
- Which candidate segment pairs were tested and which of them hit, and which constraint
  propagation steps seeded, propagated or were rejected.
- Actual solved over/under assignment for crossings with a solution, including whether it
  came from alternation, a user override, free mode or a relaxation of an unsatisfiable
  constraint.
- Actual conflict witnesses when strict alternation has no solution: the diagnostic
  `details` carry the minimal cycles (crossing IDs and paths) that make it unsatisfiable.
- Actual stroke pieces emitted by the renderer, including the painter order they are meant
  to be created in (the animation in `examples/scene_gallery.py` uses exactly that order).
- Actual ribbon regions with their areas and hole roles, plus the area accounting that says
  how much was hidden and whether the visible areas still cover the band union — identically
  for both region backends, so a trace of the same input can be compared across them.
- How each region backend walked to its result: which strand lost which area (boolean), and
  which arrangement face was attributed to which owner and why (arrangement).
- Actual diagnostics for unsupported or ambiguous cases.

`examples/scene_weave.py::SamplingTraceDemo` renders the subdivision and face-walk read-outs
in `algorithm` mode; `algorithm`/`debug` mode is where the fine-grained notes appear, and
they are only shown when the corresponding event exists.

## What is not recorded yet

- Subdivision inside the *refinement* step (`geometry/refine.py`): crossings re-solved on the
  source curve carry their final residuals (`crossing.detected` has `refined` plus the source
  parameters), but the damped-Newton iterations, backtracks and rejections are aggregated
  into `crossing.candidates.refined_events`. The iteration-level steps would be the next
  first-class events.
- Per-decision events beyond the bounded record lists: an input with a very deep recursion
  keeps its exact counters but only the first 64 decisions, and the trace says so.
- Nothing else: the remaining pipeline stages (candidate pruning, constraint propagation,
  adaptive subdivision, painter order, face attribution) all emit records produced by the
  algorithm itself, not by a post-hoc storyboard.
