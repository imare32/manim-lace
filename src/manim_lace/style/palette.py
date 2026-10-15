"""Pluggable colour palettes built from Japanese traditional colour names.

The swatch values are the commonly published hex codes of 和色 (``wadokei``-era
traditional Japanese colour names, as circulated by 和色大辞典 / JIS 慣用色名).
Only the colour *names and values* are used here; the way the swatches are
grouped into seasonal and tonal palettes is **inspired by** Teruko Sakurai's
《日本色彩调和辞典》 (*Japanese Color Harmony Dictionary*). The book's own swatch
pages, combination recipes and text are not reproduced: every palette below is an
original arrangement of public-domain colour names.

A palette is just a list of ``#RRGGBB`` strings, so this module imports neither
Manim nor Shapely; the Manim adapter passes the strings straight to
``set_stroke``/``set_fill`` and any other renderer can consume them too.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

__all__ = [
    "ALIASES",
    "PALETTES",
    "SWATCHES",
    "ColorSwatch",
    "Palette",
    "get_palette",
    "get_swatch",
    "hex_to_rgb",
    "is_light",
    "palette_names",
    "parse_color",
    "register_palette",
    "relative_luminance",
    "resolve_palette",
    "strand_colors",
]

_HEX_RE = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")


def parse_color(color: str) -> str:
    """Normalize ``#abc`` / ``abc`` / ``#AABBCC`` into lowercase ``#aabbcc``.

    Raises ``ValueError`` for anything that is not a hex colour, so a typo in a
    palette fails at construction instead of painting the wrong thing silently.
    """
    if not isinstance(color, str):
        raise ValueError(f"color must be a hex string such as '#f8b500'; got {type(color).__name__}")
    text = color.strip()
    if not text:
        raise ValueError("color must not be empty")
    if not text.startswith("#"):
        text = f"#{text}"
    if not _HEX_RE.match(text):
        raise ValueError(f"color must be '#RRGGBB' or '#RGB'; got {color!r}")
    body = text[1:].lower()
    if len(body) == 3:
        body = "".join(character * 2 for character in body)
    return f"#{body}"


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """The ``(r, g, b)`` channels of a hex colour, each within ``0..255``."""
    body = parse_color(color)[1:]
    return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)


def _srgb_channel(value: int) -> float:
    ratio = value / 255.0
    return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a hex colour, within ``0.0`` (black) and ``1.0``."""
    red, green, blue = hex_to_rgb(color)
    return (
        0.2126 * _srgb_channel(red)
        + 0.7152 * _srgb_channel(green)
        + 0.0722 * _srgb_channel(blue)
    )


def is_light(color: str, *, threshold: float = 0.5) -> bool:
    """Whether a colour reads as light, i.e. dark ink on it stays legible."""
    return relative_luminance(color) > threshold


@dataclass(frozen=True, slots=True)
class ColorSwatch:
    """One named traditional colour: name, reading and normalized hex value."""

    name: str
    reading: str
    hex: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a swatch needs a colour name")
        object.__setattr__(self, "hex", parse_color(self.hex))

    @property
    def rgb(self) -> tuple[int, int, int]:
        return hex_to_rgb(self.hex)

    @property
    def luminance(self) -> float:
        return relative_luminance(self.hex)

    def describe(self) -> str:
        return f"{self.name}（{self.reading}）{self.hex}"


# ---------------------------------------------------------------------------
# 色卡 (swatch card): the traditional colours, grouped by family for readability.
# Values are the commonly published hex codes of the traditional names; where
# sources disagree by a shade or two the widely circulated 和色大辞典 value wins.
# ---------------------------------------------------------------------------

# 桃・紅系
SAKURA = ColorSwatch("桜色", "さくらいろ", "#FEF4F4")
USUBENI = ColorSwatch("退紅", "うすべに", "#F0908D")
MOMO = ColorSwatch("桃色", "ももいろ", "#F09199")
KOBAI = ColorSwatch("紅梅色", "こうばいいろ", "#F2A0A1")
SEKICHIKU = ColorSwatch("石竹色", "せきちくいろ", "#E5ABBE")
IKKINZOME = ColorSwatch("一斤染", "いっきんぞめ", "#F4A7B9")
TSUTSUJI = ColorSwatch("躑躅色", "つつじいろ", "#E95295")
SANGO = ColorSwatch("珊瑚色", "さんごいろ", "#F5B1AA")
AKANE = ColorSwatch("茜色", "あかねいろ", "#B7282E")
SHU = ColorSwatch("朱色", "しゅいろ", "#EB6101")
CHOSHUN = ColorSwatch("長春色", "ちょうしゅんいろ", "#C97586")
SHINONOME = ColorSwatch("東雲色", "しののめいろ", "#F19072")

