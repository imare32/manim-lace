# Contributing

1. Keep geometry and topology independent from Manim imports.
2. Every new diagnostic needs a stable code and a test.
3. Every crossing change should be covered by a minimal numeric test case.
4. Do not silently close, merge, or drop paths without a configurable policy and diagnostic.
5. Do not infer crossing identity from offset boundaries.
6. Do not use a graph cycle basis as a substitute for planar face extraction.
7. Animation events must refer to IDs and coordinates produced by the solver.
8. Run `pytest` and (when installed) `ruff check src tests` before sending a PR.
9. Write down what you measured, **including the fixes that did not work** —
   `docs/DEFECT_HUNTING.md` is where that goes.

When an algorithm returns an approximation, label it as approximation in API docs and diagnostics.

`make test-fast` (`pytest -q --skip-heavy`) drops the cases that cost seconds per solve and have
nothing to do with the ribbon backends; run the full `pytest` when a change can touch crossings,
area accounting, or the implicit extractor.
