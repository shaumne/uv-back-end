"""
POST /api/v1/detect — Lightweight sticker presence check.

Accepts a single camera frame (JPEG/PNG) and returns whether a valid
photochromic sticker was detected, with a confidence score.

Design intent (v4):
  Strict contour detection is applied to prevent false positives (e.g. purple
  clothing, random purple regions). Only images that pass shape checks (aspect
  ratio, solidity, fill ratio, minimum area) return detected=True; otherwise
  detected=False with a descriptive reason. This avoids sending non-sticker
  regions to /analyze and keeps the pipeline predictable. Unusable images
  (too dark, corrupt, invalid format) also return detected=False.

Request body (multipart/form-data):
    image: UploadFile       — camera frame JPEG/PNG
    pre_cropped: str | None — if 'true', image is already cropped to guide ROI
    ambient_lux: float      — ambient light in lux (optional; used for adaptive mask)

Response (200):
    {
        "detected": bool,      # true only when contour passes all shape checks
        "confidence": float,   # 0.5 – 1.0 when detected; 0.0 when not
        "reason": str | null   # null on clean detection; code otherwise
    }
"""
import logging

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ....services.colorimetry_service import detect_sticker_presence
from ....utils.image_validator import validate_image

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class DetectResponse(BaseModel):
    detected: bool
    confidence: float
    reason: str | None = None


@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Lightweight sticker presence detection for live camera feedback",
    status_code=status.HTTP_200_OK,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit("60/minute")
async def detect_sticker(
    request: Request,
    image: UploadFile = File(..., description="Camera preview frame (JPEG/PNG)"),
    pre_cropped: str | None = Form(None, description="If 'true', image is already cropped to guide ROI"),
    ambient_lux: float = Form(1000.0, description="Ambient light sensor reading in lux (for adaptive HSV mask)"),
) -> DetectResponse:
    """
    Runs only the sticker-isolation step of the colorimetry pipeline.

    - No K-Means clustering.
    - No MED/SPF computation.
    - Returns within ~100–250 ms per frame on typical hardware.

    The endpoint always returns HTTP 200 — the `detected` flag carries the
    result so the mobile client never needs to handle unexpected error codes
    from this lightweight check.
    """
    try:
        image_bytes = await image.read()
    except Exception as exc:
        logger.warning("[Detect] Failed to read image bytes: %s", exc)
        return DetectResponse(detected=False, confidence=0.0, reason="read_error")

    # Validate image size / format to prevent abuse; soft-fail on rejection.
    try:
        validate_image(image_bytes)
    except ValueError as exc:
        logger.debug("[Detect] Image validation failed: %s", exc)
        return DetectResponse(detected=False, confidence=0.0, reason=str(exc))

    use_full_roi = (pre_cropped or "").strip().lower() == "true"
    result = detect_sticker_presence(
        image_bytes,
        ambient_lux=ambient_lux,
        pre_cropped=use_full_roi,
    )
    logger.debug(
        "[Detect] detected=%s confidence=%.2f reason=%s",
        result["detected"], result["confidence"], result.get("reason"),
    )
    return DetectResponse(**result)