# 黄・橙系
KOHAKU_WHITE = ColorSwatch("胡粉", "ごふん", "#FFFFFC")
ZOUGE = ColorSwatch("象牙色", "ぞうげいろ", "#F8F4E6")
KINARI = ColorSwatch("生成色", "きなりいろ", "#FBFAF5")
KUCHINASHI = ColorSwatch("梔子色", "くちなしいろ", "#FFDB4F")
YAMABUKI = ColorSwatch("山吹色", "やまぶきいろ", "#F8B500")
OUNI = ColorSwatch("黄丹", "おうに", "#EE7948")
TERIGAKI = ColorSwatch("照柿", "てりがき", "#EB6238")

# 緑系
WAKATAKE = ColorSwatch("若竹色", "わかたけいろ", "#68BE8D")
TOKIWA = ColorSwatch("常磐色", "ときわいろ", "#007B43")
MATSUBA = ColorSwatch("松葉色", "まつばいろ", "#839B5C")
MOEGI = ColorSwatch("萌黄", "もえぎ", "#AACF53")
RIKYU_NEZUMI = ColorSwatch("利休鼠", "りきゅうねずみ", "#888E7E")
YAMABATO = ColorSwatch("山鳩色", "やまばといろ", "#767C6B")

# 青系
AI = ColorSwatch("藍色", "あいいろ", "#165E83")
KON = ColorSwatch("紺色", "こんいろ", "#223A70")
RURI = ColorSwatch("瑠璃色", "るりいろ", "#1E50A2")
GUNJO = ColorSwatch("群青色", "ぐんじょういろ", "#4C6CB3")
SORA = ColorSwatch("空色", "そらいろ", "#A0D8EF")
ASAGI = ColorSwatch("浅葱色", "あさぎいろ", "#00A3AF")
SHINBASHI = ColorSwatch("新橋色", "しんばしいろ", "#59B9C6")
TSUYUKUSA = ColorSwatch("露草色", "つゆくさいろ", "#38A1DB")
SEIJI = ColorSwatch("青磁色", "せいじいろ", "#7EBEA5")
NANDO = ColorSwatch("納戸色", "なんどいろ", "#008899")

# 紫系
FUJI = ColorSwatch("藤色", "ふじいろ", "#BBBCDE")
HANADA = ColorSwatch("半色", "はしたいろ", "#A69ABD")
SHION = ColorSwatch("紫苑色", "しおんいろ", "#867BA9")
KODAI_MURASAKI = ColorSwatch("古代紫", "こだいむらさき", "#895B8A")
EDO_MURASAKI = ColorSwatch("江戸紫", "えどむらさき", "#745399")
KIKYO = ColorSwatch("桔梗色", "ききょういろ", "#5654A2")
SUMIRE = ColorSwatch("菫色", "すみれいろ", "#7058A3")

# 茶・無彩色系
AMAIRO = ColorSwatch("亜麻色", "あまいろ", "#D6C6AF")
HAIZAKURA = ColorSwatch("灰桜", "はいざくら", "#E8D3D1")
HATOBANEZUMI = ColorSwatch("鳩羽鼠", "はとばねずみ", "#9E8B8E")
KURUMI = ColorSwatch("胡桃色", "くるみいろ", "#A86F4C")
KOHAKU = ColorSwatch("琥珀色", "こはくいろ", "#BF783A")
BENGARA = ColorSwatch("弁柄色", "べんがらいろ", "#8F2E14")
SABI = ColorSwatch("錆色", "さびいろ", "#6C3524")
EBICHA = ColorSwatch("海老茶", "えびちゃ", "#773C30")
GINNEZU = ColorSwatch("銀鼠", "ぎんねず", "#AFAFB0")
NEZUMI = ColorSwatch("鼠色", "ねずみいろ", "#949495")
SHIRONEZU = ColorSwatch("白鼠", "しろねず", "#DCDDDD")
SHIRONERI = ColorSwatch("白練", "しろねり", "#F3F3F2")
KESHIZUMI = ColorSwatch("消炭色", "けしずみいろ", "#524748")
SUMI = ColorSwatch("墨色", "すみいろ", "#595857")

