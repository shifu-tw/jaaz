# Remote MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a remote MCP endpoint to the existing Jaaz FastAPI app so employees can generate images via Claude chat, with images placed on the Jaaz Canvas for manual editing.

**Architecture:** Mount an MCP server (via `mcp` Python SDK's `FastMCP`) as an ASGI sub-app at `/mcp` on the existing FastAPI application. MCP tools call existing image providers directly, save to canvas via existing DB/WebSocket services, and return base64 previews to Claude. Google OAuth restricts access to company domain.

**Tech Stack:** Python, FastMCP (`mcp` SDK), FastAPI, existing image providers (Jaaz/Replicate/OpenAI/Volces), SQLite, Pillow

**Spec:** `docs/superpowers/specs/2026-03-25-remote-mcp-server-design.md`

**Note:** File names differ from spec (`mcp_endpoint.py` → `mcp_server.py`, `mcp_image_tools.py` → `mcp_tools.py`) for clarity.

**Known limitation:** OAuth is Bearer-token only in this plan. Claude.ai remote MCP may require full OAuth 2.1 (`/authorize` + `/token` endpoints). This will be addressed as a follow-up if needed.

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `server/mcp_server.py` | FastMCP server instance, tool registration, MCP instructions + planning prompt |
| `server/mcp_tools.py` | MCP tool handler functions (call providers → save to canvas → return base64) |
| `server/mcp_utils.py` | Utility: create_preview_base64, get_user_canvas_id |
| `server/routers/mcp_router.py` | Mount MCP ASGI sub-app on FastAPI, OAuth middleware |
| `server/routers/mcp_auth.py` | Google OAuth verification (token validation, domain check, OAuth endpoints) |
| `server/tests/test_mcp_tools.py` | Tests for MCP tool handlers |
| `server/tests/test_mcp_utils.py` | Tests for MCP utilities |
| `server/tests/test_mcp_auth.py` | Tests for OAuth auth logic |

### Modified Files

| File | Change |
|---|---|
| `server/main.py` | Add MCP router + CORS middleware |
| `server/requirements.txt` | Update `mcp` version constraint, add `httpx` |
| `server/services/config_service.py` | Add env var fallback for API keys |

---

## Task 1: Update dependencies and config service

**Files:**
- Modify: `server/requirements.txt`
- Modify: `server/services/config_service.py`
- Test: `server/tests/test_mcp_utils.py`

- [ ] **Step 1: Update requirements.txt**

Add/update these lines in `server/requirements.txt`:

```
mcp>=1.26.0
httpx
```

(`mcp` already exists in the file — update the version constraint. `httpx` may be transitive but pin it explicitly.)

- [ ] **Step 2: Add env var fallback to config_service.py**

Add this method to the `ConfigService` class in `server/services/config_service.py`:

```python
def get_api_key(self, provider: str) -> str:
    """Get API key for provider. Priority: config.toml > env var."""
    key = self.app_config.get(provider, {}).get("api_key", "")
    if key:
        return key
    env_map = {
        "jaaz": "JAAZ_API_KEY",
        "replicate": "REPLICATE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "volces": "VOLCES_API_KEY",
    }
    return os.environ.get(env_map.get(provider, ""), "")
```

- [ ] **Step 3: Write test for get_api_key**

Create `server/tests/test_mcp_utils.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `cd server && python -m pytest tests/test_mcp_utils.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/requirements.txt server/services/config_service.py server/tests/test_mcp_utils.py
git commit -m "feat: add env var fallback for provider API keys"
```

---

## Task 2: MCP utilities (preview base64 + user canvas ID)

**Files:**
- Create: `server/mcp_utils.py`
- Modify: `server/tests/test_mcp_utils.py`

- [ ] **Step 1: Write tests for mcp_utils**

Append to `server/tests/test_mcp_utils.py`:

```python
import tempfile
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
    import base64, io
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && python -m pytest tests/test_mcp_utils.py::test_create_preview_base64_small_image -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_utils'`

- [ ] **Step 3: Implement mcp_utils.py**

Create `server/mcp_utils.py`:

```python
import base64
import hashlib
from io import BytesIO
from PIL import Image


def create_preview_base64(file_path: str, max_size: int = 1024) -> str:
    """Read an image file and return base64 string, resized if larger than max_size."""
    img = Image.open(file_path)

    # Resize if either dimension exceeds max_size
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    # Convert to PNG bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def get_user_canvas_id(email: str) -> str:
    """Generate a deterministic canvas ID for a user based on email."""
    h = hashlib.sha256(email.encode()).hexdigest()[:12]
    return f"mcp_{h}"
```

- [ ] **Step 4: Run all tests**

Run: `cd server && python -m pytest tests/test_mcp_utils.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/mcp_utils.py server/tests/test_mcp_utils.py
git commit -m "feat: add MCP utilities for image preview and user canvas ID"
```

---

## Task 3: MCP tool handlers

**Files:**
- Create: `server/mcp_tools.py`
- Create: `server/tests/test_mcp_tools.py`

- [ ] **Step 1: Write tests for a representative tool handler**

Create `server/tests/test_mcp_tools.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import os


@pytest.mark.asyncio
async def test_generate_image_tool_returns_image_and_text():
    """Tool should return list with ImageContent and TextContent."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ("image/png", 512, 512, "test123.png")

    # Create a small test image file
    import tempfile
    from PIL import Image as PILImage
    tmpdir = tempfile.mkdtemp()
    test_file = os.path.join(tmpdir, "test123.png")
    PILImage.new("RGB", (100, 100), "red").save(test_file, "PNG")

    with patch("mcp_tools.IMAGE_PROVIDERS", {"jaaz": mock_provider}), \
         patch("mcp_tools.FILES_DIR", tmpdir), \
         patch("mcp_tools.save_image_to_canvas", new_callable=AsyncMock) as mock_save, \
         patch("mcp_tools.DEPLOY_HOST", "test.example.com"):

        from mcp_tools import _generate_image

        result = await _generate_image(
            provider_name="jaaz",
            model="openai/gpt-image-1",
            prompt="a cat",
            aspect_ratio="1:1",
            canvas_id="test_canvas",
            input_images=None,
        )

    assert len(result) == 2
    # First item is image
    assert result[0]["type"] == "image"
    assert result[0]["mimeType"] == "image/png"
    assert len(result[0]["data"]) > 0
    # Second item is text with image_id and canvas URL
    assert result[1]["type"] == "text"
    assert "test123.png" in result[1]["text"]
    assert "test.example.com" in result[1]["text"]


@pytest.mark.asyncio
async def test_generate_image_tool_with_input_images():
    """Tool should process input_images before calling provider."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = ("image/png", 512, 512, "out.png")

    import tempfile
    from PIL import Image as PILImage
    tmpdir = tempfile.mkdtemp()
    # Create input image
    input_file = os.path.join(tmpdir, "input.png")
    PILImage.new("RGB", (100, 100), "blue").save(input_file, "PNG")
    # Create output image
    out_file = os.path.join(tmpdir, "out.png")
    PILImage.new("RGB", (100, 100), "green").save(out_file, "PNG")

    with patch("mcp_tools.IMAGE_PROVIDERS", {"jaaz": mock_provider}), \
         patch("mcp_tools.FILES_DIR", tmpdir), \
         patch("mcp_tools.save_image_to_canvas", new_callable=AsyncMock), \
         patch("mcp_tools.process_input_image", new_callable=AsyncMock, return_value="data:image/png;base64,abc") as mock_process, \
         patch("mcp_tools.DEPLOY_HOST", "test.example.com"):

        from mcp_tools import _generate_image

        await _generate_image(
            provider_name="jaaz",
            model="openai/gpt-image-1",
            prompt="edit this",
            aspect_ratio="1:1",
            canvas_id="test_canvas",
            input_images=["input.png"],
        )

    mock_process.assert_called_once_with("input.png")
    # Provider should receive processed image
    call_kwargs = mock_provider.generate.call_args
    assert call_kwargs.kwargs.get("input_images") == ["data:image/png;base64,abc"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && python -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools'`

- [ ] **Step 3: Implement mcp_tools.py**

Create `server/mcp_tools.py`:

```python
"""MCP tool handler functions.

Each tool calls an image provider directly, saves to canvas, and returns
both a base64 preview (for Claude chat) and canvas URL (for manual editing).
"""
import os
from typing import Optional
from mcp.types import ImageContent, TextContent

from tools.utils.image_generation_core import IMAGE_PROVIDERS
from tools.utils.image_utils import process_input_image
from tools.utils.image_canvas_utils import save_image_to_canvas
from services.config_service import FILES_DIR
from mcp_utils import create_preview_base64

DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "localhost:57988")


async def _generate_image(
    provider_name: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    canvas_id: str,
    input_images: Optional[list[str]] = None,
) -> list:
    """Core generation logic shared by all MCP image tools.

    Returns list of MCP content objects (ImageContent + TextContent).
    """
    # 1. Process input images if provided
    processed_images = None
    if input_images:
        processed_images = []
        for img_id in input_images:
            processed = await process_input_image(img_id)
            if processed:
                processed_images.append(processed)

    # 2. Call provider
    provider = IMAGE_PROVIDERS[provider_name]
    mime_type, width, height, filename = await provider.generate(
        prompt=prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        input_images=processed_images,
        metadata={"prompt": prompt, "model": model, "provider": provider_name},
    )

    # 3. Save to canvas
    session_id = f"mcp_{canvas_id}"
    await save_image_to_canvas(
        session_id, canvas_id, filename, mime_type, width, height
    )

    # 4. Create preview base64 (resized for Claude chat)
    file_path = os.path.join(FILES_DIR, filename)
    image_base64 = create_preview_base64(file_path, max_size=1024)

    # 5. Build canvas URL
    schema = "http" if "localhost" in DEPLOY_HOST else "https"
    canvas_url = f"{schema}://{DEPLOY_HOST}"

    return [
        ImageContent(type="image", data=image_base64, mimeType="image/png"),
        TextContent(type="text", text=f"image_id: {filename}\nCanvas: {canvas_url}"),
    ]
```

- [ ] **Step 4: Run tests**

Run: `cd server && python -m pytest tests/test_mcp_tools.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/mcp_tools.py server/tests/test_mcp_tools.py
git commit -m "feat: add MCP tool handler core logic"
```

---

## Task 4: MCP server with tool registration

**Files:**
- Create: `server/mcp_server.py`

- [ ] **Step 1: Create mcp_server.py with FastMCP + all tool definitions**

Create `server/mcp_server.py`:

```python
"""MCP Server for Jaaz image generation.

Registers image generation tools dynamically based on available API keys.
Each tool calls providers directly, saves to canvas, returns base64 preview.
"""
import os
from mcp.server.fastmcp import FastMCP
from services.config_service import config_service
from services.tool_service import TOOL_MAPPING
from mcp_tools import _generate_image
from mcp_utils import get_user_canvas_id

MCP_INSTRUCTIONS = """You are the Jaaz image generation assistant. Generated images are placed on an interactive canvas where users can drag, resize, layer, and manually adjust them.

Tool selection guide:
- Multi-image reference editing -> generate_image_gpt_image_1 (only tool supporting multiple input images)
- Single image editing / object removal -> generate_image_flux_kontext_pro or flux_kontext_max
- Vector design, text rendering -> generate_image_recraft_v3
- Text embedded in images -> generate_image_ideogram_3
- High-quality realistic photos -> generate_image_imagen_4
- Artistic / creative style -> generate_image_midjourney
- Chinese text scenes -> generate_image_doubao_seedream_3
- Image editing (Volces) -> edit_image_doubao_seededit_3

When editing images, reference the image_id returned from previous generations in the input_images parameter.
For batches over 10 images, split into batches of max 10 each.
Always include the canvas URL in your response so the user can open it for manual editing.
"""

mcp_server = FastMCP(
    "Jaaz Image Generator",
    instructions=MCP_INSTRUCTIONS,
    stateless_http=True,
)

# ─── Tool definition table ────────────────────────────────────────
# Maps MCP tool name -> (provider, model, description, supports_input_images, multi_input)
TOOL_DEFS: dict[str, dict] = {
    "generate_image_gpt_image_1": {
        "provider": "jaaz", "model": "openai/gpt-image-1",
        "description": "Generate or edit images using GPT Image 1. Supports MULTIPLE input images for reference/editing. Best for multi-image reference, style transfer, character consistency.",
        "supports_input": True, "multi_input": True,
    },
    "generate_image_imagen_4": {
        "provider": "jaaz", "model": "google/imagen-4",
        "description": "Generate high-quality realistic images using Google Imagen 4. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_recraft_v3": {
        "provider": "jaaz", "model": "recraft-ai/recraft-v3",
        "description": "Generate vector designs and text-heavy images using Recraft v3. Great for logos, posters, text rendering. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_ideogram_3": {
        "provider": "jaaz", "model": "ideogram-ai/ideogram-v3-balanced",
        "description": "Generate images with text embedded in the image using Ideogram 3. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_flux_kontext_pro": {
        "provider": "jaaz", "model": "black-forest-labs/flux-kontext-pro",
        "description": "Generate or edit images using Flux Kontext Pro. Supports ONE input image for editing, object removal, style transfer.",
        "supports_input": True, "multi_input": False,
    },
    "generate_image_flux_kontext_max": {
        "provider": "jaaz", "model": "black-forest-labs/flux-kontext-max",
        "description": "Generate or edit high-quality images using Flux Kontext Max. Supports ONE input image. Premium quality.",
        "supports_input": True, "multi_input": False,
    },
    "generate_image_midjourney": {
        "provider": "jaaz", "model": "midjourney",
        "description": "Generate artistic images using Midjourney. Returns multiple image variations. Supports ONE input image.",
        "supports_input": True, "multi_input": False,
        "is_midjourney": True,
    },
    "generate_image_doubao_seedream_3": {
        "provider": "jaaz", "model": "doubao-seedream-3",
        "description": "Generate images using Doubao Seedream 3. Good for Chinese text scenes. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_doubao_seedream_3_volces": {
        "provider": "volces", "model": "doubao-seedream-3-0-t2i-250301",
        "description": "Generate images using Doubao Seedream 3 via Volces. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "edit_image_doubao_seededit_3": {
        "provider": "volces", "model": "doubao-seededit-3-0-i2i-250628",
        "description": "Edit an existing image using Doubao Seededit 3. REQUIRES one input image.",
        "supports_input": True, "multi_input": False, "input_required": True,
    },
    "generate_image_imagen_4_replicate": {
        "provider": "replicate", "model": "google/imagen-4",
        "description": "Generate images using Imagen 4 via Replicate. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_recraft_v3_replicate": {
        "provider": "replicate", "model": "recraft-ai/recraft-v3",
        "description": "Generate images using Recraft v3 via Replicate. Does NOT support input images.",
        "supports_input": False, "multi_input": False,
    },
    "generate_image_flux_kontext_pro_replicate": {
        "provider": "replicate", "model": "black-forest-labs/flux-kontext-pro",
        "description": "Generate or edit images using Flux Kontext Pro via Replicate. Supports ONE input image.",
        "supports_input": True, "multi_input": False,
    },
    "generate_image_flux_kontext_max_replicate": {
        "provider": "replicate", "model": "black-forest-labs/flux-kontext-max",
        "description": "Generate or edit images using Flux Kontext Max via Replicate. Supports ONE input image.",
        "supports_input": True, "multi_input": False,
    },
}

# Provider -> env var name mapping for dynamic registration
PROVIDER_ENV_MAP = {
    "jaaz": "JAAZ_API_KEY",
    "replicate": "REPLICATE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "volces": "VOLCES_API_KEY",
}


def _has_provider_key(provider: str) -> bool:
    """Check if a provider has an API key configured (config.toml or env var)."""
    return bool(config_service.get_api_key(provider))


def register_all_tools():
    """Register MCP tools for all providers with available API keys."""
    for tool_name, tool_def in TOOL_DEFS.items():
        provider = tool_def["provider"]
        if not _has_provider_key(provider):
            continue

        supports_input = tool_def.get("supports_input", False)

        if supports_input:
            _register_tool_with_input(tool_name, tool_def)
        else:
            _register_tool_no_input(tool_name, tool_def)

    print(f"✅ MCP: Registered {len([t for t in TOOL_DEFS if _has_provider_key(TOOL_DEFS[t]['provider'])])} tools")


def _register_tool_no_input(name: str, tool_def: dict):
    @mcp_server.tool(name=name, description=tool_def["description"])
    async def handler(prompt: str, aspect_ratio: str, canvas_id: str = "") -> list[dict]:
        cid = canvas_id or "default"
        return await _generate_image(
            provider_name=tool_def["provider"],
            model=tool_def["model"],
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            canvas_id=cid,
        )


def _register_tool_with_input(name: str, tool_def: dict):
    @mcp_server.tool(name=name, description=tool_def["description"])
    async def handler(prompt: str, aspect_ratio: str, canvas_id: str = "", input_images: list[str] | None = None) -> list[dict]:
        cid = canvas_id or "default"
        return await _generate_image(
            provider_name=tool_def["provider"],
            model=tool_def["model"],
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            canvas_id=cid,
            input_images=input_images,
        )


# ─── Planning Prompt ──────────────────────────────────────────────
@mcp_server.prompt()
def plan_image_task(task_description: str) -> str:
    """Plan a complex image generation task with design strategy."""
    return f"""You are a design planning agent. Plan this task: {task_description}

Rules:
1. Break complex tasks into steps
2. Write a Design Strategy Doc including:
   - Recommended resolution and aspect ratio
   - Style & Mood description
   - Key visual elements
   - Composition & Layout
   - Color palette
   - Typography recommendations
3. Specify exact image quantities (preserve user's requested count)
4. For batches >10: split into batches of max 10
5. Choose the right tool for each image based on the tool selection guide
6. Answer in the SAME LANGUAGE as the task description"""


# NOTE: Do NOT call register_all_tools() here at module level.
# It must be called AFTER config_service.initialize() in the FastAPI lifespan.
# See Task 6 for where this is triggered.
```

- [ ] **Step 2: Verify module loads without errors**

Run: `cd server && python -c "from mcp_server import mcp_server; print('MCP server loaded OK')"`
Expected: Prints "MCP server loaded OK" (no tools registered yet — that happens in lifespan)

- [ ] **Step 3: Commit**

```bash
git add server/mcp_server.py
git commit -m "feat: add MCP server with dynamic tool registration and planning prompt"
```

---

## Task 5: OAuth authentication

**Files:**
- Create: `server/routers/mcp_auth.py`
- Create: `server/tests/test_mcp_auth.py`

- [ ] **Step 1: Write tests for auth logic**

Create `server/tests/test_mcp_auth.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from routers.mcp_auth import verify_domain


def test_verify_domain_allowed():
    assert verify_domain("alice@company.com", "company.com") is True


def test_verify_domain_rejected():
    assert verify_domain("alice@other.com", "company.com") is False


def test_verify_domain_empty_allowed_domain():
    """Empty ALLOWED_DOMAIN means allow all."""
    assert verify_domain("anyone@anywhere.com", "") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && python -m pytest tests/test_mcp_auth.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement mcp_auth.py**

Create `server/routers/mcp_auth.py`:

```python
"""Google OAuth authentication for MCP endpoint."""
import os
import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "")
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def verify_domain(email: str, allowed_domain: str) -> bool:
    """Check if email belongs to allowed domain. Empty domain allows all."""
    if not allowed_domain:
        return True
    return email.endswith(f"@{allowed_domain}")


