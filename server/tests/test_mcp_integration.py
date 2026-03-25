"""Smoke test: verify MCP server module loads and tools register correctly."""
import os
import pytest
from unittest.mock import patch

try:
    import mcp_server  # noqa: F401
    MCP_SERVER_AVAILABLE = True
except ImportError:
    MCP_SERVER_AVAILABLE = False

try:
    from services.tool_service import TOOL_MAPPING  # noqa: F401
    TOOL_SERVICE_AVAILABLE = True
except ImportError:
    TOOL_SERVICE_AVAILABLE = False


@pytest.mark.skipif(not MCP_SERVER_AVAILABLE, reason="mcp_server dependencies not available")
def test_mcp_server_loads():
    """MCP server module should load without errors."""
    with patch.dict(os.environ, {"JAAZ_API_KEY": "test_key"}):
        import importlib
        import mcp_server
        importlib.reload(mcp_server)

        server = mcp_server.mcp_server
        assert server is not None
        assert server.name == "Jaaz Image Generator"


@pytest.mark.skipif(
    not MCP_SERVER_AVAILABLE or not TOOL_SERVICE_AVAILABLE,
    reason="mcp_server or tool_service dependencies not available",
)
def test_tool_defs_cover_all_image_tools():
    """All image tools from TOOL_MAPPING should have MCP definitions."""
    from services.tool_service import TOOL_MAPPING
    from mcp_server import TOOL_DEFS

    image_tools = [k for k, v in TOOL_MAPPING.items() if v.get("type") == "image"]

    # Every image tool in TOOL_MAPPING should have a corresponding MCP tool def
    for tool_id in image_tools:
        provider = TOOL_MAPPING[tool_id]["provider"]
        model_tools = [
            name for name, d in TOOL_DEFS.items()
            if d["provider"] == provider
        ]
        assert len(model_tools) > 0, f"No MCP tool found for {tool_id} (provider: {provider})"


@pytest.mark.skipif(not MCP_SERVER_AVAILABLE, reason="mcp_server dependencies not available")
def test_no_video_tools_registered():
    """No video tools should be in MCP tool definitions."""
    from mcp_server import TOOL_DEFS

    for name, tool_def in TOOL_DEFS.items():
        assert "video" not in name.lower(), f"Video tool found in MCP: {name}"
