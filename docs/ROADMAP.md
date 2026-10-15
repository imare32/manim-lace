# Development roadmap

## M0 — Starter kit (current)
- Core data model, graph/parametric samplers, line-segment crossing detector.
- Alternating/free/manual assignment modes.
- Stroke polyline cutting, trace records, optional Manim facade.
- Unit tests and example scenes.

## M1 — Input and crossing correctness
- Test current Manim CE VMobject layouts across supported versions.
- Add source-parameter-aware curves and adaptive intersection refinement.
- Strengthen event clustering at polyline vertices and closed-path seams.
- Add a deterministic spatial index and performance benchmarks.

## M2 — Weave topology robustness
- Add explicit endpoint and multiway event policies.
- Implement constraint explanation paths / minimal conflict sets.
- Make manual override precedence and strictness settings explicit.

## M3 — Production stroke renderer
- Correct cyclic interval handling around closed-path seams.
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
