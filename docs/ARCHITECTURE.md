# Architecture Notes

## Data pipeline

`Manim adapter or direct mathematical sampler -> PolylinePath -> CrossingEvent + Pass -> WeaveTopology -> StrokePiece/Region -> Manim renderer`

The topology layer must not depend on either rendering backend. In particular, crossing identity comes from centerline events, not from offset-rail intersections.

## Stable responsibilities

- `PolylinePath`: ordered 2D coordinates, stable ID, closed state, source metadata, optional source parameters, and an optional source-curve probe.
- `CrossingEvent`: both path identities, both arc-length positions, point, crossing kind, segment references, angle sine, and — for refined events — the source-curve parameters and a `refined` flag.
- `Pass`: one visit in a path's crossing sequence; self-crossings produce two passes on the same path.
- `WeaveTopology`: pass order, over/under assignments, conflict diagnostics.
- `WeaveAssignment`: the over/under decision for one crossing plus its provenance (`alternating`, `manual`, `free` or `relaxed`), so a reader can tell a strict alternating weave from a user override and from a relaxed conflict.
- `StrokePiece`: geometry-only result; no Manim object in the core. It carries its own arc interval and `draw_index`, so ordering decisions never live in the adapter.
- `TraceEvent`: factual data emitted by the pipeline and later consumed by animation code.

## Optional dependency contract

The core never imports Manim. `manim_lace.Lace` is a lazy module attribute (PEP 562):
`__init__` lists it in the static `__all__` literal and imports it under `TYPE_CHECKING`,
so static checkers and IDEs resolve the name, while the runtime decides with
`find_spec("manim")` — without importing Manim — whether `__all__` keeps it (dropping it
keeps `from manim_lace import *` working on an installation without the extra). The first
real access goes through `__getattr__`, which raises the `pip install 'manim-lace[manim]'`
hint when Manim cannot be found and otherwise lets a genuine import failure surface
unchanged. `__dir__` follows the same rule, and `tests/test_package_api.py` freezes the
contract including both no-Manim paths.

## Crossing refinement (`geometry/refine.py`, SPEC FR-036)

Candidates are still found between sampled straight segments. For each hit whose two
paths both carry an evaluable source curve and a source parameter mapping, the detector
re-solves the crossing with a damped Newton iteration on `F(t, u) = gamma_a(t) -
gamma_b(u) = 0`, starting from the chord solution and bounded to the parameter window
that produced the hit.

- The derivative comes from central differences whose step is a thousandth of the local
  sample spacing, so accuracy is tied to the sampling, not to absolute world units.
- Refined arc lengths stay on the polyline's own cumulative length scale: the cumulative
  value at the local sample plus the Gauss-Legendre length of the curve inside that
  segment. Closed paths are reduced modulo the path length.
- Acceptance requires the residual to be inside `position_tol`, the solution to stay
  inside the local window (twice the local sample spacing), and the source curve to be
  smooth there: a turn above `MAX_LOCAL_TURN` between the two one-sided tangents means a
  real kink, where no single tangent exists and the chord estimate is kept.
- Everything else — missing probe, missing parameters, raising or non-finite probe,
  non-convergence, a jump outside the window — returns `None` and leaves the sampled
  estimate untouched. Refinement never adds, removes or reclassifies an event on its
  own; only the angle test of the classification sees the refined angle.

## Region backend (`render/regions.py`, SPEC FR-052..FR-058)

The area backend is the second consumer of `WeaveTopology` and proves the topology layer
is renderer-neutral (FR-040). It needs the optional `geometry` extra (Shapely) and is
imported lazily, so `render_mode='ribbon'` raises an `ImportError` with the install hint
instead of breaking the core import.

- One offset band per path (`LineString.buffer` with the configured cap/join strategy and
  miter limit) is the ribbon area.
- At each woven crossing between two paths the *under* band loses the Boolean intersection
  with the *over* band, restricted to the connected component that contains the crossing
  point. That component is the exact local footprint of the over ribbon: no radius, no
  shallow-angle clamp, no cap compensation. Intersecting the whole bands instead would cut
  the under ribbon at every crossing the two paths share, which the area test catches.
- A self-crossing cannot be expressed that way: both passes are the same band, and a band
  cannot be over and under itself. Such a path is therefore cut into *sections* at its two
  passes (`_StripBuilder`), emitted as separate overlapping regions, and the crossing is
  resolved by the painter order: `RibbonRegion.draw_index` puts the sections of the under
  pass before the sections of the over pass. This is the same "order covers the crossing"
  strategy the stroke backend uses, and it is disclosed through
  `REGION-OVERLAPPING-SECTIONS` (the area sum is then larger than the painted area).
- The order itself comes from `render/order.py::paint_order`, shared with the stroke
  backend, so both backends derive the painter sequence from the same assignments. A
  cyclic relation is broken deterministically and reported (`REGION-DRAW-ORDER-CYCLE`
  when sections are involved, `RENDER-DRAW-ORDER-CYCLE` when a clamped cut is).
- `RibbonRegion` exposes an exterior ring plus hole rings, each tagged `exterior`,
  `source_contour` (an interior contour the source shape already had) or `occlusion` (a
  gap the weave created), with exteriors counter-clockwise and holes clockwise. Faces and
  holes are therefore defined by geometry, not by a fill rule or ring size (FR-058).
- Validation is explicit and the accounting is checkable: an invalid offset outline is
  repaired through `make_valid` and reported as `REGION-INVALID-OUTLINE`; a zero-length
  path reports `REGION-EMPTY-RIBBON`; a section that does not tile the band (a split on a
  polyline vertex) reports `REGION-SECTION-SEAM`; a crossing without an assignment reports
  `REGION-MISSING-ASSIGNMENT`. The invariant is `painted_area == union_area` (the union of
  the visible regions equals the ribbon that was built), with `region_area_sum` exposed
  separately because sections of one self-crossing path overlap by design.