#: Every registered swatch, in definition order.
ALL_SWATCHES: tuple[ColorSwatch, ...] = (
    SAKURA, USUBENI, MOMO, KOBAI, SEKICHIKU, IKKINZOME, TSUTSUJI, SANGO, AKANE, SHU, CHOSHUN,
    SHINONOME,
    KOHAKU_WHITE, ZOUGE, KINARI, KUCHINASHI, YAMABUKI, OUNI, TERIGAKI,
    WAKATAKE, TOKIWA, MATSUBA, MOEGI, RIKYU_NEZUMI, YAMABATO,
    AI, KON, RURI, GUNJO, SORA, ASAGI, SHINBASHI, TSUYUKUSA, SEIJI, NANDO,
    FUJI, HANADA, SHION, KODAI_MURASAKI, EDO_MURASAKI, KIKYO, SUMIRE,
    AMAIRO, HAIZAKURA, HATOBANEZUMI, KURUMI, KOHAKU, BENGARA, SABI, EBICHA,
    GINNEZU, NEZUMI, SHIRONEZU, SHIRONERI, KESHIZUMI, SUMI,
)


def _swatch_index() -> dict[str, ColorSwatch]:
    index: dict[str, ColorSwatch] = {}
    for swatch in ALL_SWATCHES:
        if swatch.name in index:
            raise ValueError(f"duplicate swatch name in the colour card: {swatch.name!r}")
        index[swatch.name] = swatch
    return index


#: The colour card, keyed by traditional colour name.
SWATCHES: dict[str, ColorSwatch] = _swatch_index()


def get_swatch(name: str) -> ColorSwatch:
    """Look up one colour of the card by its traditional name (``"山吹色"``)."""
    try:
        return SWATCHES[name]
    except KeyError:
        raise ValueError(
            f"unknown colour name {name!r}; the card holds {len(SWATCHES)} traditional colours"
        ) from None


