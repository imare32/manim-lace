"""The benchmark input set is reproducible and its results are frozen (SPEC §10.2/§10.3)."""

import numpy as np

from manim_lace import LaceEngine
from manim_lace.benchmarks import SCENARIO_CLASSES, event_digest, scenario_names, scenarios
from manim_lace.geometry.intersections import detect_crossings

#: Golden digests. They change only when crossing geometry legitimately changes,
#: so an unexpected diff here is a signal, not noise.
GOLDEN_DIGESTS = {
    "simple": "11b968e3d73b7dfb8af48527f9e1f176d598bf31",  # 9 crossings
    "dense_smooth": "20398e1e88ca05ae7701cd67da41e643992ea82f",  # 2 crossings
    "self_intersecting": "e12ac7be9b4d8d4ae5acaba8243315eecf2c297d",  # 32 crossings
    "path_network": "097e5dccf04ea6bfb8815cd79307b44e616f1de6",  # 196 crossings
}


def test_scenario_set_covers_the_spec_classes():
    assert set(SCENARIO_CLASSES) == {
        "simple",
        "dense_smooth",
        "self_intersecting",
        "path_network",
    }
    assert scenario_names() == list(SCENARIO_CLASSES)
    assert set(scenarios()) == set(GOLDEN_DIGESTS)


def test_scenarios_are_reproducible_across_calls():
    first, second = scenarios(), scenarios()
    for name in scenario_names():
        assert len(first[name]) == len(second[name])
        for left, right in zip(first[name], second[name], strict=True):
            assert left.path_id == right.path_id
            assert left.closed == right.closed
            assert np.array_equal(left.points, right.points)


def test_scenario_digests_are_frozen():
    built = scenarios()
    for name in scenario_names():
        result = detect_crossings(built[name])
        assert result.crossings, name
        assert event_digest(result.crossings) == GOLDEN_DIGESTS[name], name


def test_scenarios_survive_the_full_pipeline():
    for name, paths in scenarios().items():
        result = LaceEngine(paths, offset=0.05, weave_mode="free").solve()
        assert result.crossings
        assert result.pieces
        assert result.detection_stats is not None
        assert result.detection_stats.candidate_pairs < result.detection_stats.all_pairs
        assert all(np.isfinite(piece.points).all() for piece in result.pieces)
