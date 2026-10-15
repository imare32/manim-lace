import numpy as np

from manim_lace import LaceEngine, sample_graph, sample_parametric


def test_parametric_circle_sampling_is_closed_and_finite():
    paths = sample_parametric(
        lambda t: (np.cos(t), np.sin(t)), (0, 2 * np.pi),
        max_error=0.005, max_step=0.05, closed=True,
    )
    assert len(paths) == 1
    assert paths[0].closed
    assert np.allclose(paths[0].points[0], paths[0].points[-1])
    assert paths[0].parameters is not None
    assert np.isfinite(paths[0].points).all()


def test_graph_splits_at_declared_breakpoint():
    paths = sample_graph(lambda x: x, (-1, 1), breakpoints=[0], max_step=0.1)
    assert len(paths) == 2
    assert paths[0].points[-1, 0] < paths[1].points[0, 0] + 1e-12
    assert paths[0].path_id != paths[1].path_id


def test_engine_from_parametric_runs():
    engine = LaceEngine.from_parametric(
        lambda t: (np.cos(t), np.sin(t)), (0, 2 * np.pi),
        closed=True, max_step=0.05, max_error=0.003,
    )
    result = engine.solve()
    assert len(result.paths) == 1
    assert result.paths[0].closed
    assert len(result.pieces) == 1


def test_nonplanar_xyz_is_rejected_by_2d_path_model():
    import pytest

    from manim_lace import PolylinePath

    with pytest.raises(ValueError, match="XY-parallel"):
        PolylinePath(np.array([[0, 0, 0], [1, 1, 1]]))


def test_closed_path_appends_endpoint_and_parameter_mapping():
    from manim_lace import PolylinePath

    path = PolylinePath(
        np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]),
        path_id="closed",
        closed=True,
        parameters=np.array([0.0, 1.0, 2.0]),
    )
    assert len(path.points) == 4
    assert len(path.parameters) == 4
    assert np.allclose(path.points[0], path.points[-1])


def test_function_domain_errors_split_paths_without_fake_bridges():
    import math

    paths = sample_graph(math.log, (-1.0, 1.0), max_step=0.02, max_error=0.01)
    assert paths
    assert all(np.isfinite(path.points).all() for path in paths)
    assert all((path.points[:, 0] > 0).all() for path in paths)
