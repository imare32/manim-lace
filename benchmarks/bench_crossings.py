"""Timing and equivalence harness for the crossing detector (SPEC §10.2).

Run from the repository root::

    python benchmarks/bench_crossings.py

For every scenario in :mod:`manim_lace.benchmarks` this script

1. runs detection with the pruned grid candidate index,
2. optionally re-runs the same geometry with the brute-force strategy and fails
   loudly if the two disagree (an optimisation must never change the result),
3. prints segment counts, candidate pruning, timings and a stable event digest.

Timings are wall-clock and therefore machine dependent; the digests are not.
Use ``--repeat`` to take the best of several runs on a noisy machine.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from manim_lace.benchmarks import event_digest, scenario_names, scenarios
from manim_lace.geometry.intersections import detect_crossings

DEFAULT_MAX_BRUTE_PAIRS = 60_000


@dataclass(slots=True)
class Row:
    name: str
    paths: int
    segments: int
    crossings: int
    candidate_pairs: int
    all_pairs: int
    detect_ms: float
    brute_ms: float | None
    digest: str
    matches: bool | None


def _best_ms(callable_, repeat: int) -> float:
    timings = []
    for _ in range(repeat):
        start = time.perf_counter()
        callable_()
        timings.append((time.perf_counter() - start) * 1000.0)
    return min(timings)


def measure(
    name: str,
    paths,
    *,
    repeat: int,
    max_brute_pairs: int,
    position_tol: float,
) -> Row:
    gridded = detect_crossings(paths, position_tol=position_tol, candidate_strategy="grid")
    stats = gridded.stats
    assert stats is not None
    detect_ms = _best_ms(
        lambda: detect_crossings(paths, position_tol=position_tol, candidate_strategy="grid"),
        repeat,
    )
    brute_ms: float | None = None
    matches: bool | None = None
    if stats.all_pairs <= max_brute_pairs:
        reference = detect_crossings(
            paths, position_tol=position_tol, candidate_strategy="brute_force"
        )
        matches = _signature(gridded.crossings) == _signature(reference.crossings)
        brute_ms = _best_ms(
            lambda: detect_crossings(
                paths, position_tol=position_tol, candidate_strategy="brute_force"
            ),
            repeat,
        )
    return Row(
        name=name,
        paths=len(paths),
        segments=stats.segment_count,
        crossings=len(gridded.crossings),
        candidate_pairs=stats.candidate_pairs,
        all_pairs=stats.all_pairs,
        detect_ms=detect_ms,
        brute_ms=brute_ms,
        digest=event_digest(gridded.crossings),
        matches=matches,
    )


def _signature(crossings):
    return [
        (
            event.crossing_id,
            event.kind,
            event.point,
            event.s_a,
            event.s_b,
            event.segment_a,
            event.segment_b,
            event.u_a,
            event.u_b,
            event.sin_angle,
        )
        for event in crossings
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1, help="best-of-N timing runs")
    parser.add_argument(
        "--max-brute-pairs",
        type=int,
        default=DEFAULT_MAX_BRUTE_PAIRS,
        help="only run the reference strategy below this pair count",
    )
    parser.add_argument("--position-tol", type=float, default=1e-7)
    args = parser.parse_args()

    built = scenarios()
    rows = [
        measure(
            name,
            built[name],
            repeat=max(1, args.repeat),
            max_brute_pairs=args.max_brute_pairs,
            position_tol=args.position_tol,
        )
        for name in scenario_names()
    ]

    header = (
        f"{'scenario':18s} {'paths':>5s} {'segs':>6s} {'cross':>6s} "
        f"{'candidates/all':>16s} {'detect_ms':>9s} {'brute_ms':>9s}  digest"
    )
    print(header)
    print("-" * len(header))
    mismatches = []
    for row in rows:
        brute = "n/a" if row.brute_ms is None else f"{row.brute_ms:9.2f}"
        flag = ""
        if row.matches is False:
            flag = "  <-- MISMATCH"
            mismatches.append(row.name)
        elif row.matches is True:
            flag = "  (=)"
        print(
            f"{row.name:18s} {row.paths:5d} {row.segments:6d} {row.crossings:6d} "
            f"{row.candidate_pairs:7d}/{row.all_pairs:<7d} {row.detect_ms:9.2f} {brute:>9s}  "
            f"{row.digest[:16]}{flag}"
        )
    if mismatches:
        print(f"\nFAILED: grid and brute force disagree on {', '.join(mismatches)}")
        return 1
    print("\nOK: grid and brute force agree wherever the reference strategy ran.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
