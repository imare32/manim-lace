"""Suite-wide knobs shared by the test modules.

The suite is a long tail of cheap cases plus a handful that dominate the wall clock.
Measured on this machine, the full run is ~217 s and two families own almost all of it:

* one catalog-wide re-measure (``test_the_raw_input_channel_is_rendered_first``) at ~84 s;
* the implicit-curve cases at ~67 s for the six cases in ``test_review_catalog`` and
  another ~22 s across the five tests in ``test_implicit`` — fine grids plus refinement
  passes, so their cost is in the sampler, not in the weave backends.

Neither family says anything about ribbon rendering, which is what most edits touch, so
they are marked ``heavy`` and ``--skip-heavy`` drops them. The default run is unchanged:
the marker only skips when the switch is given.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("manim-lace")
    group.addoption(
        "--skip-heavy",
        action="store_true",
        default=False,
        help="跳过标记为 heavy 的重案例（隐式曲线的全量细化、审查目录全量重测）",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--skip-heavy"):
        return
    skip = pytest.mark.skip(reason="--skip-heavy：重案例已跳过")
    for item in items:
        if item.get_closest_marker("heavy") is not None:
            item.add_marker(skip)
