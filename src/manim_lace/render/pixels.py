"""Pixel-aligned stroke-width and unit conversions for Manim rendering.

Manim's ``stroke_width`` is relative to the frame height, not to screen pixels.
The actual pixel thickness of a stroked line is approximately::

    pixel_thickness ≈ 0.01 × stroke_width × (pixel_height / frame_height)

These helpers let a caller specify the desired **output pixel** thickness and
convert it to the Manim ``stroke_width`` value, or vice versa. They are pure
mathematics and do not import Manim, so the geometry core stays dependency-free.
"""

from __future__ import annotations

__all__ = [
    "FRAME_HEIGHT_480",
    "FRAME_HEIGHT_720",
    "FRAME_HEIGHT_1080",
    "PIXEL_HEIGHT_480",
    "PIXEL_HEIGHT_720",
    "PIXEL_HEIGHT_1080",
    "px_to_stroke_width",
    "px_to_units",
    "stroke_width_to_px",
]

#: Default Manim frame heights for common quality presets.
FRAME_HEIGHT_480: float = 8.0 / 3.0
FRAME_HEIGHT_720: float = 4.0
FRAME_HEIGHT_1080: float = 6.0

#: Default output pixel heights (vertical resolution) for common quality presets.
PIXEL_HEIGHT_480: int = 480
PIXEL_HEIGHT_720: int = 720
PIXEL_HEIGHT_1080: int = 1080


def px_to_stroke_width(
    px: float,
    *,
    pixel_height: int = PIXEL_HEIGHT_720,
    frame_height: float = FRAME_HEIGHT_720,
) -> float:
    """Convert a desired pixel thickness to a Manim ``stroke_width`` value.

    Parameters
    ----------
    px:
        Desired stroke thickness in output pixels.
    pixel_height:
        Vertical resolution of the rendered output (e.g. 480, 720, 1080).
    frame_height:
        Height of the Manim frame in world units.

    Returns
    -------
    float
        The value to pass to ``VMobject.set_stroke(width=...)`` so that the
        rendered line is approximately ``px`` pixels thick.

    Raises
    ------
    ValueError
        If ``px`` is not positive, ``pixel_height`` is not positive, or
        ``frame_height`` is not positive.
    """
    if not isinstance(px, (int, float)) or px <= 0:
        raise ValueError(f"px must be a positive number; got {px!r}")
    if not isinstance(pixel_height, int) or pixel_height <= 0:
        raise ValueError(f"pixel_height must be a positive int; got {pixel_height!r}")
    if not isinstance(frame_height, (int, float)) or frame_height <= 0:
        raise ValueError(f"frame_height must be positive; got {frame_height!r}")
    # pixel_thickness = 0.01 * stroke_width * (pixel_height / frame_height)
    # => stroke_width = pixel_thickness * frame_height / (0.01 * pixel_height)
    return float(px) * float(frame_height) / (0.01 * float(pixel_height))


def stroke_width_to_px(
    stroke_width: float,
    *,
    pixel_height: int = PIXEL_HEIGHT_720,
    frame_height: float = FRAME_HEIGHT_720,
) -> float:
    """Convert a Manim ``stroke_width`` value back to output pixels.

    Inverse of :func:`px_to_stroke_width`.

    Raises
    ------
    ValueError
        If any argument is non-positive.
    """
    if not isinstance(stroke_width, (int, float)) or stroke_width < 0:
        raise ValueError(f"stroke_width must be non-negative; got {stroke_width!r}")
    if not isinstance(pixel_height, int) or pixel_height <= 0:
        raise ValueError(f"pixel_height must be a positive int; got {pixel_height!r}")
    if not isinstance(frame_height, (int, float)) or frame_height <= 0:
        raise ValueError(f"frame_height must be positive; got {frame_height!r}")
    return 0.01 * float(stroke_width) * float(pixel_height) / float(frame_height)


def px_to_units(
    px: float,
    *,
    pixel_height: int = PIXEL_HEIGHT_720,
    frame_height: float = FRAME_HEIGHT_720,
) -> float:
    """Convert a pixel count to world (frame) units.

    Useful for sizing dots, gaps, and other geometric features to match
    a target on-screen pixel size.

    Raises
    ------
    ValueError
        If any argument is non-positive.
    """
    if not isinstance(px, (int, float)) or px <= 0:
        raise ValueError(f"px must be a positive number; got {px!r}")
    if not isinstance(pixel_height, int) or pixel_height <= 0:
        raise ValueError(f"pixel_height must be a positive int; got {pixel_height!r}")
    if not isinstance(frame_height, (int, float)) or frame_height <= 0:
        raise ValueError(f"frame_height must be positive; got {frame_height!r}")
    return float(px) * float(frame_height) / float(pixel_height)
