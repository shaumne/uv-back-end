"""
Pytest configuration and shared fixtures for the BlancMate API test suite.

Provides:
  - `client` fixture: an httpx.AsyncClient bound to the FastAPI app with
    transport overriding so tests run without a live server.
  - `sample_jpeg_bytes` fixture: a minimal valid JPEG image as bytes, used for
    multipart/form-data upload tests.
  - `api_key_headers` fixture: headers dict with the test API key.

Environment:
  Tests run with `API_KEY=""` (auth disabled) unless a specific auth test
  explicitly sets the header.
"""
import io

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Creates a minimal in-memory JPEG image suitable for upload tests."""
    # White image — enough for basic endpoint validation tests.
    arr = np.full((height, width, 3), fill_value=200, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client bound to the ASGI app — no real server required."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """Returns a valid 100×100 white JPEG as bytes."""
    return _make_jpeg_bytes()


@pytest.fixture
def small_jpeg_bytes() -> bytes:
    """Returns a JPEG that is below the minimum dimension threshold (10×10)."""
    return _make_jpeg_bytes(width=10, height=10)


@pytest.fixture
def api_key_headers() -> dict[str, str]:
    """Headers dict for authenticated requests (uses empty key — auth disabled by default)."""
    return {"X-API-Key": ""}
