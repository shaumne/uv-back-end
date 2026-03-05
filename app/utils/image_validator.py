"""
Image validation utilities.

All uploaded images pass through these checks before OpenCV processing
to prevent malformed input from crashing the analysis pipeline.
"""
import logging
from io import BytesIO

from PIL import Image

from ..core.config import settings

logger = logging.getLogger(__name__)


def validate_image(image_bytes: bytes) -> None:
    """
    Validates that the uploaded image is safe to process.

    Checks:
    - File size is within [settings.max_image_size_bytes].
    - File can be decoded as a valid image by Pillow.
    - Both dimensions are at least [settings.min_image_dimension_px].

    Args:
        image_bytes: Raw bytes of the uploaded image file.

    Raises:
        ValueError: With a descriptive message for each validation failure.
    """
    size = len(image_bytes)
    if size > settings.max_image_size_bytes:
        raise ValueError(
            f"Image too large: {size / 1_048_576:.1f} MB "
            f"(max {settings.max_image_size_bytes / 1_048_576:.0f} MB)."
        )

    try:
        img = Image.open(BytesIO(image_bytes))
        img.verify()  # raises if corrupt
    except Exception as exc:
        raise ValueError(f"Invalid or corrupt image file: {exc}") from exc

    # Re-open after verify() (verify() closes the stream)
    img = Image.open(BytesIO(image_bytes))
    width, height = img.size
    min_dim = settings.min_image_dimension_px
    if width < min_dim or height < min_dim:
        raise ValueError(
            f"Image dimensions {width}×{height} px are too small "
            f"(minimum {min_dim}×{min_dim} px required)."
        )

    logger.debug("Image validated: %d bytes, %d×%d px.", size, width, height)
