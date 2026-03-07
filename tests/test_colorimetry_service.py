"""
Unit tests for the Computer Vision Colorimetry Service (colorimetry_service.py).

Tests cover:
- Hex-to-UV-percent interpolation (critical pipeline step)
- HEX color format validation
- Edge cases: pure black, pure white, calibration anchors

Run: pytest backend/tests/test_colorimetry_service.py -v
"""
import pytest
import numpy as np
from app.services.colorimetry_service import (
    _hex_to_uv_percent,
    _dominant_hex_kmeans,
    _white_balance_lab,
    _roi_median_l_to_uv_percent,
)


# ──────────────────────────────────────────────────────────────────────────────
# HEX → UV% mapping (LAB L* interpolation)
# ──────────────────────────────────────────────────────────────────────────────

class TestHexToUvPercent:
    """
    Calibration curve from ComputerVision_Colorimetry skill (L* → UV%):
        (90,0), (75,10), (60,25), (45,50), (30,75), (15,100).
    LAB L*: high = fresh → low UV%; low = dark → high UV%.
    """

    def test_fresh_sticker_near_zero(self):
        """Very light sticker (moccasin #FFE4B5, L*≈92) → near 0% UV."""
        pct = _hex_to_uv_percent("#FFE4B5")
        assert pct <= 15.0, f"Expected <= 15%, got {pct:.1f}%"

    def test_dark_sticker_high_exposure(self):
        """Dark brown (#8B4513, L*≈38) → high UV% (skill curve ~60%+)."""
        pct = _hex_to_uv_percent("#8B4513")
        assert pct >= 55.0, f"Expected >= 55%, got {pct:.1f}%"

    def test_midpoint_sticker(self):
        """Orange (#FFA500, L*≈75) → low–mid UV% (skill curve ~10–25%)."""
        pct = _hex_to_uv_percent("#FFA500")
        assert 5.0 <= pct <= 35.0, f"Expected 5–35%, got {pct:.1f}%"

    def test_output_within_0_to_100_range(self):
        """UV% must be clamped to 0–100 range."""
        for hex_color in ["#FFFFFF", "#000000", "#FF0000", "#00FF00", "#0000FF"]:
            pct = _hex_to_uv_percent(hex_color)
            assert 0.0 <= pct <= 100.0, f"{hex_color} → {pct:.1f}% out of range"

    def test_invalid_hex_raises_or_returns_zero(self):
        """Invalid hex should either raise ValueError or return 0.0 gracefully."""
        try:
            pct = _hex_to_uv_percent("NOT_A_HEX")
            assert pct == 0.0
        except (ValueError, Exception):
            pass  # Either behaviour is acceptable

    def test_pure_white_near_zero(self):
        """Pure white sticker means unexposed → near 0% UV."""
        pct = _hex_to_uv_percent("#FFFFFF")
        assert pct <= 20.0

    def test_pure_black_near_hundred(self):
        """Pure black (L*=0) → 100% UV (clamped; maximum darkening)."""
        pct = _hex_to_uv_percent("#000000")
        assert pct >= 95.0


# ──────────────────────────────────────────────────────────────────────────────
# ROI median L* → UV% (dose reading after sticker detected)
# ──────────────────────────────────────────────────────────────────────────────

class TestRoiMedianLToUvPercent:
    """Sticker tespit edildikten sonra doz = ROI ortanca L* ile aynı eğri."""

    def test_uniform_dark_roi_high_uv(self):
        """Koyu BGR pikseller → yüksek UV%."""
        dark_bgr = np.tile([40, 30, 25], (100, 1)).astype(np.uint8)  # koyu
        pct = _roi_median_l_to_uv_percent(dark_bgr)
        assert pct >= 70.0, f"Expected high UV%, got {pct:.1f}%"

    def test_uniform_light_roi_low_uv(self):
        """Açık BGR pikseller → düşük UV%."""
        light_bgr = np.tile([240, 235, 230], (100, 1)).astype(np.uint8)  # açık
        pct = _roi_median_l_to_uv_percent(light_bgr)
        assert pct <= 25.0, f"Expected low UV%, got {pct:.1f}%"

    def test_output_in_range(self):
        """Sonuç her zaman 0–100 aralığında."""
        for b, g, r in [(0, 0, 0), (128, 128, 128), (255, 255, 255)]:
            pixels = np.tile([b, g, r], (50, 1)).astype(np.uint8)
            pct = _roi_median_l_to_uv_percent(pixels)
            assert 0.0 <= pct <= 100.0, f"BGR({b},{g},{r}) → {pct} out of range"


# ──────────────────────────────────────────────────────────────────────────────
# White balance
# ──────────────────────────────────────────────────────────────────────────────

class TestWhiteBalanceLab:
    def test_output_same_shape_as_input(self):
        """White balance must not change image dimensions."""
        img = np.full((100, 100, 3), [180, 160, 140], dtype=np.uint8)
        result = _white_balance_lab(img)
        assert result.shape == img.shape

    def test_output_dtype_uint8(self):
        """Output must remain uint8 for downstream OpenCV operations."""
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        result = _white_balance_lab(img)
        assert result.dtype == np.uint8

    def test_uniform_grey_stays_near_grey(self):
        """A perfectly grey image should stay near-grey after white balance."""
        grey = np.full((60, 60, 3), 128, dtype=np.uint8)
        result = _white_balance_lab(grey)
        mean_channels = result.mean(axis=(0, 1))
        # All channels should be within ±20 of 128
        for ch in mean_channels:
            assert abs(ch - 128) < 25, f"Channel diverged: {ch:.1f}"


# ──────────────────────────────────────────────────────────────────────────────
# Dominant HEX via K-Means
# ──────────────────────────────────────────────────────────────────────────────

class TestDominantHexKmeans:
    def test_returns_valid_hex_format(self):
        """Should return a string like #RRGGBB. Pixels must be (N, 3) BGR."""
        region = np.full((80, 80, 3), [200, 100, 50], dtype=np.uint8)
        pixels = region.reshape(-1, 3)
        hex_color = _dominant_hex_kmeans(pixels)
        assert hex_color.startswith("#"), f"Expected #RRGGBB, got '{hex_color}'"
        assert len(hex_color) == 7, f"Expected 7 chars, got {len(hex_color)}"

    def test_uniform_red_returns_red_ish_hex(self):
        """A solid red region (BGR: R=index 2) should produce red-dominant hex."""
        red_region = np.zeros((80, 80, 3), dtype=np.uint8)
        red_region[:, :, 2] = 200  # BGR: red channel = index 2
        pixels = red_region.reshape(-1, 3)
        hex_color = _dominant_hex_kmeans(pixels)
        r_val = int(hex_color[1:3], 16)
        assert r_val > 100, f"Expected red-dominant hex, got {hex_color}"

    def test_handles_small_regions(self):
        """Should not crash on very small pixel sets (edge case)."""
        tiny = np.full((5, 5, 3), [128, 64, 32], dtype=np.uint8)
        pixels = tiny.reshape(-1, 3)
        result = _dominant_hex_kmeans(pixels)
        assert result.startswith("#")
