# Contributing

1. Keep geometry and topology independent from Manim imports.
2. Every new diagnostic needs a stable code and a test.
3. Every crossing change should be covered by a minimal numeric test case.
4. Do not silently close, merge, or drop paths without a configurable policy and diagnostic.
5. Do not infer crossing identity from offset boundaries.
6. Do not use a graph cycle basis as a substitute for planar face extraction.
7. Animation events must refer to IDs and coordinates produced by the solver.
8. Run `pytest` and (when installed) `ruff check src tests` before sending a PR.

When an algorithm returns an approximation, label it as approximation in API docs and diagnostics.