- Known limit, reported rather than hidden: when several crossings land on the *same*
  point (three strands at one spot), each crossing removes the overlap it sees and the
  removals cancel out, so coverage is no longer conserved. That is reported as
  `REGION-COINCIDENT-CROSSINGS` together with `REGION-AREA-MISMATCH`, rather than being
  smoothed over. A planar arrangement with per-face strand labels is the principled fix
  and is the remaining M4 item.
- Manim has no even-odd fill, so the facade paints hole rings as its own layer
  (`Lace.holes`) with `hole_color`, and paints regions in `draw_index` order with a
  matching `z_index`; the geometry result is independent of both choices.

## Event policy and conflict strategy

Two decisions are deliberately explicit instead of implicit (SPEC FR-032, FR-042, FR-045):

- **Event policy** (`EventPolicy`, engine knob `event_policy`). Candidates that are not
  plain transverse crossings stay in `result.crossings` no matter what: the policy only
  decides the classification and the diagnostic. `diagnose` (default) keeps the detected
  class and warns; `weave` promotes a *point-like* contact (`endpoint_touch`,
  `near_tangent`) to `transverse` so it enters the over/under solver, and records the
  original class in `GEOM-CONTACT-WOVEN`; `ignore` keeps the class and drops the warning.
  A collinear overlap is an interval and a multiway node has more than two strands, so
  neither has a single binary over/under decision and both only accept `diagnose`/`ignore`.
- **Conflict strategy** (`conflict_strategy`, engine and `solve_weave`). It only applies to
  `alternating` mode and only when the parity system has no solution. `error` (default)
  returns no assignment at all and reports the witnesses; `manual` seeds the propagation
  from the user's over sides (which become hard constraints) and relaxes the automatic
  constraints that contradict them; `relax` keeps the automatic solution and relaxes what
  has to give. Both relaxing strategies mark every relaxed crossing with
  `source='relaxed'` and report `TOPOLOGY-ALTERNATION-RELAXED`. A relaxed crossing takes a
  deterministic side (`a` over, or the user's side when one was given); improving that
  choice is a known follow-up, not a hidden behaviour.
- **Conflict witnesses** are minimal on purpose: for a rejected parity constraint the
  witness is the shortest alternative path between its two paths — a cycle of crossing IDs —
  and for a self-crossing whose two passes share a parity it is that single crossing.
  `details["crossing_ids"]` is the union of the witnesses (what the user should change),
  while `details["relaxed_crossing_ids"]` is the (smaller) set that actually got relaxed,
  because breaking any single edge of a witness cycle is enough.

## Numeric assumptions in v0.1

1. Current intersection computation is between sampled straight segments, not exact Bezier curves. The only exception is the local refinement above, which applies where a path exposes a source curve and is explicitly reported per event through `CrossingEvent.refined`.
2. Candidate enumeration is pluggable: `candidate_strategy="grid"` uses a deterministic
   uniform grid over segment boxes expanded by `position_tol`, `"brute_force"` checks
   every pair. Both are asserted to yield identical events, diagnostics and pieces;
   the grid only reduces the number of exact tests. A sweep line or BVH can replace it
   behind the same seam.
3. Crossings classified as endpoint-touch or near-tangent are retained as diagnostics, but not sent to strict alternating assignment unless the event policy promotes them (`weave`).
4. Collinear overlap is diagnostic-only; no automatic crossing relationship is invented, and the event policy can only silence the warning.
5. Stroke cutting is a visual approximation. It cannot ensure exact area coverage around every shallow-angle crossing, and the cut gap is widened by `offset` when the cap style protrudes.
6. The region backend computes exact areas with a Boolean engine, but the stroke backend remains an approximation: a renderer must not treat stroke pieces as an exact painted outline.

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
- Every piece carries a deterministic `draw_index`. Pieces are ordered by the
  longest-path layering of the "under before over" relation between paths, so that an
  under path is always painted before the paths it is under. A cyclic relation — the
  normal case for two strands that cross an even number of times — has no consistent
  painter order; the cuts decide visibility, and the cycle is only reported
  (`RENDER-DRAW-ORDER-CYCLE`, info) where one of its cuts is a clamped shallow-angle
  approximation, because that is where paint order actively hides the approximation.
- `cap_style` keeps the geometry honest about what the renderer will paint: `butt` ends
  exactly at the gap, while `round` and `square` protrude half the ribbon width along the
  tangent, so the gap is widened by `offset` and `RENDER-CAP-EXTENSION` (info) says so.
  The cap outline itself is not modelled; it is a property of the stroke renderer.
- The Manim facade consumes those two facts: it builds the ribbon VGroup in
  `draw_index` order, sets the matching `CapStyleType` and repeats the order as
  `z_index`, so a Manim render cannot disagree with the geometry layer.

## Suggested extension contracts

A future `CrossingDetector` implementation should return `CrossingDetectionResult`, preserving `CrossingEvent` semantics. Any ribbon renderer must consume `WeaveTopology` instead of recomputing assignments (the Shapely backend above is the reference implementation). Every renderer should report diagnostics for dropped pieces or geometric repair.

Anything that changes *which* pairs are examined must keep the reported events
identical; `candidate_strategy="brute_force"` is the reference oracle for that, and
`manim_lace.benchmarks.event_digest` plus the golden values in
`tests/test_benchmarks.py` freeze the observable output per input class.

A future detailed trace should record the same IDs used by final geometry. Trace events are not permitted to fabricate geometry for pedagogical reasons.
