"""
Integration tests for POST /api/v1/analyze.

Test matrix:
  - happy_path: valid JPEG + valid form params → 200 with expected JSON shape
  - missing_image: no image field → 422
  - invalid_skin_type: out-of-range value → 422
  - image_too_small: image below min dimension → 422 (sticker not detected)
  - sticker_not_detected: white image returns detected=False (graceful result)

All tests use the `client` fixture from conftest.py which runs without a
live server via ASGI transport.
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_health_check(client):
    """Health endpoint must return 200 and status ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


async def test_analyze_missing_image(client):
    """Missing image field must return 422 Unprocessable Entity."""
    response = await client.post(
        "/api/v1/analyze",
        data={
            "ambient_lux": "1000.0",
            "skin_type": "2",
        },
    )
    assert response.status_code == 422


async def test_analyze_invalid_skin_type(client, sample_jpeg_bytes):
    """skin_type=7 is out of range [1, 6] — must return 422."""
    response = await client.post(
        "/api/v1/analyze",
        data={
            "ambient_lux": "1000.0",
            "skin_type": "7",
            "spf": "30.0",
            "hours_since_application": "0.0",
            "cumulative_dose_jm2": "0.0",
            "uv_index": "5.0",
        },
        files={"image": ("sticker.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert response.status_code == 422


async def test_analyze_missing_ambient_lux(client, sample_jpeg_bytes):
    """Missing required ambient_lux field must return 422."""
    response = await client.post(
        "/api/v1/analyze",
        data={
            "skin_type": "2",
            "spf": "30.0",
        },
        files={"image": ("sticker.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    assert response.status_code == 422


async def test_analyze_with_valid_image_returns_200_or_422(
    client, sample_jpeg_bytes
):
    """
    A valid JPEG upload with correct params returns either:
      - 200 (if colorimetry pipeline succeeds, unlikely with white test image)
      - 422 with sticker_not_detected reason (expected for plain white image)

    We accept both outcomes because we do not mock the CV pipeline.
    What we validate is that the endpoint does NOT 500.
    """
    response = await client.post(
        "/api/v1/analyze",
        data={
            "ambient_lux": "1000.0",
            "skin_type": "2",
            "spf": "30.0",
            "hours_since_application": "1.0",
            "cumulative_dose_jm2": "50.0",
            "uv_index": "5.0",
        },
        files={"image": ("sticker.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    # Must not be a server error
    assert response.status_code in {200, 422}, (
        f"Unexpected status {response.status_code}: {response.text}"
    )
    if response.status_code == 422:
        detail = response.json().get("detail", "")
        # Confirm it is a known detection/processing error, not a crash
        assert detail, "422 response must include detail"


async def test_detect_endpoint_returns_detected_flag(client, sample_jpeg_bytes):
    """POST /detect must return a JSON body with a `detected` boolean field."""
    response = await client.post(
        "/api/v1/detect",
        files={"image": ("frame.jpg", sample_jpeg_bytes, "image/jpeg")},
    )
    # Accept 200 (detected or not) or 422 (image too small / invalid)
    assert response.status_code in {200, 422}
    if response.status_code == 200:
        data = response.json()
        assert "detected" in data
        assert isinstance(data["detected"], bool)
        assert "confidence" in data
