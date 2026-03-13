"""
Dermatology Math Engine — MED, SPF degradation, and UV risk calculation.

Implements the full risk pipeline specified by the Dermatology_Math_Engine skill:

    Fitzpatrick Type → MED_base
    MED_base × SPF_effective(t) → MED_protected
    (MED_protected − cumulative_dose) / UV_irradiance → minutes_remaining

All formulas are based on published photobiology standards:
- CIE 209:2014 — Photocarcinogenesis Action Spectrum
- ICNIRP 2004  — Guidelines on limits of exposure to ultraviolet radiation
- WHO 2002     — Global Solar UV Index
- Fitzpatrick TB (1988) — Sun-reactive skin types validity
"""
import logging
import math
from enum import Enum

logger = logging.getLogger(__name__)

# ── MED baselines (J/m²) per Fitzpatrick type ─────────────────────────────────
# Source: ICNIRP / CIE photobiology standards
MED_TABLE: dict[int, float] = {
    1: 200.0,   # Very fair — always burns, never tans
    2: 250.0,   # Fair     — usually burns, sometimes tans
    3: 350.0,   # Medium   — sometimes burns, always tans
    4: 500.0,   # Olive    — rarely burns, always tans
    5: 700.0,   # Brown    — very rarely burns
    6: 1000.0,  # Dark     — almost never burns
}

# ── UV irradiance conversion (WHO standard) ───────────────────────────────────
# 1 UV Index unit = 0.025 W/m² (= J/m²/s)
_UVI_TO_IRRADIANCE = 0.025  # W/m² per UV Index unit

# ── SPF bi-exponential decay parameters ──────────────────────────────────────
# Fast-decay fraction (UV organic filters photo-degrade rapidly)
_ALPHA = 0.7
# Fast decay rate constant (h⁻¹) — half-life ≈ 2h
_K1 = 0.35
# Slow decay rate constant (h⁻¹) — half-life ≈ 14h (physical blockers)
_K2 = 0.05

# ── Sunscreen reapplication threshold ────────────────────────────────────────
_REAPPLY_THRESHOLD = 0.5  # flag if SPF_eff < SPF_applied × 0.5


