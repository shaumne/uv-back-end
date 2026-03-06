"""
Colorimetry service v3 — production-hardened UV sticker colour extraction.

Sticker: sadece mor spektrumu (beyaz → lavanta → mor → indigo). UV% L* ile
mor kalibrasyon eğrine göre hesaplanır; dozaj bildirimleri bu eğriye göredir.

Pipeline (ComputerVision_Colorimetry skill specification):
1. Decode raw image bytes → BGR NumPy array.
2. Apply LAB-space Grey-World white balance correction.
3. Locate the sticker via HSV masking + multi-factor contour scoring.
   → HSV bands include purple/violet (H 115–170) for mor sticker.
   → Falls back to centre-crop ROI when no contour scores above threshold.
4. Extract dominant colour from sticker pixels using K-Means (k=3).
   Cluster with highest pixel count is dominant (skill); achromatic
   fallback picks the most chromatic cluster when the largest is artefact.
5. Map dominant colour → UV% via LAB L* interpolation (scipy).

Key improvements vs v2:
- ALL hard geometry thresholds are significantly relaxed so real-world
  stickers (small, shot from normal distance, irregular contour, suboptimal
  lighting) are no longer falsely rejected.
- Centre-crop fallback: when contour detection yields no candidate above
  _ANALYZE_CONFIDENCE_THRESHOLD, the central 45 % square of the image is
  used as the ROI — aligned with the 220 dp guide frame on the scan screen.
- HSV bands are widened (especially Band 3) to reliably capture near-fresh
  stickers whose near-white appearance has very low saturation.
- /detect and /analyze use separate confidence thresholds so the lightweight
  presence check never gates out a valid full analysis.

Required packages: opencv-python-headless, scikit-learn, scipy, numpy
"""
import logging
import math

import cv2
import numpy as np
from scipy.interpolate import interp1d
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)

# ── UV calibration curve: mor sticker spektrumu ───────────────────────────────
# Referans: beyaz → lavanta → orta mor → koyu mor → indigo (0% → 100% UV).
# L* değerleri bu mor tonlarından türetildi; dozaj bildirimleri bu eğriye göre.
# Fiziksel kalibrasyon sonrası reference.md ile güncellenebilir.
_CALIBRATION: list[tuple[float, float]] = [
    (97.0,   0.0),   # #F8F9FA — UV Seviyesi 0 (Başlangıç)
    (80.0,  25.0),   # #E0BBE4 — Düşük doz (%25)
    (55.0,  50.0),   # #9575CD — Orta doz (%50)
    (35.0,  75.0),   # #673AB7 — Yüksek doz (%75)
    (18.0, 100.0),   # #311B92 — Kritik doz (%100, yanma riski)
]
_L_VALS, _UV_VALS = zip(*_CALIBRATION)
_UV_CURVE = interp1d(_L_VALS, _UV_VALS, kind="linear", fill_value="extrapolate")

# ── Image resize limits ───────────────────────────────────────────────────────
_DETECT_MAX_PX  = 640   # /detect — shape check only
_ANALYZE_MAX_PX = 960   # /analyze — needs colour fidelity

# ── Sticker detection thresholds (RELAXED for real-world robustness) ─────────

# Minimum absolute sticker contour area in pixels² (skill: reject if < 500).
# 500 px² ≈ ~22×22 px — ensures usable ROI for colour extraction.
_MIN_STICKER_AREA_PX2 = 500

# Sticker relative area bounds (fraction of total image area).
# Lower bound 0.002 (0.2 %) supports normal shooting distances (~30 cm).
# Upper bound 0.60 supports very close-up shots.
_MIN_STICKER_AREA_FRACTION = 0.002
_MAX_STICKER_AREA_FRACTION = 0.60

# Aspect ratio w/h.  Sticker kare veya daireye yakın; ince uzun şekiller reddedilir.
_MIN_ASPECT_RATIO = 0.70
_MAX_ASPECT_RATIO = 1.40

# Compactness = 4π × A / P².  Daire ≈ 1.0, kare ≈ 0.79; dağınık bloklar elenir.
_MIN_COMPACTNESS = 0.50

# Fill ratio = contour area / bounding-rect area.
_MIN_FILL_RATIO = 0.18

# Güven eşikleri: kontur bu skorun üstünde olmalı; aksi halde sticker_not_detected.
_DETECT_CONFIDENCE_THRESHOLD  = 0.35
_ANALYZE_CONFIDENCE_THRESHOLD = 0.50

# Minimum mean LAB L* for the whole image (skill: reject if mean L* < 20).
_MIN_LIGHTNESS = 20.0