async def validate_bearer_token(token: str) -> dict | None:
    """Validate a Bearer token against Google's userinfo endpoint.

    Returns user info dict on success, None on failure.
    """
    async with httpx.AsyncClient() as client:
        res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        if res.status_code != 200:
            return None
        return res.json()


class MCPAuthMiddleware:
    """ASGI middleware that validates Bearer tokens for MCP requests."""

    def __init__(self, app: ASGIApp, allowed_domain: str = ""):
        self.app = app
        self.allowed_domain = allowed_domain

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Handle CORS preflight (FastAPI CORS middleware doesn't apply to sub-apps)
            if request.method == "OPTIONS":
                response = JSONResponse(content={}, status_code=200, headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                })
                await response(scope, receive, send)
                return

            auth_header = request.headers.get("authorization", "")

            if not auth_header.startswith("Bearer "):
                response = JSONResponse(
                    {"error": "Missing or invalid Authorization header"},
                    status_code=401,
                )
                await response(scope, receive, send)
                return

            token = auth_header[7:]
            user_info = await validate_bearer_token(token)

            if user_info is None:
                response = JSONResponse({"error": "Invalid token"}, status_code=401)
                await response(scope, receive, send)
                return

            email = user_info.get("email", "")
            if not verify_domain(email, self.allowed_domain):
                response = JSONResponse(
                    {"error": f"Only @{self.allowed_domain} accounts allowed"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return

            # Store user info in request state for downstream use
            scope["state"] = scope.get("state", {})
            scope["state"]["user_email"] = email

        # Wrap send to add CORS headers to all responses
        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"access-control-allow-origin"] = b"*"
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_cors)
```

- [ ] **Step 4: Run tests**

Run: `cd server && python -m pytest tests/test_mcp_auth.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/routers/mcp_auth.py server/tests/test_mcp_auth.py
git commit -m "feat: add Google OAuth middleware for MCP endpoint"
```

---

## Task 6: MCP router + mount on FastAPI

**Files:**
- Create: `server/routers/mcp_router.py`
- Modify: `server/main.py`

- [ ] **Step 1: Create mcp_router.py**

Create `server/routers/mcp_router.py`:

```python
"""Mount MCP server as ASGI sub-app on FastAPI."""
import os
from mcp_server import mcp_server
from routers.mcp_auth import MCPAuthMiddleware

ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "")

