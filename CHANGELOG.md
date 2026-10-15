# Changelog

## Unreleased — stroke cap policy, draw order and regression pair (M3)

- Every `StrokePiece` now carries a deterministic `draw_index`. The renderer layers the
  paths with a longest-path layering of the "under before over" relation, so a piece of an
  under path always precedes the pieces of the paths over it, and breaks a cyclic relation
  deterministically (path order). A cyclic relation is the normal case for two strands that
  cross an even number of times and is resolved by the cuts, so it is only reported as the
  new `RENDER-DRAW-ORDER-CYCLE` (info) where one of its cuts is a clamped shallow-angle
  approximation, which is the only place paint order hides the approximation.
  `StrokeRenderResult.ordered_pieces()` / `.draw_order` expose the order.
- Add the `cap_style` knob (`butt` default, `round`, `square`, validated at construction).
  `round` and `square` caps paint half the ribbon width past the centerline endpoint, so the
  cut gap is widened by `offset` and the new `RENDER-CAP-EXTENSION` (info) diagnostic says
  so; `butt` keeps the previous geometry exactly.
- The Manim facade applies both facts: ribbons are built in `draw_index` order, each one
  gets the matching `CapStyleType` and a repeated `z_index`, and the duplicated ribbon
  construction in `__init__` / `from_parametric` / `from_graph` is now one helper.
- Add `manim_lace.benchmarks.piece_digest` plus `tests/test_stroke.py` coverage for the cap
  geometry, the ordering invariant, the cycle reporting rule, determinism, the trace records
  and a frozen `piece_digest` golden for two standard inputs — the headless stand-in for a
  visual regression baseline, since CI does not render. `tests/test_optional_manim.py`
  checks the Manim-side cap style, `z_index` and piece geometry.
- Add `examples/scene_gallery.py` with `CapStyleGallery` (butt/round/square comparison) and
  `DrawOrderGallery` (pieces created in painter order, printing the diagnostics and the
  piece digest), both rendered on Manim CE 0.22.0.
- Add `.vscode/` and `.idea/` to `.gitignore`.

## Unreleased — event policies and conflict strategies (M2)

- Add `EventPolicy` (engine knob `event_policy`, public `manim_lace.EventPolicy`): the
  detector's handling of candidates that are not plain transverse crossings is now an
  explicit, validated choice per event class. `diagnose` (default) keeps the class and its
  warning, `weave` promotes a point-like contact (`endpoint_touch`, `near_tangent`) into
  the over/under solver and records the original class in a new `GEOM-CONTACT-WOVEN` info
  diagnostic, `ignore` keeps the geometry and classification but drops the warning. A
  collinear overlap and a multiway node only accept the latter two values, because neither
  has a single binary over/under decision. `event_policy` accepts an `EventPolicy`, a
  partial mapping such as `{"endpoint_touch": "weave"}`, a single value for every field, or
  `None`, and is normalised (and validated) at engine construction.
- Report minimal conflict witnesses instead of the whole conflicting component:
  `TOPOLOGY-ALTERNATION-UNSAT` (and the new `TOPOLOGY-ALTERNATION-RELAXED`) now carry
  `details["witnesses"]`, one per conflict — the shortest alternative path closing an odd
  cycle, or a self-crossing whose two passes share a parity — and `details["crossing_ids"]`
  is the union of those witnesses. `details["relaxed_crossing_ids"]` lists the crossings
  that actually received a relaxed assignment, which can be a strict subset because
  breaking one edge of a cycle suffices.
- Add the FR-045 conflict strategy switch (`conflict_strategy`, engine and `solve_weave`):
  `error` (default) keeps refusing to fabricate a solution, `manual` turns the user's over
  sides into hard parity constraints and relaxes the automatic constraints that contradict
  them, `relax` keeps the automatic solution and relaxes what has to give. Both relaxing
  strategies assign every transverse crossing, mark relaxed ones with the new
  `WeaveAssignment.source='relaxed'`, prefer the user's side when one was requested, and
  report `TOPOLOGY-ALTERNATION-RELAXED`. Two contradicting manual sides on one path are
  reported as the new `TOPOLOGY-MANUAL-CONFLICT` warning, keeping the smaller crossing ID.
  Manual overrides otherwise keep their documented precedence, and
  `TOPOLOGY-MANUAL-OVERRIDE` is now emitted only when the user's side actually disagreed
  with the automatic solution instead of for every manual crossing.
- Add `tests/test_event_policy.py` (policy matrix, validation shapes, an end-to-end
  promoted T-junction that is actually cut, and which path of a promoted contact gets
  trimmed) and `tests/test_conflict_strategy.py` (witness minimality, self-crossing
  witnesses, all three strategies, determinism and JSON-safe diagnostic details).

## Unreleased — statically visible lazy Manim facade

- Make `manim_lace.Lace` readable by static tools instead of only by a runtime
  `__all__.append`: `__init__` now declares the complete `__all__` literal, imports `Lace`
  under `TYPE_CHECKING` for checkers and IDEs, and only *removes* the name from `__all__`
  when `find_spec("manim")` says the optional dependency is missing, so
  `from manim_lace import *` keeps working without Manim. Runtime laziness (PEP 562
  `__getattr__`) is unchanged, `__dir__` now reports the facade whenever it is available,
  and a missing or unfindable Manim always yields the `pip install 'manim-lace[manim]'`
  hint while a genuine import failure with Manim installed surfaces unchanged.
- Add `tests/test_package_api.py` to freeze the namespace contract, including both
  no-Manim subprocess paths and the guarantee that importing the package never imports
  Manim.

## Unreleased — intersection refinement on the source curve

- Add adaptive local crossing refinement (SPEC FR-036, `geometry/refine.py`): a raw hit
  whose two paths both expose an evaluable source curve (`PolylinePath.curve`) and the
  source parameter mapping is re-solved with a damped Newton iteration on
  `gamma_a(t) - gamma_b(u) = 0`, bounded to the parameter window that produced the hit.
  `CrossingEvent` gains `refined`, `parameter_a` and `parameter_b`; refined events also
  carry a curve-accurate arc length and an angle sine computed from the true local
  tangents instead of the chord pair. `LaceEngine(..., refine=False)` and
  `detect_crossings(..., refine=False)` restore the sampled-polyline result exactly, and
  `CrossingStats.refined_events` plus the `crossing.candidates` / `crossing.detected`
  trace records report what was refined and where.
- Keep the samplers' source curve: `sample_parametric` / `sample_graph` store the
  evaluator on the path they emit (also across `jump_threshold` splits), and the Manim
  adapter builds a piecewise cubic Bezier evaluator over the `curve_index + local_t`
  parameter it already records, so real VMobject crossings refine as well.
- Refinement is fail-open and fail-honest: a missing probe or parameter mapping, a probe
  that raises or returns non-finite values, a non-convergent iteration, a solution that
  jumps outside the candidate's local window, or a path that genuinely kinks at the
  crossing all leave the sampled estimate in place. At a real corner the chord pair stays
  the reported angle, because no single local tangent exists there.
- State the refinement contract in `README.md`, `docs/ARCHITECTURE.md` and
  `docs/ALGORITHM_TRACE.md`; freeze it with `tests/test_refine.py` (analytic accuracy,
  vertex-angle replacement, corner refusal, fallbacks, determinism, engine wiring) and
  extend `tests/test_optional_manim.py` to cover the Bezier probe on real Manim data.
  Events on paths without a probe are byte-identical to before, which the frozen
  benchmark digests still assert.

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