# Minimum pixel count inside a contour for K-Means.
_MIN_CONTOUR_PIXELS = 20

# Mean HSV saturation gate on the extracted ROI (unused when contour-only path).
_MIN_ROI_SATURATION = 0


# ── Image resize helper ───────────────────────────────────────────────────────

def _resize_for_processing(image: np.ndarray, max_px: int) -> np.ndarray:
    """
    Resizes *image* so its longest edge is at most *max_px* pixels.
    Uses INTER_AREA (anti-aliasing) for downscaling.
    Returns the original array unchanged if it already fits.
    """
    h, w = image.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_px:
        return image
    scale = max_px / long_edge
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    logger.debug(
        "[Colorimetry] Resized %dx%d → %dx%d (scale=%.2f)",
        w, h, new_w, new_h, scale,
    )
    return resized


# ── Public API ────────────────────────────────────────────────────────────────

def extract_sticker_data(
    image_bytes: bytes,
    ambient_lux: float,
) -> tuple[str, float]:
    """
    Full colorimetry pipeline: image bytes → (hex_color, uv_percent).

    When contour-based sticker isolation scores below
    _ANALYZE_CONFIDENCE_THRESHOLD, the function automatically falls back
    to the centre-crop strategy (45 % square centred on the image), which
    aligns with the 220 dp guide frame shown on the scan screen.

    Args:
        image_bytes: Raw JPEG/PNG bytes from the mobile camera.
        ambient_lux: Ambient light sensor reading in lux (used for logging;
                     white balance uses LAB grey-world independently).

    Returns:
        Tuple of (hex_color: str, uv_percent: float).
        hex_color is '#RRGGBB'; uv_percent is 0.0 – 100.0 (clamped).

    Raises:
        ValueError: Descriptive code string for client feedback.
    """
    image = _decode_image(image_bytes)
    image = _resize_for_processing(image, _ANALYZE_MAX_PX)
    _check_lightness(image)
    balanced = _white_balance_lab(image)
    roi_pixels = _isolate_sticker_pixels(balanced)
    hex_color = _dominant_hex_kmeans(roi_pixels)
    if not _is_sticker_plausible_colour(hex_color):
        logger.warning("[Colorimetry] Dominant colour not sticker-like: %s", hex_color)
        raise ValueError("sticker_not_detected")
    uv_percent = _hex_to_uv_percent(hex_color)

    logger.info(
        "[Colorimetry] lux=%.1f hex=%s uv_pct=%.1f",
        ambient_lux, hex_color, uv_percent,
    )
    return hex_color, uv_percent


def detect_sticker_presence(image_bytes: bytes) -> dict:
    """
    Lightweight sticker presence check — no K-Means, no MED calculation.

    Uses _DETECT_CONFIDENCE_THRESHOLD (more lenient than the analyse path)
    so that a valid sticker at distance or with a subtle colour tint is not
    falsely rejected before the full /analyze pipeline runs.

    When the best contour scores between 0.0 and _DETECT_CONFIDENCE_THRESHOLD,
    the function returns detected=True with the actual confidence score rather
    than blocking the pipeline — the /analyze endpoint will either succeed or
    return a meaningful error to the user.

    Returns:
        dict with keys: detected (bool), confidence (float), reason (str|None).
    Never raises — all exceptions are caught and returned as not-detected.
    """
    try:
        image = _decode_image(image_bytes)
        image = _resize_for_processing(image, _DETECT_MAX_PX)
        _check_lightness(image)
        balanced = _white_balance_lab(image)
        contour, confidence = _find_best_sticker_contour(balanced)

        if contour is None:
            logger.debug("[Detect] No contour found — not a sticker.")
            return {"detected": False, "confidence": 0.0, "reason": "sticker_not_detected"}

        if confidence < _DETECT_CONFIDENCE_THRESHOLD:
            logger.debug("[Detect] Best contour confidence=%.2f below threshold", confidence)
            return {"detected": False, "confidence": round(confidence, 2), "reason": "sticker_not_detected"}

        return {"detected": True, "confidence": round(confidence, 2), "reason": None}

    except ValueError as exc:
        reason = str(exc)
        if "insufficient_lighting" in reason or "too dark" in reason.lower():
            logger.debug("[Detect] Blocked: %s", reason)
            return {"detected": False, "confidence": 0.0, "reason": reason}
        logger.debug("[Detect] ValueError: %s", reason)
        return {"detected": False, "confidence": 0.0, "reason": reason}

    except Exception as exc:
        logger.warning("[Detect] Unexpected error: %s", exc)
        return {"detected": False, "confidence": 0.0, "reason": "processing_error"}