# Wrap MCP's ASGI app with auth middleware
# Note: FastAPI's CORSMiddleware does NOT apply to mounted sub-apps,
# so we handle CORS inside MCPAuthMiddleware (see mcp_auth.py).
mcp_asgi_app = MCPAuthMiddleware(
    mcp_server.streamable_http_app(),
    allowed_domain=ALLOWED_DOMAIN,
)
```

- [ ] **Step 2: Modify main.py to mount MCP + add CORS**

In `server/main.py`, add these changes:

After the existing router imports (around line 10), add:

```python
from fastapi.middleware.cors import CORSMiddleware
```

After `app = FastAPI(lifespan=lifespan)` (around line 46), add CORS:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

After the existing router inclusions (around line 58), add:

```python
# Mount MCP server
try:
    from routers.mcp_router import mcp_asgi_app
    app.mount("/mcp", mcp_asgi_app)
    print("✅ MCP server mounted at /mcp")
except Exception as e:
    print(f"⚠️ MCP server not mounted: {e}")
```

In the `initialize()` function (around line 28), add MCP tool registration AFTER config_service init:

```python
async def initialize():
    print('Initializing config_service')
    await config_service.initialize()
    # Register MCP tools after config is loaded (API keys available)
    try:
        from mcp_server import register_all_tools
        register_all_tools()
    except Exception as e:
        print(f"⚠️ MCP tools not registered: {e}")
    print('Initializing broadcast_init_done')
    await broadcast_init_done()
