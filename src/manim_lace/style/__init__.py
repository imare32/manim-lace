"""Aesthetic policies (M6): palettes, grouping, borders, cut ends and density.

Everything in this package is renderer-neutral and decorative: it reads a solved
:class:`~manim_lace.model.LaceResult` and decides how the result is *drawn*, never
what the weave *is*. Colour, grouping, frame and density choices therefore cannot
change crossings, over/under assignments or geometry (SPEC FR-062, AT-018). The
one exception is deliberate and explicit: a cover allowance changes the cut, so it
is a geometry parameter carried by the engine and reported by the stroke backend.
"""

from .border import CORNER_STYLES, BorderGeometry, BorderSpec, build_border, pattern_bounds
from .caps import (
    DEFAULT_MITER_LIMIT,
    CapTreatment,
    PieceOutline,
    stroke_piece_outline,
    trim_cut_half_length,
    validate_cover_allowance,
)
from .density import (
    DEFAULT_CLUSTER_FRACTION,
    DEFAULT_MIN_CLUSTER_SIZE,
    DensityCluster,
    DensityPolicy,
    DensityReport,
    DensitySimplification,
    analyze_density,
    simplify_for_density,
)
from .grouping import GROUPING_KINDS, StyleGroup, build_groups
from .palette import (
    ALIASES as PALETTE_ALIASES,
)
from .palette import (
    PALETTES,
    SWATCHES,
    ColorSwatch,
    Palette,
    get_palette,
    get_swatch,
    hex_to_rgb,
    is_light,
    palette_names,
    parse_color,
    register_palette,
    relative_luminance,
    resolve_palette,
    strand_colors,
)
from .policy import (
    DRAW_ORDER_MODES,
    PieceOrderingPolicy,
    StyleAssignment,
    StylePlan,
    StylePolicy,
    apply_style,
)

__all__ = [
    "CORNER_STYLES",
    "DEFAULT_CLUSTER_FRACTION",
    "DEFAULT_MIN_CLUSTER_SIZE",
    "DEFAULT_MITER_LIMIT",
    "DRAW_ORDER_MODES",
    "GROUPING_KINDS",
    "PALETTES",
    "PALETTE_ALIASES",
    "SWATCHES",
    "BorderGeometry",
    "BorderSpec",
    "CapTreatment",
    "ColorSwatch",
    "DensityCluster",
    "DensityPolicy",
    "DensityReport",
    "DensitySimplification",
    "Palette",
    "PieceOrderingPolicy",
    "PieceOutline",
    "StyleAssignment",
    "StyleGroup",
    "StylePlan",
    "StylePolicy",
    "analyze_density",
    "apply_style",
    "build_border",
    "build_groups",
    "get_palette",
    "get_swatch",
    "hex_to_rgb",
    "is_light",
    "palette_names",
    "parse_color",
    "pattern_bounds",
    "register_palette",
    "relative_luminance",
    "resolve_palette",
    "simplify_for_density",
    "strand_colors",
    "stroke_piece_outline",
    "trim_cut_half_length",
    "validate_cover_allowance",
]