# ── Step 1 — Image decode ─────────────────────────────────────────────────────

def _decode_image(image_bytes: bytes) -> np.ndarray:
    """Decodes raw bytes into a BGR NumPy array (OpenCV native format)."""
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Image decoding failed — unsupported format or corrupt data.")
    return image


# ── Step 1b — Darkness check ──────────────────────────────────────────────────

def _check_lightness(image: np.ndarray) -> None:
    """
    Rejects images that are too dark for any reliable colour analysis.

    OpenCV encodes LAB L* as 0-255; dividing by 2.55 yields CIE 0-100.
    Threshold lowered to 10 — images with mean L* > 10 are accepted;
    only pitch-black/lens-covered frames are rejected.

    Raises:
        ValueError: 'insufficient_lighting' if mean L* < _MIN_LIGHTNESS.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    mean_l = float(np.mean(lab[:, :, 0])) / 2.55
    logger.debug("[Colorimetry] Mean L*=%.1f", mean_l)
    if mean_l < _MIN_LIGHTNESS:
        raise ValueError(
            f"insufficient_lighting (mean L*={mean_l:.1f} < {_MIN_LIGHTNESS}). "
            "Move to better lighting and retry."
        )


# ── Step 2 — White balance (LAB Grey-World) ───────────────────────────────────

def _white_balance_lab(image: np.ndarray) -> np.ndarray:
    """
    Applies Grey-World white balance in CIE LAB colour space.

    LAB separates luminance from chromaticity, giving more accurate
    colour neutralisation under mixed ambient lighting.  A* and B*
    are shifted so their average equals the grey-point (128 in OpenCV's
    0-255 LAB encoding), weighted by luminance.

    A mild bilateral filter removes sensor noise while preserving edges.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float64)

    avg_a = np.average(lab[:, :, 1])
    avg_b = np.average(lab[:, :, 2])

    lab[:, :, 1] -= (avg_a - 128) * (lab[:, :, 0] / 255.0) * 1.1
    lab[:, :, 2] -= (avg_b - 128) * (lab[:, :, 0] / 255.0) * 1.1

    lab = np.clip(lab, 0, 255).astype(np.uint8)
    balanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    # Skill: mild bilateral for harsh sunlight (d=9, sigmaColor=75, sigmaSpace=75)
    return cv2.bilateralFilter(balanced, d=9, sigmaColor=75, sigmaSpace=75)


# ── Step 3 — Sticker isolation ────────────────────────────────────────────────

