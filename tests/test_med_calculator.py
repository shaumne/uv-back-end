"""
Unit tests for the Dermatology Math Engine (med_calculator.py).

All test cases are sourced from:
- Dermatology_Math_Engine skill specification
- ICNIRP photobiology standards
- WHO UV Index Global Standard

Run: pytest backend/tests/test_med_calculator.py -v
"""
import math
import pytest
from app.services.med_calculator import (
    MED_TABLE,
    RiskLevel,
    calculate_uv_risk,
    classify_risk,
    get_med,
    remaining_safe_minutes,
    spf_effective,
    uv_percent_to_dose_jm2,
    uvi_to_irradiance,
)


# ──────────────────────────────────────────────────────────────────────────────
# MED lookup
# ──────────────────────────────────────────────────────────────────────────────

class TestGetMed:
    def test_all_fitzpatrick_types_correct(self):
        expected = {1: 200.0, 2: 250.0, 3: 350.0, 4: 500.0, 5: 700.0, 6: 1000.0}
        for fitz, med in expected.items():
            assert get_med(fitz) == med, f"Type {fitz}: expected {med}, got {get_med(fitz)}"

    def test_invalid_type_raises_value_error(self):
        for invalid in [0, 7, -1, 10]:
            with pytest.raises(ValueError, match="1–6"):
                get_med(invalid)

    def test_med_table_order_ascending(self):
        """Higher Fitzpatrick type must have higher or equal MED."""
        values = [MED_TABLE[i] for i in range(1, 7)]
        assert values == sorted(values)


# ──────────────────────────────────────────────────────────────────────────────
# UV irradiance
# ──────────────────────────────────────────────────────────────────────────────

class TestUviToIrradiance:
    def test_uvi_8_gives_0_2(self):
        assert uvi_to_irradiance(8.0) == pytest.approx(0.2, rel=1e-5)

    def test_zero_uvi(self):
        assert uvi_to_irradiance(0.0) == 0.0

    def test_linearity(self):
        """Irradiance must scale linearly with UV index."""
        assert uvi_to_irradiance(10.0) == pytest.approx(2 * uvi_to_irradiance(5.0))


# ──────────────────────────────────────────────────────────────────────────────
# SPF degradation (bi-exponential decay)
# ──────────────────────────────────────────────────────────────────────────────

class TestSpfEffective:
    def test_full_spf_at_t0(self):
        """At application time, effective SPF equals labelled SPF."""
        assert spf_effective(50, 0) == pytest.approx(50.0, rel=1e-3)

    def test_spf_decreases_over_time(self):
        """SPF must decrease monotonically after application."""
        values = [spf_effective(50, t) for t in [0, 2, 4, 8, 12]]
        assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))

    def test_no_sunscreen_spf1_flat(self):
        """SPF 1 (bare skin) must remain flat at 1.0."""
        for t in [0, 2, 4, 12]:
            assert spf_effective(1, t) == pytest.approx(1.0)

    def test_spf_never_below_1(self):
        """Effective SPF must not drop below 1.0 even at extreme time."""
        assert spf_effective(50, 100) >= 1.0

    def test_spf50_at_2h_approx_28(self):
        """Skill spec: SPF 50 at t=2h → ~28.4."""
        result = spf_effective(50, 2)
        assert 25.0 < result < 32.0, f"Expected ~28.4, got {result:.2f}"

    def test_spf50_at_8h_approx_6(self):
        """Skill spec: SPF 50 at t=8h → ~6.2."""
        result = spf_effective(50, 8)
        assert 4.0 < result < 8.0, f"Expected ~6.2, got {result:.2f}"

    def test_negative_hours_raises(self):
        with pytest.raises(ValueError):
            spf_effective(50, -1)


# ──────────────────────────────────────────────────────────────────────────────
# Remaining safe minutes
# ──────────────────────────────────────────────────────────────────────────────

class TestRemainingSafeMinutes:
    def test_zero_uv_index_returns_sentinel(self):
        """Night/indoor: UV index 0 → large sentinel (999)."""
        mins = remaining_safe_minutes(100.0, 500.0, 0.0)
        assert mins == pytest.approx(999.0)

    def test_exceeded_dose_returns_zero(self):
        """If cumulative > MED_protected, remaining = 0."""
        assert remaining_safe_minutes(600.0, 500.0, 8.0) == pytest.approx(0.0)

    def test_reasonable_output(self):
        """Fitzpatrick II, SPF 50, t=2h, 180 J/m², UVI 8 → ~11 min (skill example)."""
        spf_eff = spf_effective(50, 2.5)
        med_p = 250.0 * spf_eff
        mins = remaining_safe_minutes(180.0, med_p, 8.0)
        assert 5.0 < mins < 30.0, f"Expected ~11 min, got {mins:.1f}"