@dataclass(frozen=True, slots=True)
class Palette:
    """An ordered, named set of colours that a style policy can cycle through.

    ``swatches`` are ordered dark → light with the paper-like pale colours at the
    end: the first few colours a policy takes are then the visible ones, and the
    palest swatch doubles as the "empty space" tone of the palette. ``background``
    is the paper the palette is meant to sit on; both are plain hex strings.
    """

    name: str
    label: str
    description: str
    swatches: tuple[ColorSwatch, ...]
    background: str = KOHAKU_WHITE.hex

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a palette needs a name")
        swatches = tuple(self.swatches)
        if not swatches:
            raise ValueError(f"palette {self.name!r} has no swatches")
        if len({swatch.hex for swatch in swatches}) != len(swatches):
            raise ValueError(f"palette {self.name!r} repeats a colour; that is a typo, not a palette")
        object.__setattr__(self, "swatches", swatches)
        object.__setattr__(self, "background", parse_color(self.background))

    @property
    def colors(self) -> tuple[str, ...]:
        """The palette colours as hex strings, in order."""
        return tuple(swatch.hex for swatch in self.swatches)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(swatch.name for swatch in self.swatches)

    def __len__(self) -> int:
        return len(self.swatches)

    def __iter__(self) -> Iterator[ColorSwatch]:
        return iter(self.swatches)

    def swatch(self, index: int) -> ColorSwatch:
        """The swatch at ``index``, cycling when the index runs past the end."""
        return self.swatches[int(index) % len(self.swatches)]

    def color(self, index: int) -> str:
        """The hex colour at ``index``, cycling when the index runs past the end."""
        return self.swatch(index).hex

    def with_background(self, color: str) -> Palette:
        """The same palette on a different paper colour."""
        return replace(self, background=parse_color(color))

    def strand_colors(
        self, count: int, *, seed: int | None = None, mode: str = "cycle"
    ) -> list[str]:
        """``count`` colours for consecutive strands.

        ``mode`` is ``cycle`` (palette order, repeating), ``even`` (spread evenly
        over the palette, so a long strand list uses the whole range) or
        ``shuffle`` (deterministic shuffle; pass ``seed`` for reproducibility,
        SPEC FR-063).
        """
        if count < 0:
            raise ValueError(f"count must be non-negative; got {count}")
        if mode not in ("cycle", "even", "shuffle"):
            raise ValueError(f"mode must be 'cycle', 'even' or 'shuffle'; got {mode!r}")
        colors = self.colors
        size = len(colors)
        if mode == "cycle" or count == 0:
            return [colors[index % size] for index in range(count)]
        if mode == "even":
            return [colors[(index * size) // count] for index in range(count)]
        shuffled = list(colors)
        random.Random(seed).shuffle(shuffled)
        return [shuffled[index % size] for index in range(count)]

    def describe(self) -> str:
        """A one-line human summary, useful in docs, logs and gallery captions."""
        return f"{self.label}（{self.name}）：" + "、".join(swatch.describe() for swatch in self.swatches)


# ---------------------------------------------------------------------------
# Named palettes: seasonal and tonal groupings of the card above.
#
# Ordering rule: dark first, paper-like pale colours last, so cycling through a
# palette gives visible strands before it gives empty space.
# ---------------------------------------------------------------------------

PALETTES: dict[str, Palette] = {}
#: Extra spellings accepted by :func:`get_palette`, mapped to a canonical name.
ALIASES: dict[str, str] = {}


def register_palette(
    palette: Palette, *, aliases: Iterable[str] = (), replace: bool = False
) -> Palette:
    """Add a palette to the registry so it can be selected by name.

    ``aliases`` are additional accepted spellings (``"春"``, ``"spring"``). A
    clash raises ``ValueError`` unless ``replace=True``, so two plugins cannot
    silently shadow each other.
    """
    key = palette.name.strip().lower()
    if key in PALETTES and not replace:
        raise ValueError(f"palette {key!r} is already registered; pass replace=True to override")
    PALETTES[key] = palette
    for alias in aliases:
        alias_key = str(alias).strip().lower()
        if not alias_key:
            raise ValueError("a palette alias must not be empty")
        owner = alias_key if alias_key in PALETTES else ALIASES.get(alias_key)
        if owner is not None and owner != key and not replace:
            raise ValueError(f"alias {alias!r} already points at palette {owner!r}")
        ALIASES[alias_key] = key
    return palette


def palette_names() -> list[str]:
    """All registered palette names, canonical ones first, in definition order."""
    return list(PALETTES)


HARU = register_palette(
    Palette(
        name="haru",
        label="春",
        description="樱、嫩叶与春日晴空：深色在前，桜色留在末尾作留白。",
        swatches=(WAKATAKE, FUJI, MOMO, SORA, IKKINZOME, SAKURA),
    ),
    aliases=("春", "spring"),
)
NATSU = register_palette(
    Palette(
        name="natsu",
        label="夏",
        description="常磐、瑠璃与盛夏水面：由深绿到浅葱，梔子色收尾。",
        swatches=(TOKIWA, RURI, ASAGI, MOEGI, YAMABUKI, KUCHINASHI),
    ),
    aliases=("夏", "summer"),
)
AKI = register_palette(
    Palette(
        name="aki",
        label="秋",
        description="柿、琥珀与栗：暖米色纸上的橙褐色阶，由深到浅。",
        swatches=(EBICHA, KURUMI, KOHAKU, TERIGAKI, OUNI, AMAIRO),
        background=ZOUGE.hex,
    ),
    aliases=("秋", "autumn", "fall"),
)
FUYU = register_palette(
    Palette(
        name="fuyu",
        label="冬",
        description="霜、梅与炭：消炭到白練的冷灰阶，長春（梅）是唯一暖点。",
        swatches=(KESHIZUMI, HATOBANEZUMI, CHOSHUN, GINNEZU, SHIRONEZU, SHIRONERI),
    ),
    aliases=("冬", "winter"),
)
MATSURI = register_palette(
    Palette(
        name="matsuri",
        label="祭",
        description="祭礼的强对比：墨、藍、常磐、朱、山吹，胡粉留给最亮的留白。",
        swatches=(SUMI, AI, TOKIWA, SHU, YAMABUKI, KOHAKU_WHITE),
    ),
    aliases=("祭", "festival"),
)
WABI = register_palette(
    Palette(
        name="wabi",
        label="侘",
        description="侘寂的中性色阶：消炭、山鳩、利休鼠，生成色收在纸底一端。",
        swatches=(KESHIZUMI, YAMABATO, RIKYU_NEZUMI, AMAIRO, ZOUGE, KINARI),
        background=KINARI.hex,
    ),
    aliases=("侘", "wabi-sabi", "wabisabi"),
)
AYAME = register_palette(
    Palette(
        name="ayame",
        label="菖蒲",
        description="菖蒲与青磁：桔梗、群青、江戸紫为主，青磁色作冷调落点。",
        swatches=(KIKYO, GUNJO, EDO_MURASAKI, SHION, HANADA, SEIJI),
    ),
    aliases=("菖蒲", "iris"),
)


def _resolve_name(reference: str) -> str:
    key = reference.strip().lower()
    if key in PALETTES:
        return key
    if key in ALIASES:
        return ALIASES[key]
    raise ValueError(
        f"unknown palette {reference!r}; available: {palette_names()} "
        f"(aliases: {sorted(ALIASES)})"
    )


def get_palette(reference: str | Palette) -> Palette:
    """Resolve a palette name, an alias, or an already built :class:`Palette`."""
    if isinstance(reference, Palette):
        return reference
    if not isinstance(reference, str):
        raise ValueError(f"palette must be a name or a Palette; got {type(reference).__name__}")
    return PALETTES[_resolve_name(reference)]


def resolve_palette(
    reference: str | Palette | Sequence[str] | None, *, fallback: str = "#888888"
) -> list[str]:
    """Turn any palette reference into a list of hex colours (``None`` → fallback).

    Accepts a name/alias, a :class:`Palette`, an explicit sequence of colours, or
    ``None`` for the single-colour fallback (the pre-M6 behaviour).
    """
    if reference is None:
        return [parse_color(fallback)]
    if isinstance(reference, Palette):
        return list(reference.colors)
    if isinstance(reference, str):
        return list(get_palette(reference).colors)
    if isinstance(reference, Sequence):
        return [parse_color(color) for color in reference]
    raise ValueError(
        "palette must be a palette name, a Palette, a sequence of hex colours, or None; "
        f"got {type(reference).__name__}"
    )


def strand_colors(
    reference: str | Palette | Sequence[str] | None,
    count: int,
    *,
    fallback: str = "#888888",
    seed: int | None = None,
    mode: str = "cycle",
) -> list[str]:
    """``count`` colours taken from any palette reference.

    An explicit :class:`Palette` honours ``seed``/``mode``; a name is resolved to
    its :class:`Palette` and does the same, so ``strand_colors("aki", 12, mode="even")``
    spreads the whole autumn range over twelve strands.
    """
    if isinstance(reference, Palette):
        return reference.strand_colors(count, seed=seed, mode=mode)
    if isinstance(reference, str):
        try:
            return get_palette(reference).strand_colors(count, seed=seed, mode=mode)
        except ValueError:
            if reference in SWATCHES:
                raise ValueError(
                    f"{reference!r} is a colour name, not a palette; "
                    f"pass [get_swatch({reference!r}).hex] or a registered palette name"
                ) from None
            raise
    colors = resolve_palette(reference, fallback=fallback)
    if not colors:
        raise ValueError("an explicit colour sequence must contain at least one colour")
    if count < 0:
        raise ValueError(f"count must be non-negative; got {count}")
    if mode not in ("cycle", "even", "shuffle"):
        raise ValueError(f"mode must be 'cycle', 'even' or 'shuffle'; got {mode!r}")
    if mode == "cycle" or count == 0:
        return [colors[index % len(colors)] for index in range(count)]
    if mode == "even":
        return [colors[(index * len(colors)) // count] for index in range(count)]
    shuffled = list(colors)
    random.Random(seed).shuffle(shuffled)
    return [shuffled[index % len(shuffled)] for index in range(count)]