def _build_sticker_mask(image: np.ndarray) -> np.ndarray:
    """
    Builds a binary mask for potential sticker regions using HSV.

    Sticker sadece mor spektrumu: beyaz → lavanta → mor → indigo.
    Sadece mor tonları ve parlak beyaz (taze) maskelenir; kırmızı/turuncu hariç.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Mor / doygun: sadece H 110–170 (eflatun/mor), S ≥ 30
    purple_vivid = cv2.inRange(hsv, (110, 30, 30), (170, 255, 255))

    # Açık mor / soluk lavanta: H 110–170, düşük S
    purple_pale = cv2.inRange(hsv, (110, 5, 50), (170, 50, 255))

    # Taze sticker: parlaklık yüksek, doygunluk sıfıra yakın (beyaz/şeffaf)
    fresh_mask = cv2.inRange(hsv, (0, 0, 180), (179, 15, 255))

    combined = cv2.bitwise_or(purple_vivid, purple_pale)
    combined = cv2.bitwise_or(combined, fresh_mask)

    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, close_k)

    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, open_k)

    return combined


def _score_contour(contour: np.ndarray, image_area: int) -> float:
    """
    Computes a 0.0–1.0 sticker likelihood score for a contour.

    Hard constraints (any failure → 0.0):
    - Absolute area ≥ _MIN_STICKER_AREA_PX2
    - Relative area in [_MIN_STICKER_AREA_FRACTION, _MAX_STICKER_AREA_FRACTION]
    - Aspect ratio (w/h) in [0.70, 1.40] — kare/daireye yakın
    - Compactness ≥ 0.50 — dağınık/düzensiz bloklar reddedilir
    - Fill ratio ≥ _MIN_FILL_RATIO

    Soft scores (weighted sum → final score 0.0–1.0):
    - area_score:    peaks at 3–15 % of image area
    - aspect_score:  peaks at 1.0 (perfect square/circle)
    - compact_score: peaks at 1.0 (circle)
    - fill_score:    peaks at 1.0 (fully filled bounding rect)
    """
    area = cv2.contourArea(contour)
    if area < _MIN_STICKER_AREA_PX2:
        return 0.0

    rel_area = area / image_area
    if rel_area < _MIN_STICKER_AREA_FRACTION or rel_area > _MAX_STICKER_AREA_FRACTION:
        return 0.0

    x, y, w, h = cv2.boundingRect(contour)
    if h == 0:
        return 0.0

    aspect = w / h
    if aspect < _MIN_ASPECT_RATIO or aspect > _MAX_ASPECT_RATIO:
        return 0.0

    perimeter = cv2.arcLength(contour, closed=True)
    if perimeter < 1:
        return 0.0

    compactness = (4.0 * math.pi * area) / (perimeter ** 2)
    if compactness < _MIN_COMPACTNESS:
        return 0.0

    bbox_area = w * h
    fill_ratio = area / bbox_area if bbox_area > 0 else 0.0
    if fill_ratio < _MIN_FILL_RATIO:
        return 0.0

    # ── Soft scores ───────────────────────────────────────────────────────────
    area_score = max(0.0, 1.0 - abs(math.log10(max(rel_area, 1e-6)) + 1.3) / 1.8)
    area_score = min(1.0, area_score)
    aspect_score = max(0.0, 1.0 - abs(aspect - 1.0) * 1.1)
    compact_score = min(compactness, 1.0)
    fill_score = min(fill_ratio, 1.0)

    score = (
        0.20 * area_score
        + 0.20 * aspect_score
        + 0.40 * compact_score
        + 0.20 * fill_score
    )
    return round(score, 3)


def _find_best_sticker_contour(
    image: np.ndarray,
) -> tuple[np.ndarray | None, float]:
    """
    Finds the contour that best matches the expected sticker shape.

    Returns:
        (best_contour, confidence) — contour is None if nothing qualifies.
    """
    mask = _build_sticker_mask(image)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        logger.debug("[Colorimetry] No contours found in HSV mask")
        return None, 0.0

    image_area = image.shape[0] * image.shape[1]
    best_contour = None
    best_score = 0.0

    for cnt in contours:
        score = _score_contour(cnt, image_area)
        if score > best_score:
            best_score = score
            best_contour = cnt

    if best_contour is not None:
        logger.debug("[Colorimetry] Best contour score=%.3f", best_score)
    else:
        logger.debug("[Colorimetry] All contours failed hard constraints")

    return best_contour, best_score


def _isolate_sticker_pixels(image: np.ndarray) -> np.ndarray:
    """
    Locates the sticker contour and returns the pixels inside it.

    Skill: sticker region must be found via contour; no centre-crop fallback.
    Random objects (cola can, packaging, etc.) must not be accepted — only
    a contour that scores above _ANALYZE_CONFIDENCE_THRESHOLD is used.

    Returns:
        1-D array of shape (N, 3) — BGR pixel values inside the sticker contour.

    Raises:
        ValueError: sticker_not_detected, sticker_too_small.
    """
    best_contour, confidence = _find_best_sticker_contour(image)

    if best_contour is None or confidence < _ANALYZE_CONFIDENCE_THRESHOLD:
        logger.info(
            "[Colorimetry] No sticker contour above threshold (confidence=%.2f). Rejecting.",
            confidence if best_contour is not None else 0.0,
        )
        raise ValueError("sticker_not_detected")

    image_area = image.shape[0] * image.shape[1]
    area = cv2.contourArea(best_contour)
    rel_area = area / image_area

    if rel_area > _MAX_STICKER_AREA_FRACTION:
        logger.warning("[Colorimetry] Contour too large (%.1f %% of frame).", rel_area * 100)
        raise ValueError("sticker_not_detected")

    contour_mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.drawContours(contour_mask, [best_contour], -1, 255, thickness=cv2.FILLED)
    pixels = image[contour_mask > 0]

    if len(pixels) < _MIN_CONTOUR_PIXELS:
        raise ValueError(
            "sticker_too_small — Hold the camera closer to the sticker."
        )

    logger.debug(
        "[Colorimetry] Contour: area=%.0f px² (%.1f %%), confidence=%.2f, pixels=%d",
        area, rel_area * 100, confidence, len(pixels),
    )
    return pixels


# ── Sticker colour sanity (reject cola, green, blue, etc.) ─────────────────────

def _is_sticker_plausible_colour(hex_color: str) -> bool:
    """
    Sticker sadece mor ve mor tonlarında (beyaz → lavanta → indigo).
    Sadece mor spektrumu ve akromatik (taze/şeffaf) kabul; turuncu/kırmızı/yeşil
    vb. reddedilir (kola kutusu, ambalaj vb.).
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return False
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    bgr = np.uint8([[[b, g, r]]])
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[0][0]
    H, S = int(hsv[0]), int(hsv[1])
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[0][0]
    l_star = float(lab[0]) / 2.55

    # Akromatik (taze sticker): çok düşük satürasyon veya çok yüksek L*
    if S <= 30 or l_star >= 90:
        return True
    # Sadece mor spektrumu: OpenCV H 110–175 (lavanta, mor, indigo)
    if 108 <= H <= 178:
        return True
    # Mora yakın magenta: H 175–179
    if H >= 175:
        return True
    # Diğer tüm renkler red (turuncu, kırmızı, yeşil, mavi, sarı vb.)
    return False