```

Also update the uvicorn bind address (around line 107) to support cloud deployment:

```python
host = os.environ.get("HOST", "127.0.0.1")
uvicorn.run(socket_app, host=host, port=args.port)
```

- [ ] **Step 3: Verify server starts without errors**

Run: `cd server && python -c "from main import app; print('App loaded with MCP')"`
Expected: Prints startup messages including "MCP server mounted at /mcp" (or warning if no API keys)

- [ ] **Step 4: Commit**

```bash
git add server/routers/mcp_router.py server/main.py
git commit -m "feat: mount MCP server at /mcp with OAuth middleware and CORS"
```

---

## Task 7: Midjourney special handling

**Files:**
- Modify: `server/mcp_tools.py`
- Modify: `server/mcp_server.py`

- [ ] **Step 1: Add Midjourney handler to mcp_tools.py**

Append to `server/mcp_tools.py`:

```python
from services.jaaz_service import JaazService
from tools.utils.image_utils import get_image_info_and_save, generate_image_id


async def _generate_midjourney(
    prompt: str,
    canvas_id: str,
    input_images: list[str] | None = None,
) -> list[dict]:
    """Midjourney-specific handler: async polling, returns multiple images."""
    # Process input images
    processed = None
    if input_images:
        processed = []
        for img_id in input_images:
            p = await process_input_image(img_id)
            if p:
                processed.append(p)

    jaaz_service = JaazService()
    result = await jaaz_service.generate_image_by_midjourney(
        prompt=prompt, model="midjourney", input_images=processed
    )

    if not result:
        return [{"type": "text", "text": "Midjourney generation failed: no result"}]

    images = result.get("images", [])
    if not images:
        return [{"type": "text", "text": "Midjourney generation failed: no images"}]

    content: list[dict] = []
    session_id = f"mcp_{canvas_id}"

    for img_data in images:
        url = img_data.get("url")
        if not url:
            continue

        image_id = generate_image_id()
        mime_type, width, height, ext = await get_image_info_and_save(
            url, os.path.join(FILES_DIR, image_id),
            metadata={"prompt": prompt, "model": "midjourney"},
        )
        filename = f"{image_id}.{ext}"

        await save_image_to_canvas(
            session_id, canvas_id, filename, mime_type, width, height
        )

        preview_b64 = create_preview_base64(
            os.path.join(FILES_DIR, filename), max_size=1024
        )
        content.append({"type": "image", "data": preview_b64, "mimeType": "image/png"})

    schema = "http" if "localhost" in DEPLOY_HOST else "https"
    canvas_url = f"{schema}://{DEPLOY_HOST}"
    content.append({
        "type": "text",
        "text": f"Generated {len(content)} Midjourney images.\nCanvas: {canvas_url}",
    })
    return content
