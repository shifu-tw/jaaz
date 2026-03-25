import pytest
import os
import sys
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image as PILImage


def _make_mock_modules():
    """Inject lightweight mocks for heavy server deps so mcp_tools can be imported."""
    mocks = {}

    # tools.utils.image_generation_core
    core_mod = MagicMock()
    core_mod.IMAGE_PROVIDERS = {}
    mocks["tools"] = MagicMock()
    mocks["tools.utils"] = MagicMock()
    mocks["tools.utils.image_generation_core"] = core_mod

    # tools.utils.image_utils
    image_utils_mod = MagicMock()
    image_utils_mod.process_input_image = AsyncMock()
    mocks["tools.utils.image_utils"] = image_utils_mod

    # tools.utils.image_canvas_utils
    canvas_utils_mod = MagicMock()
    canvas_utils_mod.save_image_to_canvas = AsyncMock()
    mocks["tools.utils.image_canvas_utils"] = canvas_utils_mod

    # services.config_service
    config_mod = MagicMock()
    config_mod.FILES_DIR = "/tmp"
    mocks["services"] = MagicMock()
    mocks["services.config_service"] = config_mod

    # services.jaaz_service (added by Midjourney handler)
    jaaz_mod = MagicMock()
    mocks["services.jaaz_service"] = jaaz_mod

    return mocks


@pytest.fixture(autouse=True)
def clean_mcp_tools_import():
    """Remove mcp_tools from sys.modules before each test so patches apply fresh."""
    sys.modules.pop("mcp_tools", None)
    yield
    sys.modules.pop("mcp_tools", None)


@pytest.mark.asyncio
async def test_generate_image_tool_returns_image_and_text():
    """Tool should return list with ImageContent and TextContent."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ("image/png", 512, 512, "test123.png")

    tmpdir = tempfile.mkdtemp()
    test_file = os.path.join(tmpdir, "test123.png")
    PILImage.new("RGB", (100, 100), "red").save(test_file, "PNG")

    injected = _make_mock_modules()
    injected["tools.utils.image_generation_core"].IMAGE_PROVIDERS = {"jaaz": mock_provider}
    injected["services.config_service"].FILES_DIR = tmpdir

    with patch.dict(sys.modules, injected):
        import mcp_tools
        mcp_tools.DEPLOY_HOST = "test.example.com"
        mcp_tools.save_image_to_canvas = AsyncMock()

        result = await mcp_tools._generate_image(
            provider_name="jaaz",
            model="openai/gpt-image-1",
            prompt="a cat",
            aspect_ratio="1:1",
            canvas_id="test_canvas",
            input_images=None,
        )

    assert len(result) == 2
    assert result[0].type == "image"
    assert result[0].mimeType == "image/png"
    assert len(result[0].data) > 0
    assert result[1].type == "text"
    assert "test123.png" in result[1].text
    assert "test.example.com" in result[1].text


@pytest.mark.asyncio
async def test_generate_image_tool_with_input_images():
    """Tool should process input_images before calling provider."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ("image/png", 512, 512, "out.png")

    tmpdir = tempfile.mkdtemp()
    out_file = os.path.join(tmpdir, "out.png")
    PILImage.new("RGB", (100, 100), "green").save(out_file, "PNG")

    mock_process = AsyncMock(return_value="data:image/png;base64,abc")

    injected = _make_mock_modules()
    injected["tools.utils.image_generation_core"].IMAGE_PROVIDERS = {"jaaz": mock_provider}
    injected["tools.utils.image_utils"].process_input_image = mock_process
    injected["services.config_service"].FILES_DIR = tmpdir

    with patch.dict(sys.modules, injected):
        import mcp_tools
        mcp_tools.DEPLOY_HOST = "test.example.com"
        mcp_tools.save_image_to_canvas = AsyncMock()
        mcp_tools.process_input_image = mock_process

        await mcp_tools._generate_image(
            provider_name="jaaz",
            model="openai/gpt-image-1",
            prompt="edit this",
            aspect_ratio="1:1",
            canvas_id="test_canvas",
            input_images=["input.png"],
        )

    mock_process.assert_called_once_with("input.png")
    call_kwargs = mock_provider.generate.call_args
    assert call_kwargs.kwargs.get("input_images") == ["data:image/png;base64,abc"]
