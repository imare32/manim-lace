"""内置色卡与随机取色工具的测试。"""

from __future__ import annotations

import random
import re

from manim_lace.swatches import SWATCH_SIZE, random_swatch, swatches

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_collection_is_populated():
    assert len(swatches) == 84


def test_every_swatch_has_the_documented_size():
    assert all(len(swatch) == SWATCH_SIZE for swatch in swatches)


def test_colors_are_hex_strings():
    for swatch in swatches:
        for color in swatch:
            assert HEX_PATTERN.match(color), f"{color!r} 不是合法的十六进制颜色"


def test_colors_are_unique_within_each_swatch():
    for index, swatch in enumerate(swatches):
        assert len(set(swatch)) == len(swatch), f"第 {index} 张色卡存在重复颜色"


def test_random_swatch_returns_a_known_palette():
    for _ in range(20):
        assert random_swatch() in swatches


def test_random_swatch_is_reproducible_with_a_seeded_rng():
    assert random_swatch(random.Random(0)) == random_swatch(random.Random(0))


def test_random_swatch_does_not_touch_the_global_rng():
    random.seed(1234)
    expected = random.random()
    random.seed(1234)
    random_swatch(random.Random(7))
    assert random.random() == expected
