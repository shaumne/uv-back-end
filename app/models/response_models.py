"""
Pydantic response models returned to the Flutter client.

AnalyzeResponse merges both skill schemas:
- ComputerVision_Colorimetry: hex_color, uv_percent
- Dermatology_Math_Engine: full MED/SPF/risk payload
"""
from pydantic import BaseModel, Field


class AnalyzeResponse(BaseModel):
    """
    Full UV analysis response — returned by POST /api/v1/analyze.

    Colorimetry fields:
        hex_color:   Dominant sticker colour extracted by OpenCV K-Means.
        uv_percent:  UV exposure percentage derived from L* interpolation.

    Dermatology fields (all units documented inline):
        fitzpatrick_type:          Echoed from request for client validation.
        spf_applied:               Echoed from request.
        spf_effective_now:         Current effective SPF after degradation.
        med_base_jm2:              MED baseline for this Fitzpatrick type (J/m²).
        med_protected_jm2:         MED × SPF_effective — the user's actual limit.
        cumulative_dose_jm2:       Total UV dose received today (J/m²).
        dose_percentage:           cumulative / med_protected × 100 (0–999+).
        minutes_remaining:         Safe sun exposure time left (minutes).
        risk_level:                One of: safe | caution | warning | danger | exceeded
        sunscreen_reapply_recommended: True when SPF_eff < SPF_applied × 0.5.

    Sticker/cilt ayrışımı için ek alanlar:
        sticker_dose_jm2:               Sticker okumasından türetilen doz (J/m²).
        previous_cumulative_dose_jm2:   İstekle gelen kümülatif doz (J/m²).
        sticker_reset_suspected:        Sticker okuması belirgin şekilde düşükse True.
    """
    # ── Colorimetry ───────────────────────────────────────────────────────────
    hex_color: str = Field(..., description="Dominant sticker colour in #RRGGBB format")
    uv_percent: float = Field(..., ge=0, description="UV exposure % from L* calibration curve")

    # ── Dermatology ───────────────────────────────────────────────────────────
    fitzpatrick_type: int = Field(..., ge=1, le=6)
    spf_applied: float = Field(..., ge=1)
    spf_effective_now: float = Field(..., ge=1, description="Current SPF after bi-exponential decay")
    med_base_jm2: float = Field(..., description="Fitzpatrick MED baseline (J/m²)")
    med_protected_jm2: float = Field(..., description="MED × SPF_effective (J/m²)")
    cumulative_dose_jm2: float = Field(..., ge=0, description="Total dose accumulated today (J/m²)")
    dose_percentage: float = Field(..., ge=0, description="% of daily limit consumed")
    minutes_remaining: float = Field(..., ge=0, description="Estimated safe exposure time left")
    risk_level: str = Field(..., pattern="^(safe|caution|warning|danger|exceeded)$")
    sunscreen_reapply_recommended: bool = Field(
        ..., description="True when SPF degradation exceeds 50% of original"
    )

    # ── Sticker / cilt ayrışımı metadatası ──────────────────────────────────────
    sticker_dose_jm2: float = Field(
        ...,
        ge=0,
        description="Dose implied by current sticker reading (J/m²)",
    )
    previous_cumulative_dose_jm2: float = Field(
        ...,
        ge=0,
        description="Cumulative dose value sent by client before this scan (J/m²)",
    )
    sticker_reset_suspected: bool = Field(
        ...,
        description=(
            "True when sticker_dose_jm2 is significantly lower than the previous "
            "cumulative dose, suggesting a new sticker or anomalous reading."
        ),
    )


class ErrorResponse(BaseModel):
    detail: str
    code: str