```

- [ ] **Step 2: Update mcp_server.py Midjourney registration**

In `server/mcp_server.py`, update the Midjourney entry in `_register_tool_with_input` to use the special handler. Replace the `_register_tool_with_input` function:

```python
def _register_tool_with_input(name: str, tool_def: dict):
    is_midjourney = tool_def.get("is_midjourney", False)

    if is_midjourney:
        from mcp_tools import _generate_midjourney

        @mcp_server.tool(name=name, description=tool_def["description"])
        async def handler(prompt: str, canvas_id: str = "", input_images: list[str] | None = None) -> list[dict]:
            cid = canvas_id or "default"
            return await _generate_midjourney(prompt=prompt, canvas_id=cid, input_images=input_images)
    else:
        @mcp_server.tool(name=name, description=tool_def["description"])
        async def handler(prompt: str, aspect_ratio: str, canvas_id: str = "", input_images: list[str] | None = None) -> list[dict]:
            cid = canvas_id or "default"
            return await _generate_image(
                provider_name=tool_def["provider"],
                model=tool_def["model"],
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                canvas_id=cid,
                input_images=input_images,
            )
```

Note: Midjourney doesn't take `aspect_ratio` — it generates its own dimensions.

- [ ] **Step 3: Commit**

```bash
git add server/mcp_tools.py server/mcp_server.py
git commit -m "feat: add Midjourney special handler with async polling and multi-image return"
```

---

## Task 8: Integration test — end-to-end smoke test

**Files:**
- Create: `server/tests/test_mcp_integration.py`

- [ ] **Step 1: Write integration smoke test**

Create `server/tests/test_mcp_integration.py`:

```python
"""Smoke test: verify MCP server module loads and tools register correctly."""
import os
import pytest
from unittest.mock import patch