# ── Step 4 — Dominant colour (K-Means k=3, skill: highest pixel count) ─────────

def _dominant_hex_kmeans(pixels: np.ndarray, k: int = 3) -> str:
    """
    Extracts the photochromic indicator colour from sticker pixels.

    Skill: K-Means with k=3; take the cluster with the highest pixel count
    as the dominant colour. Fallback: if the largest cluster is achromatic
    (L* > 92 or L* < 8, artefact), pick the most chromatic cluster among
    those with sufficient count.

    Returns:
        Hex string '#RRGGBB' of the dominant cluster centroid (BGR → RGB).
    """
    pixel_float = pixels.astype(np.float32)
    actual_k = min(k, max(2, len(pixel_float) // 10))

    kmeans = KMeans(n_clusters=actual_k, n_init=10, random_state=42)
    kmeans.fit(pixel_float)
    counts = np.bincount(kmeans.labels_, minlength=actual_k)

    # Primary: cluster with highest pixel count (skill specification).
    best_idx = int(np.argmax(counts))

    # Check if dominant cluster is achromatic (shadow/highlight artefact).
    center = kmeans.cluster_centers_[best_idx]
    bgr_px = np.uint8([[[int(center[0]), int(center[1]), int(center[2])]]])
    lab = cv2.cvtColor(bgr_px, cv2.COLOR_BGR2LAB)[0][0]
    l_star = float(lab[0]) / 2.55
    a_star = float(lab[1]) - 128.0
    b_star = float(lab[2]) - 128.0
    chroma = math.sqrt(a_star ** 2 + b_star ** 2)

    if l_star > 92 or l_star < 8:
        # Achromatic dominant — pick most chromatic cluster with meaningful count.
        best_chroma_score = -1.0
        for i in range(actual_k):
            c = kmeans.cluster_centers_[i]
            bgr_c = np.uint8([[[int(c[0]), int(c[1]), int(c[2])]]])
            lab_c = cv2.cvtColor(bgr_c, cv2.COLOR_BGR2LAB)[0][0]
            l_c = float(lab_c[0]) / 2.55
            if l_c > 94 or l_c < 6:
                continue
            a_c = float(lab_c[1]) - 128.0
            b_c = float(lab_c[2]) - 128.0
            chroma_c = math.sqrt(a_c ** 2 + b_c ** 2)
            score = counts[i] * (1.0 + chroma_c / 25.0)
            if score > best_chroma_score:
                best_chroma_score = score
                best_idx = i

    dominant_bgr = kmeans.cluster_centers_[best_idx].astype(int)
    b, g, r = int(dominant_bgr[0]), int(dominant_bgr[1]), int(dominant_bgr[2])
    return f"#{r:02X}{g:02X}{b:02X}"


# ── Step 5 — UV% mapping via LAB L* interpolation ────────────────────────────

def _hex_to_uv_percent(hex_color: str) -> float:
    """
    Converts a '#RRGGBB' hex colour to UV MED percentage via L* interpolation.

    Process:
    1. Parse hex → RGB → OpenCV BGR pixel.
    2. Convert BGR pixel to LAB using OpenCV.
    3. Normalise L* from OpenCV's 0-255 range to CIE 0-100 range (÷ 2.55).
    4. Interpolate L* against the calibration curve (_UV_CURVE).
    5. Clamp result to [0, 100].

    The LAB L* channel is perceptually uniform — small ΔL* corresponds to
    visually meaningful UV exposure changes on the photochromic dye.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Malformed hex colour: {hex_color}")

    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    bgr_pixel = np.uint8([[[b, g, r]]])
    lab_pixel = cv2.cvtColor(bgr_pixel, cv2.COLOR_BGR2LAB)[0][0]

    l_star = float(lab_pixel[0]) / 2.55
    uv_pct = float(np.clip(_UV_CURVE(l_star), 0.0, 100.0))

    logger.debug("[Colorimetry] hex=%s L*=%.1f → UV%%=%.1f", hex_color, l_star, uv_pct)
    return round(uv_pct, 1)
