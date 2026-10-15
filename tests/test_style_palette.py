"""The colour card, the named palettes and reproducible strand colouring (M6)."""

import re

import pytest

from manim_lace import PALETTES, get_palette, get_swatch, palette_names, register_palette
from manim_lace.style import palette as palette_module
from manim_lace.style.palette import (
    ALIASES,
    SWATCHES,
    ColorSwatch,
    Palette,
    hex_to_rgb,
    is_light,
    parse_color,
    relative_luminance,
    resolve_palette,
    strand_colors,
)

_HEX = re.compile(r"\A#[0-9a-f]{6}\Z")


def test_the_colour_card_holds_normalized_unique_swatches():
    assert len(SWATCHES) >= 50
    assert len(SWATCHES) == len(palette_module.ALL_SWATCHES)
    for name, swatch in SWATCHES.items():
        assert swatch.name == name
        assert swatch.reading
        assert _HEX.match(swatch.hex), (name, swatch.hex)
    assert SWATCHES["山吹色"].hex == "#f8b500"
    assert SWATCHES["山吹色"].rgb == (248, 181, 0)
    assert SWATCHES["江戸紫"].hex == "#745399"
    assert hex_to_rgb("745399") == (116, 83, 153)


def test_unknown_colour_name_raises_with_the_card_size():
    with pytest.raises(ValueError, match="unknown colour name"):
        get_swatch("幻想色")


def test_swatch_rejects_a_non_hex_value():
    with pytest.raises(ValueError, match="color must be"):
        ColorSwatch("謎色", "なぞいろ", "hot pink")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("#ABC", "#aabbcc"), ("FFF4F4", "#fff4f4"), ("  #F8B500 ", "#f8b500")],
)
def test_parse_color_normalizes_hex_forms(text, expected):
    assert parse_color(text) == expected


@pytest.mark.parametrize("bad", ["", "#12345", "#GGGGGG", "rgb(1,2,3)", "#f8b50"])
def test_parse_color_rejects_anything_that_is_not_hex(bad):
    with pytest.raises(ValueError, match="color"):
        parse_color(bad)


def test_luminance_and_lightness_order_the_card_sensibly():
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert relative_luminance("#ffffff") == pytest.approx(1.0, abs=1e-6)
    assert relative_luminance("#f8b500") > relative_luminance("#223a70")
    assert is_light(SWATCHES["胡粉"].hex)
    assert not is_light(SWATCHES["墨色"].hex)


def test_named_palettes_are_registered_and_reachable_by_alias():
    assert palette_names() == ["haru", "natsu", "aki", "fuyu", "matsuri", "wabi", "ayame"]
    assert get_palette("haru") is PALETTES["haru"]
    assert get_palette("春") is PALETTES["haru"]
    assert get_palette("spring") is PALETTES["haru"]
    assert get_palette("祭") is PALETTES["matsuri"]
    assert ALIASES["wabi-sabi"] == "wabi"


def test_every_palette_keeps_visible_colours_first_and_has_a_paper():
    for name in palette_names():
        palette = get_palette(name)
        assert palette.label and palette.description
        assert len(palette) >= 5
        assert len(set(palette.colors)) == len(palette)
        assert all(_HEX.match(color) for color in palette.colors)
        # The last swatch is the pale "empty space" tone of the palette.
        assert relative_luminance(palette.colors[-1]) > relative_luminance(palette.colors[0])
        assert _HEX.match(palette.background)
        assert is_light(palette.background)


def test_unknown_palette_lists_the_available_ones():
    with pytest.raises(ValueError, match="available"):
        get_palette("no-such-palette")


def test_palette_rejects_empty_and_repeated_colours():
    with pytest.raises(ValueError, match="no swatches"):
        Palette(name="empty", label="空", description="", swatches=())
    with pytest.raises(ValueError, match="repeats a colour"):
        Palette(
            name="twin",
            label="双",
            description="",
            swatches=(ColorSwatch("一", "いち", "#112233"), ColorSwatch("二", "に", "#112233")),
        )


def test_palette_with_background_normalizes_the_paper():
    palette = get_palette("aki").with_background("FFF")
    assert palette.background == "#ffffff"
    assert get_palette("aki").background == "#f8f4e6"


def test_strand_colors_cycle_and_spread():
    haru = get_palette("haru")
    assert haru.strand_colors(2) == list(haru.colors[:2])
    assert haru.strand_colors(8) == [*haru.colors, *haru.colors[:2]]
    even = haru.strand_colors(3, mode="even")
    assert even == [haru.colors[(index * len(haru)) // 3] for index in range(3)]
    assert len(set(even)) == 3
    assert haru.strand_colors(0) == []


def test_strand_colors_shuffle_is_reproducible_and_seeded():
    haru = get_palette("haru")
    first = haru.strand_colors(6, seed=7, mode="shuffle")
    assert first == haru.strand_colors(6, seed=7, mode="shuffle")
    assert sorted(first) == sorted(haru.colors)
    assert first != haru.strand_colors(6, seed=8, mode="shuffle")
    assert first != haru.colors


def test_strand_colors_rejects_bad_arguments():
    haru = get_palette("haru")
    with pytest.raises(ValueError, match="mode"):
        haru.strand_colors(3, mode="random")
    with pytest.raises(ValueError, match="non-negative"):
        haru.strand_colors(-1)
    with pytest.raises(ValueError, match="at least one colour"):
        strand_colors([], 3)
    with pytest.raises(ValueError, match="not a palette"):
        strand_colors("山吹色", 3)


def test_resolve_palette_accepts_names_objects_sequences_and_none():
    assert resolve_palette(None) == ["#888888"]
    assert resolve_palette(None, fallback="F8B500") == ["#f8b500"]
    assert resolve_palette("aki") == list(get_palette("aki").colors)
    assert resolve_palette(get_palette("aki")) == list(get_palette("aki").colors)
    assert resolve_palette(["#ABC", "def"]) == ["#aabbcc", "#ddeeff"]
    with pytest.raises(ValueError, match="palette must be"):
        resolve_palette(3.5)


def test_register_palette_reports_clashes_and_supports_replacement():
    custom = Palette(
        name="test-only",
        label="测",
        description="only used by this test",
        swatches=(ColorSwatch("深", "ふか", "#112233"), ColorSwatch("淡", "あわ", "#ddeeff")),
    )
    try:
        register_palette(custom, aliases=("测试色卡",))
        assert get_palette("测试色卡") is custom
        with pytest.raises(ValueError, match="already registered"):
            register_palette(custom)
        with pytest.raises(ValueError, match="already points at"):
            register_palette(
                Palette(name="other", label="他", description="", swatches=custom.swatches[:1]),
                aliases=("测试色卡",),
            )
        register_palette(custom, aliases=("测试色卡",), replace=True)
        assert get_palette("test-only") is custom
    finally:
        palette_module.PALETTES.pop("test-only", None)
        palette_module.PALETTES.pop("other", None)
        ALIASES.pop("测试色卡", None)


def test_the_render_palettes_shim_keeps_the_old_season_names():
    from manim_lace.render import palettes as shim

    assert shim.SPRING == tuple(get_palette("haru").colors)
    assert shim.PALETTES["festival"] == tuple(get_palette("matsuri").colors)
    assert shim.resolve_palette("spring") == list(get_palette("haru").colors)
    assert shim.strand_colors("winter", 3) == get_palette("fuyu").strand_colors(3)
