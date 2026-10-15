"""Compatibility shim: the palettes now live in :mod:`manim_lace.style.palette`.

The M6 style package owns the colour card, the named palettes and the registry
(``manim_lace.style.palette``). This module keeps the earlier import path working
by re-exporting that API, and maps the original English season names onto the
current palettes so ``resolve_palette("spring")`` keeps behaving as before.
"""

from __future__ import annotations

from ..style.palette import (
    ColorSwatch,
    Palette,
    get_palette,
    palette_names,
    parse_color,
    register_palette,
    resolve_palette,
    strand_colors,
)

__all__ = [
    "PALETTES",
    "ColorSwatch",
    "Palette",
    "get_palette",
    "palette_names",
    "resolve_palette",
    "strand_colors",
]

#: Kept for the old import path: the *hex tuples* of the palettes, keyed by the
#: original English names (``PALETTES`` in the style package holds ``Palette``
#: objects keyed by romaji names).
PALETTES: dict[str, tuple[str, ...]] = {
    "spring": get_palette("haru").colors,
    "summer": get_palette("natsu").colors,
    "autumn": get_palette("aki").colors,
    "winter": get_palette("fuyu").colors,
    "festival": get_palette("matsuri").colors,
    "wabi": get_palette("wabi").colors,
    "ayame": get_palette("ayame").colors,
}

SPRING = PALETTES["spring"]
SUMMER = PALETTES["summer"]
AUTUMN = PALETTES["autumn"]
WINTER = PALETTES["winter"]
FESTIVAL = PALETTES["festival"]
WABI = PALETTES["wabi"]
AYAME = PALETTES["ayame"]

__all__ += [
    "AYAME",
    "AUTUMN",
    "FESTIVAL",
    "SPRING",
    "SUMMER",
    "WABI",
    "WINTER",
    "parse_color",
    "register_palette",
]