# ──────────────────────────────────────────────────────────────────────────────
# Risk classification
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyRisk:
    def test_exceeded_when_dose_ratio_gte_1(self):
        assert classify_risk(0.0, 600.0, 500.0) == RiskLevel.EXCEEDED

    def test_danger_when_minutes_zero(self):
        assert classify_risk(0.0, 400.0, 600.0) == RiskLevel.DANGER

    def test_warning_when_dose_ratio_gte_85pct(self):
        """Skill: dose ≥ 85% → WARNING; DANGER only when minutes_remaining ≤ 0."""
        assert classify_risk(20.0, 430.0, 500.0) == RiskLevel.WARNING

    def test_warning_when_minutes_lt_10(self):
        assert classify_risk(8.0, 250.0, 600.0) == RiskLevel.WARNING

    def test_caution_when_minutes_lt_30(self):
        assert classify_risk(25.0, 200.0, 600.0) == RiskLevel.CAUTION

    def test_safe_when_plenty_of_time(self):
        assert classify_risk(90.0, 50.0, 500.0) == RiskLevel.SAFE


# ──────────────────────────────────────────────────────────────────────────────
# Full pipeline: calculate_uv_risk
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateUvRisk:
    def test_returns_all_required_keys(self):
        result = calculate_uv_risk(2, 50, 0, 0, 5.0)
        required_keys = {
            "fitzpatrick_type", "spf_applied", "spf_effective_now",
            "med_base_jm2", "med_protected_jm2", "cumulative_dose_jm2",
            "dose_percentage", "minutes_remaining", "risk_level",
            "sunscreen_reapply_recommended",
        }
        assert required_keys.issubset(result.keys())

    def test_fitzpatrick_type_echoed(self):
        result = calculate_uv_risk(3, 30, 1, 0, 5.0)
        assert result["fitzpatrick_type"] == 3

    def test_zero_dose_is_safe(self):
        result = calculate_uv_risk(2, 50, 0, 0, 3.0)
        assert result["risk_level"] == RiskLevel.SAFE.value

    def test_full_dose_is_exceeded(self):
        result = calculate_uv_risk(1, 1, 0, 250.0, 5.0)
        assert result["risk_level"] == RiskLevel.EXCEEDED.value

    def test_invalid_fitzpatrick_raises(self):
        with pytest.raises(ValueError):
            calculate_uv_risk(7, 50, 0, 0, 5.0)

    def test_spf_reapply_flag_true_after_4h(self):
        """After 4h, SPF50 drops below 50*0.5=25 → reapply flag should be True."""
        result = calculate_uv_risk(2, 50, 4, 0, 5.0)
        assert result["sunscreen_reapply_recommended"] is True

    def test_spf_reapply_flag_false_at_t0(self):
        """At application time, SPF is full → no reapply needed."""
        result = calculate_uv_risk(2, 50, 0, 0, 5.0)
        assert result["sunscreen_reapply_recommended"] is False

    def test_dose_percentage_capped(self):
        """dose_percentage must be capped at 999.9 even when dose >> MED."""
        result = calculate_uv_risk(1, 1, 0, 10000.0, 5.0)
        assert result["dose_percentage"] <= 999.9


# ──────────────────────────────────────────────────────────────────────────────
# Unit conversion: UV% → J/m²
# ──────────────────────────────────────────────────────────────────────────────

class TestUvPercentToDoseJm2:
    def test_100_percent_equals_med_base(self):
        for fitz in range(1, 7):
            med = get_med(fitz)
            assert uv_percent_to_dose_jm2(100.0, fitz) == pytest.approx(med)

    def test_zero_percent_is_zero(self):
        assert uv_percent_to_dose_jm2(0.0, 2) == pytest.approx(0.0)

    def test_50_percent_is_half_med(self):
        for fitz in range(1, 7):
            assert uv_percent_to_dose_jm2(50.0, fitz) == pytest.approx(get_med(fitz) / 2)
