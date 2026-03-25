import os
import pytest
from unittest.mock import patch
from services.config_service import ConfigService


def test_get_api_key_from_config():
    svc = ConfigService()
    svc.app_config = {"jaaz": {"api_key": "from_config"}}
    assert svc.get_api_key("jaaz") == "from_config"


def test_get_api_key_from_env():
    svc = ConfigService()
    svc.app_config = {"jaaz": {"api_key": ""}}
    with patch.dict(os.environ, {"JAAZ_API_KEY": "from_env"}):
        assert svc.get_api_key("jaaz") == "from_env"


def test_get_api_key_config_priority_over_env():
    svc = ConfigService()
    svc.app_config = {"jaaz": {"api_key": "from_config"}}
    with patch.dict(os.environ, {"JAAZ_API_KEY": "from_env"}):
        assert svc.get_api_key("jaaz") == "from_config"


def test_get_api_key_unknown_provider():
    svc = ConfigService()
    svc.app_config = {}
    assert svc.get_api_key("unknown") == ""


import tempfile
import base64
import io
from PIL import Image as PILImage
from mcp_utils import create_preview_base64, get_user_canvas_id


def test_create_preview_base64_small_image():
    """Small image should not be resized."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = PILImage.new("RGB", (100, 100), color="red")
        img.save(f, format="PNG")
        f.flush()
        result = create_preview_base64(f.name, max_size=1024)
    assert isinstance(result, str)
    assert len(result) > 0


def test_create_preview_base64_large_image():
    """Large image should be resized to max_size."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = PILImage.new("RGB", (4096, 4096), color="blue")
        img.save(f, format="PNG")
        f.flush()
        result = create_preview_base64(f.name, max_size=512)
    # Decode and check size
    decoded = base64.b64decode(result)
    preview = PILImage.open(io.BytesIO(decoded))
    assert max(preview.size) <= 512


def test_get_user_canvas_id():
    result = get_user_canvas_id("alice@company.com")
    assert result.startswith("mcp_")
    assert len(result) > 4
    # Same email produces same canvas_id
    assert get_user_canvas_id("alice@company.com") == result
    # Different email produces different canvas_id
    assert get_user_canvas_id("bob@company.com") != result