def test_mcp_server_loads():
    """MCP server module should load without errors."""
    # Simulate having a Jaaz API key
    with patch.dict(os.environ, {"JAAZ_API_KEY": "test_key"}):
        # Need to reload since mcp_server registers on import
        import importlib
        import mcp_server
        importlib.reload(mcp_server)

        server = mcp_server.mcp_server
        assert server is not None
        assert server.name == "Jaaz Image Generator"


def test_tool_defs_cover_all_image_tools():
    """All image tools from TOOL_MAPPING should have MCP definitions."""
    from services.tool_service import TOOL_MAPPING
    from mcp_server import TOOL_DEFS

    image_tools = [k for k, v in TOOL_MAPPING.items() if v.get("type") == "image"]

    # Every image tool in TOOL_MAPPING should have a corresponding MCP tool def
    for tool_id in image_tools:
        # Find matching MCP tool (name mapping exists)
        provider = TOOL_MAPPING[tool_id]["provider"]
        model_tools = [
            name for name, d in TOOL_DEFS.items()
            if d["provider"] == provider
        ]
        assert len(model_tools) > 0, f"No MCP tool found for {tool_id} (provider: {provider})"


def test_no_video_tools_registered():
    """No video tools should be in MCP tool definitions."""
    from mcp_server import TOOL_DEFS

    for name, tool_def in TOOL_DEFS.items():
        assert "video" not in name.lower(), f"Video tool found in MCP: {name}"
