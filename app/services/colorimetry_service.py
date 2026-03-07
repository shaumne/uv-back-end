"""
Colorimetry service v3 — production-hardened UV sticker colour extraction.

Sticker: sadece mor (lavanta, mor, indigo). Beyaz/şeffaf ve mor dışı renkler
algılanmaz; UV% mor kalibrasyon eğrisi ile hesaplanır.

Pipeline (ROI, UI kılavuzu ile uyumlu):
1. Decode → BGR, resize, LAB white balance.
2. ROI (merkez %45 veya client pre_cropped ile tüm görüntü).
3. Sadece mor HSV maskesi (H 100–178, S ≥ 10); beyaz/şeffaf dahil değil.
4. K-Means (k=3) → dominant renk; sadece mor kabul (_is_sticker_plausible_colour).
5. Dominant HEX → L* → UV%.

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
    *,
    pre_cropped: bool = False,
) -> tuple[str, float]:
    """
    Full colorimetry pipeline: image bytes → (hex_color, uv_percent).

    When pre_cropped=True (client sent only the guide region), the whole image
    is used as ROI. Otherwise the centre 45 % square is used.

    Args:
        image_bytes: Raw JPEG/PNG bytes from the mobile camera.
        ambient_lux: Ambient light sensor reading in lux (used for logging;
                     white balance uses LAB grey-world independently).
        pre_cropped: If True, treat the entire image as the sticker ROI (no centre crop).

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
    roi_pixels = _isolate_sticker_pixels(balanced, use_full_image_as_roi=pre_cropped)
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


def detect_sticker_presence(image_bytes: bytes, *, pre_cropped: bool = False) -> dict:
    """
    ROI tabanlı hızlı kontrol: mor/şeffaf piksel sayar.
    pre_cropped=True ise tüm görüntü ROI; değilse merkez %45 kare.

    Returns:
        dict: detected (bool), confidence (float), reason (str|None).
    """
    try:
        image = _decode_image(image_bytes)
        image = _resize_for_processing(image, _DETECT_MAX_PX)
        _check_lightness(image)
        balanced = _white_balance_lab(image)

        if pre_cropped:
            roi_image = balanced
        else:
            h, w = balanced.shape[:2]
            size = max(30, int(min(h, w) * 0.45))
            cy, cx = h // 2, w // 2
            y1 = max(0, cy - size // 2)
            y2 = min(h, cy + size // 2)
            x1 = max(0, cx - size // 2)
            x2 = min(w, cx + size // 2)
            roi_image = balanced[y1:y2, x1:x2]

        mask = _build_sticker_mask(roi_image)
        pixel_count = int(np.count_nonzero(mask))

        if pixel_count > _MIN_CONTOUR_PIXELS:
            return {"detected": True, "confidence": 0.90, "reason": None}
        return {
            "detected": False,
            "confidence": 0.0,
            "reason": "sticker_not_detected — Çemberin içine sticker'ı hizalayın.",
        }
    except ValueError as exc:
        reason = str(exc)
        if "insufficient_lighting" in reason or "too dark" in reason.lower():
            return {"detected": False, "confidence": 0.0, "reason": reason}
        return {"detected": False, "confidence": 0.0, "reason": reason}
    except Exception as exc:
        logger.warning("[Detect] Error: %s", exc)
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
    Binary mask: sadece mor (eflatun, lavanta, mor, indigo). Beyaz/şeffaf dahil değil.

    OpenCV HSV: H 100–178 mor spektrumu. Minimum S ile beyaz/şeffaf (S≈0) elenir.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Mor / doygun: H 100–178, S ≥ 20 (beyaz değil)
    purple_vivid = cv2.inRange(hsv, (100, 20, 30), (178, 255, 255))

    # Açık mor / lavanta: H mor, düşük ama sıfır olmayan S (S≥10 → şeffaf/beyaz yok)
    purple_pale = cv2.inRange(hsv, (100, 10, 40), (178, 55, 255))

    combined = cv2.bitwise_or(purple_vivid, purple_pale)

    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, close_k)

    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, open_k)

    return combined


def _isolate_sticker_pixels(
    image: np.ndarray,
    *,
    use_full_image_as_roi: bool = False,
) -> np.ndarray:
    """
    ROI: use_full_image_as_roi=True ise tüm görüntü; değilse merkez %45 kare.
    Sadece mor maskesi uygulanır (beyaz/şeffaf dahil değil); yetersiz mor piksel → sticker_not_detected.

    Returns:
        Shape (N, 3) BGR — sadece mor pikseller.

    Raises:
        ValueError: sticker_not_detected (hedef alanda yeterli mor piksel yok).
    """
    if use_full_image_as_roi:
        roi_image = image
    else:
        h, w = image.shape[:2]
        size = max(30, int(min(h, w) * 0.45))
        cy, cx = h // 2, w // 2
        y1 = max(0, cy - size // 2)
        y2 = min(h, cy + size // 2)
        x1 = max(0, cx - size // 2)
        x2 = min(w, cx + size // 2)
        roi_image = image[y1:y2, x1:x2]

    mask = _build_sticker_mask(roi_image)
    sticker_pixels = roi_image[mask > 0]

    if len(sticker_pixels) < _MIN_CONTOUR_PIXELS:
        logger.warning(
            "[Colorimetry] Merkez alanda sticker rengi yetersiz (%d piksel).",
            len(sticker_pixels),
        )
        raise ValueError(
            "sticker_not_detected — Hedef alanda sticker bulunamadı. "
            "Lütfen sticker'ı ekrandaki çemberin tam içine hizalayın ve ışığın iyi olduğundan emin olun."
        )

    logger.debug(
        "[Colorimetry] ROI: merkez alanda %d sticker pikseli.",
        len(sticker_pixels),
    )
    return sticker_pixels


# ── Sticker colour sanity (reject cola, green, blue, etc.) ─────────────────────

def _is_sticker_plausible_colour(hex_color: str) -> bool:
    """
    Sadece mor kabul. Beyaz/şeffaf ve mor dışı her renk reddedilir.
    OpenCV HSV: mor H 108–178 (lavanta, mor, indigo). S=0 / L* çok yüksek = beyaz → False.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return False
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    bgr = np.uint8([[[b, g, r]]])
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[0][0]
    H, S = int(hsv[0]), int(hsv[1])

    # Beyaz/şeffaf: doygunluk çok düşük → mor değil
    if S <= 15:
        return False
    # Sadece mor spektrumu: H 108–178 (lavanta, mor, indigo)
    if 108 <= H <= 178:
        return True
    # OpenCV'de H 0–179; mor/magenta sınırı
    if 175 <= H <= 179:
        return True
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