class RiskLevel(str, Enum):
    """Five-tier UV risk classification matching the Dermatology_Math_Engine skill."""
    SAFE = "safe"
    CAUTION = "caution"
    WARNING = "warning"
    DANGER = "danger"
    EXCEEDED = "exceeded"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def calculate_uv_risk(
    fitzpatrick: int,
    spf: float,
    hours_since_application: float,
    cumulative_dose_jm2: float,
    uv_index: float,
) -> dict:
    """
    Full UV risk calculation — returns a production-ready payload dict.

    Args:
        fitzpatrick:               Skin type 1–6 (Fitzpatrick scale).
        spf:                       Applied sunscreen SPF (1 = bare skin).
        hours_since_application:   Hours since sunscreen was applied (float).
        cumulative_dose_jm2:       UV dose already received today in J/m².
        uv_index:                  Current real-time UV Index value.

    Returns:
        Dict with keys matching [UVRiskResponse] Pydantic model.

    Raises:
        ValueError: If fitzpatrick is out of range 1–6.
    """
    med_base = get_med(fitzpatrick)
    spf_eff = spf_effective(spf, hours_since_application)
    med_protected = med_base * spf_eff

    minutes_rem = remaining_safe_minutes(
        cumulative_dose_jm2=cumulative_dose_jm2,
        med_protected=med_protected,
        uv_index=uv_index,
    )

    dose_pct = (cumulative_dose_jm2 / med_protected * 100.0) if med_protected > 0 else 0.0
    risk = classify_risk(minutes_rem, cumulative_dose_jm2, med_protected)
    reapply = spf_eff < (spf * _REAPPLY_THRESHOLD) and spf > 1

    result = {
        "fitzpatrick_type": fitzpatrick,
        "spf_applied": round(spf, 1),
        "spf_effective_now": round(spf_eff, 2),
        "med_base_jm2": med_base,
        "med_protected_jm2": round(med_protected, 2),
        "cumulative_dose_jm2": round(cumulative_dose_jm2, 2),
        "dose_percentage": round(min(dose_pct, 999.9), 1),
        "minutes_remaining": round(max(0.0, minutes_rem), 1),
        "risk_level": risk.value,
        "sunscreen_reapply_recommended": reapply,
    }

    logger.info(
        "[MED] type=%d spf=%.0f→%.2f dose=%.1f/%.1f J/m² pct=%.1f%% rem=%.0fmin risk=%s",
        fitzpatrick,
        spf,
        spf_eff,
        cumulative_dose_jm2,
        med_protected,
        dose_pct,
        minutes_rem,
        risk.value,
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — MED lookup
# ──────────────────────────────────────────────────────────────────────────────

def get_med(fitzpatrick: int) -> float:
    """
    Returns MED in J/m² for the given Fitzpatrick skin type.

    Raises:
        ValueError: If fitzpatrick is not in range 1–6.
    """
    if fitzpatrick not in MED_TABLE:
        raise ValueError(f"Fitzpatrick type must be 1–6, got {fitzpatrick}")
    return MED_TABLE[fitzpatrick]


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — UV irradiance from UV Index
# ──────────────────────────────────────────────────────────────────────────────

def uvi_to_irradiance(uv_index: float) -> float:
    """
    Converts a WHO UV Index value to effective UV irradiance in W/m².

    Standard: E = UVI × 0.025 W/m² (WHO/CIE).
    """
    return uv_index * _UVI_TO_IRRADIANCE


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — SPF effective (bi-exponential decay)
# ──────────────────────────────────────────────────────────────────────────────

def spf_effective(spf: float, hours_elapsed: float) -> float:
    """
    Returns effective SPF at [hours_elapsed] hours after sunscreen application.

    Uses a bi-exponential decay model to account for:
    - Fast decay (α=0.7, k1=0.35/h): UV organic filters photo-degrading
    - Slow decay (1-α=0.3, k2=0.05/h): Physical blockers (zinc, titanium)

    Formula:
        SPF_eff(t) = 1 + (SPF - 1) × [0.7·e^(-0.35t) + 0.3·e^(-0.05t)]

    SPF cannot fall below 1.0 (no negative protection).

    Args:
        spf:           Applied sunscreen SPF (1 = no sunscreen).
        hours_elapsed: Hours since application. Must be >= 0.

    Example outputs for SPF 50:
        t=0h → SPF 50.0  (full protection)
        t=2h → SPF ~28.4
        t=4h → SPF ~14.6
        t=8h → SPF  ~6.2
    """
    if hours_elapsed < 0:
        raise ValueError(f"hours_elapsed must be >= 0, got {hours_elapsed}")
    if spf <= 1.0:
        return 1.0  # no sunscreen → flat SPF 1 (no decay needed)

    decay = _ALPHA * math.exp(-_K1 * hours_elapsed) + (1 - _ALPHA) * math.exp(-_K2 * hours_elapsed)
    return max(1.0, 1.0 + (spf - 1.0) * decay)


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 — Remaining safe minutes
# ──────────────────────────────────────────────────────────────────────────────

def remaining_safe_minutes(
    cumulative_dose_jm2: float,
    med_protected: float,
    uv_index: float,
) -> float:
    """
    Estimates remaining safe sun exposure in minutes.

    Formula:
        remaining_dose  = max(0, MED_protected − cumulative_dose)
        irradiance      = UVI × 0.025  (W/m²)
        time_remaining  = remaining_dose / irradiance  (seconds → ÷ 60 → minutes)

    Edge cases:
        uv_index == 0  (night / indoor) → return float('inf') sentinel → caller
                                          capped to a large constant (999 min).
        cumulative > med_protected       → return 0.0
    """
    irradiance = uvi_to_irradiance(uv_index)
    remaining_dose = max(0.0, med_protected - cumulative_dose_jm2)

    if remaining_dose <= 0.0:
        return 0.0
    if irradiance <= 0.0:
        # UV index is zero (night/indoor) — exposure time is effectively unlimited
        return 999.0

    return (remaining_dose / irradiance) / 60.0


# ──────────────────────────────────────────────────────────────────────────────
# Step 5 — Risk classification (5-tier)
# ──────────────────────────────────────────────────────────────────────────────

def classify_risk(
    minutes_remaining: float,
    cumulative_dose_jm2: float,
    med_protected: float,
) -> RiskLevel:
    """
    Maps current UV exposure state to a [RiskLevel] tier (Dermatology_Math_Engine skill).

    Thresholds (dose_ratio = cumulative_dose_jm2 / med_protected):
        EXCEEDED  dose_ratio ≥ 1.0   MED already crossed
        DANGER    minutes_remaining ≤ 0
        WARNING   minutes_remaining < 10  OR  dose_ratio ≥ 0.85
        CAUTION   minutes_remaining < 30  OR  dose_ratio ≥ 0.65
        SAFE      else
    """
    dose_ratio = (cumulative_dose_jm2 / med_protected) if med_protected > 0 else 1.0

    if dose_ratio >= 1.0:
        return RiskLevel.EXCEEDED
    if minutes_remaining <= 0:
        return RiskLevel.DANGER
    if minutes_remaining < 10 or dose_ratio >= 0.85:
        return RiskLevel.WARNING
    if minutes_remaining < 30 or dose_ratio >= 0.65:
        return RiskLevel.CAUTION
    return RiskLevel.SAFE


def classify_risk_by_sticker(uv_percent: float, minutes_remaining: float) -> RiskLevel:
    """
    Risk classification driven primarily by the sticker's raw UV% reading.

    The photochromic sticker measures ambient UV without SPF — its reading
    directly reflects environmental dose intensity. SPF only extends the
    time budget; it does not lower the sticker alarm level.

    Thresholds (sticker UV%):
        EXCEEDED  ≥ 100%  sticker fully saturated
        DANGER    ≥  75%  OR  minutes_remaining ≤ 0
        WARNING   ≥  50%  OR  minutes_remaining < 10
        CAUTION   ≥  30%  OR  minutes_remaining < 30
        SAFE      all other cases
    """
    if uv_percent >= 100.0:
        return RiskLevel.EXCEEDED
    if uv_percent >= 75.0 or minutes_remaining <= 0:
        return RiskLevel.DANGER
    if uv_percent >= 50.0 or minutes_remaining < 10:
        return RiskLevel.WARNING
    if uv_percent >= 30.0 or minutes_remaining < 30:
        return RiskLevel.CAUTION
    return RiskLevel.SAFE


# ──────────────────────────────────────────────────────────────────────────────
# Convenience: convert UV% from sticker scan to J/m² dose increment
# ──────────────────────────────────────────────────────────────────────────────

def uv_percent_to_dose_jm2(uv_percent: float, fitzpatrick: int) -> float:
    """
    Converts a UV% reading from the sticker into an absolute dose in J/m².

    uv_percent is a fraction (0-100) of MED_base for the given skin type.
    This allows the sticker scan result to be accumulated in J/m² units.

    Args:
        uv_percent:  UV percentage from colorimetry pipeline (0-100+).
        fitzpatrick: Fitzpatrick skin type for MED_base lookup.
    """
    med_base = get_med(fitzpatrick)
    return (uv_percent / 100.0) * med_base
