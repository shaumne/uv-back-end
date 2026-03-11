"""
POST /api/v1/analyze — Sticker UV analysis endpoint.

Accepts a multipart/form-data request:
    image                 : JPEG/PNG camera capture of the photochromic sticker
    ambient_lux           : Ambient light sensor reading (float)
    skin_type             : Fitzpatrick skin type 1–6 (int)
    spf                   : Sunscreen SPF factor (int, default 1)
    hours_since_application: Hours since sunscreen was applied (float, default 0)
    cumulative_dose_jm2   : UV dose already received today in J/m² (float, default 0)
    uv_index              : Current real-time UV Index (float, default 5.0)

Returns [AnalyzeResponse] — full merged colorimetry + dermatology payload.
"""
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from ....models.response_models import AnalyzeResponse
from ....services.colorimetry_service import compute_delta_uv_stress, extract_sticker_data
from ....services.med_calculator import calculate_uv_risk, classify_risk_by_sticker, uv_percent_to_dose_jm2
from ....utils.image_validator import validate_image

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyse photochromic sticker and compute UV dose",
    status_code=status.HTTP_200_OK,
    responses={
        422: {"description": "Image validation or sticker detection failure"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal image processing error"},
    },
)
@limiter.limit("10/minute")
async def analyze_sticker(
    request: Request,
    image: UploadFile = File(..., description="Camera image of the UV sticker patch"),
    ambient_lux: float = Form(..., ge=0, description="Ambient light in lux"),
    skin_type: int = Form(..., ge=1, le=6, description="Fitzpatrick skin type"),
    spf: float = Form(default=1.0, ge=1, le=100, description="SPF factor"),
    hours_since_application: float = Form(default=0.0, ge=0, description="Hours since sunscreen applied"),
    cumulative_dose_jm2: float = Form(
        default=0.0,
        ge=0,
        description="Reserved; sticker reading is used as cumulative dose (J/m²) for this scan",
    ),
    uv_index: float = Form(default=5.0, ge=0, description="Current UV Index"),
    pre_cropped: str | None = Form(None, description="If 'true', image is already cropped to guide ROI"),
    daily_context: str | None = Form(None, description="beach_swimming | intense_sport | daily_city"),
    albedo: str | None = Form(None, description="none | snow | sand (ground reflection)"),
) -> AnalyzeResponse:
    """
    Full analysis pipeline:

    1. Validate uploaded image (size, format, dimensions).
    2. Extract sticker hex colour and UV% via OpenCV colorimetry.
    3. Convert UV% → J/m² dose increment for the user's skin type.
    4. Accumulate with today's cumulative dose.
    5. Run MED/SPF dermatology calculation.
    6. Return merged JSON response.
    """
    # ── Step 1: Read and validate image ──────────────────────────────────────
    try:
        image_bytes = await image.read()
    except Exception as exc:
        logger.error("Failed to read uploaded image: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded image.",
        ) from exc

    try:
        validate_image(image_bytes)
    except ValueError as exc:
        logger.warning("Image validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # ── Step 2: Colorimetry — hex + UV% ───────────────────────────────────────
    use_full_roi = (pre_cropped or "").strip().lower() == "true"
    try:
        hex_color, uv_percent = extract_sticker_data(
            image_bytes, ambient_lux, pre_cropped=use_full_roi
        )
    except ValueError as exc:
        err_str = str(exc)
        logger.warning("Colorimetry failed: %s", err_str)
        # Map known error codes to specific 422 detail messages
        if "sticker_not_detected" in err_str:
            detail = "Sticker not detected. Ensure the sticker is inside the frame."
        elif "sticker_too_small" in err_str:
            detail = "Sticker area too small. Hold the camera closer."
        elif "too dark" in err_str:
            detail = "Image too dark. Move to better lighting and retry."
        else:
            detail = f"Sticker colour extraction failed: {err_str}"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during colour extraction.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal image processing error.",
        ) from exc

    # ── Step 3: Sticker UV% → cumulative dose (J/m²) ────────────────────────────
    # The photochromic sticker reading is cumulative (total exposure so far), not
    # an increment. So cumulative_dose_jm2 for this reading = (uv_percent/100)*MED_base.
    # We use the sticker-derived value as the cumulative; do not add to client
    # value to avoid double-counting when the user rescans.
    try:
        scan_dose_jm2 = uv_percent_to_dose_jm2(uv_percent, skin_type)
        updated_cumulative = scan_dose_jm2
    except ValueError as exc:
        logger.error("Dose conversion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # ── Step 4: MED / SPF calculation (with daily context & albedo) ─────────────
    try:
        risk_payload = calculate_uv_risk(
            fitzpatrick=skin_type,
            spf=spf,
            hours_since_application=hours_since_application,
            cumulative_dose_jm2=updated_cumulative,
            uv_index=uv_index,
            daily_context=daily_context,
            albedo=albedo,
        )
    except ValueError as exc:
        logger.error("MED calculation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # ── Step 5: Override risk level with sticker-driven classifier ───────────
    # The sticker measures raw ambient UV without SPF attenuation.
    # SPF is correctly used for minutes_remaining, but the danger alarm must
    # reflect what the sticker reports — otherwise SPF 30 always shows "safe"
    # even when the sticker is fully saturated.
    sticker_risk = classify_risk_by_sticker(
        uv_percent=uv_percent,
        minutes_remaining=risk_payload["minutes_remaining"],
    )
    risk_payload["risk_level"] = sticker_risk.value

    # dose_percentage shown to user = sticker UV%, not SPF-adjusted fraction.
    # This ensures the displayed percentage matches what the sticker reads.
    risk_payload["dose_percentage"] = round(min(uv_percent, 999.9), 1)

    # Exclude extra keys not in AnalyzeResponse schema
    for key in ("daily_context", "albedo"):
        risk_payload.pop(key, None)

    return AnalyzeResponse(
        hex_color=hex_color,
        uv_percent=uv_percent,
        **risk_payload,
    )


@router.post(
    "/delta",
    summary="Delta UV stress analysis (baseline vs evening)",
    status_code=status.HTTP_200_OK,
    responses={
        422: {"description": "Image validation failure"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit("10/minute")
async def analyze_delta(
    request: Request,
    baseline_image: UploadFile = File(..., description="Morning/baseline skin photo"),
    evening_image: UploadFile = File(..., description="Evening skin photo"),
    ambient_lux_baseline: float = Form(default=1000.0, ge=0),
    ambient_lux_evening: float = Form(default=1000.0, ge=0),
) -> dict:
    """
    Delta analysis: Red channel difference between baseline (morning) and evening.
    Output: percentage change in UV stress — NOT medical diagnosis.
    """
    try:
        baseline_bytes = await baseline_image.read()
        evening_bytes = await evening_image.read()
    except Exception as exc:
        logger.error("Failed to read delta images: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read uploaded images.",
        ) from exc

    for name, data in [("baseline", baseline_bytes), ("evening", evening_bytes)]:
        try:
            validate_image(data)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{name}: {exc}",
            ) from exc

    try:
        result = compute_delta_uv_stress(
            baseline_image_bytes=baseline_bytes,
            evening_image_bytes=evening_bytes,
            ambient_lux_baseline=ambient_lux_baseline,
            ambient_lux_evening=ambient_lux_evening,
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
