"""Tests for the pixel-aligned stroke-width utility (M1 remaining item)."""

import pytest

from manim_lace.render.pixels import (
    FRAME_HEIGHT_480,
    FRAME_HEIGHT_720,
    FRAME_HEIGHT_1080,
    PIXEL_HEIGHT_480,
    PIXEL_HEIGHT_720,
    PIXEL_HEIGHT_1080,
    px_to_stroke_width,
    px_to_units,
    stroke_width_to_px,
)


class TestPxToStrokeWidth:
    def test_basic_conversion_720p(self):
        # pixel_thickness = 0.01 * stroke_width * (720 / 4.0)
        # For 2 px at 720p (frame_height=4.0):
        # stroke_width = 2 * 4.0 / (0.01 * 720) = 8 / 7.2 ≈ 1.111...
        result = px_to_stroke_width(2.0, pixel_height=720, frame_height=4.0)
        assert result == pytest.approx(2.0 * 4.0 / (0.01 * 720))

    def test_round_trip(self):
        """px_to_stroke_width and stroke_width_to_px are inverses."""
        for px in (1.0, 2.5, 5.0, 10.0):
            sw = px_to_stroke_width(px, pixel_height=1080, frame_height=6.0)
            back = stroke_width_to_px(sw, pixel_height=1080, frame_height=6.0)
            assert back == pytest.approx(px)

    def test_480p_defaults(self):
        result = px_to_stroke_width(3.0, pixel_height=480, frame_height=FRAME_HEIGHT_480)
        assert result == pytest.approx(3.0 * FRAME_HEIGHT_480 / (0.01 * 480))

    def test_1080p_defaults(self):
        result = px_to_stroke_width(3.0, pixel_height=1080, frame_height=FRAME_HEIGHT_1080)
        assert result == pytest.approx(3.0 * FRAME_HEIGHT_1080 / (0.01 * 1080))

    def test_default_uses_720p(self):
        result = px_to_stroke_width(2.0)
        assert result == pytest.approx(2.0 * 4.0 / (0.01 * 720))

    @pytest.mark.parametrize("px", [0, -1, -0.01])
    def test_rejects_non_positive_px(self, px):
        with pytest.raises(ValueError, match="px must be a positive number"):
            px_to_stroke_width(px)

    def test_rejects_non_positive_pixel_height(self):
        with pytest.raises(ValueError, match="pixel_height"):
            px_to_stroke_width(1.0, pixel_height=0)

    def test_rejects_non_positive_frame_height(self):
        with pytest.raises(ValueError, match="frame_height"):
            px_to_stroke_width(1.0, frame_height=-1)


class TestStrokeWidthToPx:
    def test_zero_stroke_width(self):
        assert stroke_width_to_px(0.0) == 0.0

    def test_known_value(self):
        # stroke_width=1.0, 720p, frame_height=4.0
        # px = 0.01 * 1.0 * 720 / 4.0 = 1.8
        assert stroke_width_to_px(1.0, pixel_height=720, frame_height=4.0) == pytest.approx(1.8)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            stroke_width_to_px(-1.0)


class TestPxToUnits:
    def test_basic(self):
        # 2 px at 720p, frame_height=4.0 => 2 * 4.0 / 720
        result = px_to_units(2.0, pixel_height=720, frame_height=4.0)
        assert result == pytest.approx(2.0 * 4.0 / 720)

    def test_round_trip_with_stroke_width(self):
        px = 5.0
        sw = px_to_stroke_width(px, pixel_height=720, frame_height=4.0)
        # stroke_width_to_px checks the inverse of px_to_stroke_width
        back = stroke_width_to_px(sw, pixel_height=720, frame_height=4.0)
        assert back == pytest.approx(px)
        # px_to_units should give the same world-unit size
        units = px_to_units(px, pixel_height=720, frame_height=4.0)
        assert units == pytest.approx(px * 4.0 / 720)

    @pytest.mark.parametrize("px", [0, -1])
    def test_rejects_non_positive(self, px):
        with pytest.raises(ValueError, match="px must be a positive number"):
            px_to_units(px)


class TestQualityPresets:
    """The preset constants are the standard Manim frame heights."""

    def test_480p_constants(self):
        assert FRAME_HEIGHT_480 == pytest.approx(8.0 / 3.0)
        assert PIXEL_HEIGHT_480 == 480

    def test_720p_constants(self):
        assert FRAME_HEIGHT_720 == pytest.approx(4.0)
        assert PIXEL_HEIGHT_720 == 720

    def test_1080p_constants(self):
        assert FRAME_HEIGHT_1080 == pytest.approx(6.0)
        assert PIXEL_HEIGHT_1080 == 1080
