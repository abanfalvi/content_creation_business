"""Test setup: an isolated project root and no real credentials.

PODCAST_HOME must be set before the package is imported, because `settings` reads it once.
"""
import os
import tempfile

HOME = tempfile.mkdtemp(prefix="podcast_test_")
os.environ["PODCAST_HOME"] = HOME
for key in ("POSTGRES_URI", "OPIK_API_KEY", "OPIK_WORKSPACE"):
    os.environ.pop(key, None)
for key in ("OPENROUTER_API_KEY", "TAVILY_API_KEY", "MINERU_API_KEY", "BUFFER_API_KEY", "DROPBOX"):
    os.environ[key] = "test"

import io  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfWriter  # noqa: E402


def make_pdf(pages: int = 3) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    from podcast_generation.api.main import app
    from podcast_generation.services import db

    with TestClient(app) as c:
        db.init(tmp_path / "app.db")  # fresh records for every test
        yield c


def wait_for(fn, timeout: float = 10.0, interval: float = 0.05):
    """Poll `fn` until it returns something truthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")