```

- [ ] **Step 2: Run integration tests**

Run: `cd server && python -m pytest tests/test_mcp_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_mcp_integration.py
git commit -m "test: add MCP server integration smoke tests"
```

---

## Task 9: Deployment configuration

**Files:**
- Create: `server/Dockerfile.mcp` (optional, for container deployment)
- Create: `server/.env.example`

- [ ] **Step 1: Create .env.example**

Create `server/.env.example`:

```bash
# Jaaz Remote MCP Server - Environment Variables
# Copy to .env and fill in values

# Provider API keys (at least one required)
JAAZ_API_KEY=
REPLICATE_API_KEY=
OPENAI_API_KEY=
VOLCES_API_KEY=

# Google OAuth (required for authentication)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Access control
ALLOWED_DOMAIN=yourcompany.com

# Deployment
DEPLOY_HOST=jaaz.yourcompany.com
DEFAULT_PORT=57988
```

- [ ] **Step 2: Create Dockerfile for cloud deployment**

Create `server/Dockerfile.mcp`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev libjpeg-dev && \
    rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .
COPY react/dist/ /app/react-dist/

ENV UI_DIST_DIR=/app/react-dist
ENV PYTHONUNBUFFERED=1

EXPOSE 57988

CMD ["python", "main.py", "--port", "57988"]
```

- [ ] **Step 3: Commit**

```bash
git add server/.env.example server/Dockerfile.mcp
git commit -m "chore: add deployment config for remote MCP server"
```

---

## Task 10: Manual end-to-end verification

- [ ] **Step 1: Start server locally with test API key**

```bash
cd server
JAAZ_API_KEY=your_test_key ALLOWED_DOMAIN="" python main.py
```

Verify console output includes "MCP server mounted at /mcp"

- [ ] **Step 2: Test MCP endpoint responds**

```bash
curl -X POST http://localhost:57988/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {"capabilities": {}}, "id": 1}'
```

Expected: JSON-RPC response (may be auth error if ALLOWED_DOMAIN is set — that's fine, it means the endpoint is reachable)

- [ ] **Step 3: Verify existing app still works**

Open `http://localhost:57988` in browser — the React canvas UI should load normally.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete remote MCP server integration"
```
