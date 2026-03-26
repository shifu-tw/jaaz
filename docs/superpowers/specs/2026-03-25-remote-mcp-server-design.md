# Jaaz Remote MCP Server Design Spec

## Overview

Deploy the full Jaaz application (FastAPI + React Canvas UI) to the cloud with an added MCP endpoint. Company employees use Claude chat as the conversation entry point to generate images, which are automatically placed on the Jaaz Canvas for manual editing (drag, layers, adjustments). Authentication via Google OAuth restricted to company domain.

## Goals

- Let company employees generate images via Claude chat MCP tools
- Generated images appear on the Jaaz Canvas for manual editing (drag, layers, adjustments)
- Google OAuth with company domain restriction (no API keys for end users)
- All provider API keys sealed in server-side environment variables
- Keep all image generation + canvas features, exclude video generation
- Include planning prompt for complex multi-image tasks
- Support image editing by referencing previously generated images

## Non-Goals

- Video generation (explicitly excluded)
- ComfyUI local execution (not applicable for cloud deployment)
- Electron desktop app packaging (web-only deployment)

## Architecture

```
Employee's Claude Chat                    Employee's Browser
    | (Streamable HTTP + Google OAuth)       | (HTTPS)
    v                                        v
+--------------------------------------------------+
|  Jaaz Cloud (Zeabur / Railway / Cloud Run)       |
|                                                   |
|  FastAPI Application                              |
|  +-- /mcp endpoint (MCP Streamable HTTP)         |
|  |   +-- Google OAuth middleware                  |
|  |   +-- MCP Tools (image generation)             |
|  |   +-- MCP Instructions + Planning Prompt       |
|  +-- /api/* (existing REST endpoints)             |
|  +-- /socket.io (existing WebSocket)              |
|  +-- / (React Canvas UI - static files)           |
|                                                   |
|  Shared Services:                                 |
|  +-- Image Providers (Jaaz, Replicate, OpenAI,   |
|  |   Volces)                                      |
|  +-- Canvas DB (SQLite)                           |
|  +-- Image Storage (user_data/files/)             |
|  +-- WebSocket (real-time canvas updates)         |
+--------------------------------------------------+
```

**Key insight**: MCP tools reuse the exact same code path as the existing LangChain tools — calling providers, saving images to disk, placing them on canvas, broadcasting via WebSocket. The only addition is a thin MCP wrapper + base64 image return for Claude chat preview.

## User Experience Flow

```
1. Employee opens Claude chat, connects to Jaaz MCP server
   (first time: Google OAuth with company email)

2. Employee: "Generate a magazine cover for our product launch"

3. Claude calls MCP tools (guided by instructions + planning prompt):
   a. Calls generate_image_flux_kontext_max(prompt="...", aspect_ratio="3:4")
   b. MCP tool → provider API → download image → save to canvas + return base64

4. Employee sees:
   - Image preview in Claude chat
   - "Image placed on canvas: https://jaaz.yourcompany.com/canvas/xxx"

5. Employee clicks canvas URL → opens Jaaz Canvas in browser
   → drag, resize, layer editing, manual adjustments

6. Employee back in Claude: "Edit this image, change the background to blue"
   → Claude calls edit tool with image_id → new image on canvas
```

## File Changes

### New Files

```
server/
+-- mcp_endpoint.py          # MCP server setup + tool definitions
+-- mcp_image_tools.py       # MCP tool handlers (call providers + save to canvas)
+-- routers/mcp_router.py    # FastAPI route mounting for /mcp
+-- routers/mcp_auth.py      # Google OAuth middleware for MCP endpoint
```

### Modified Files

```
server/main.py               # Mount MCP router
server/requirements.txt      # Add: mcp>=1.26.0
server/services/config_service.py  # Support env vars for API keys (fallback from config.toml)
```

### Unchanged

Everything else — all existing tools, providers, services, React UI, canvas logic, DB, WebSocket.

## MCP Endpoint Integration

### mcp_endpoint.py — MCP Server Setup

```python
from mcp.server.fastmcp import FastMCP, Image
from services.tool_service import tool_service, TOOL_MAPPING
from services.config_service import config_service
from tools.utils.image_generation_core import IMAGE_PROVIDERS
from tools.utils.image_utils import get_image_info_and_save, generate_image_id
from tools.utils.image_canvas_utils import save_image_to_canvas
from services.config_service import FILES_DIR
import base64
import os

mcp = FastMCP(
    "Jaaz Image Generator",
    instructions="""...(tool selection guide)...""",
    stateless_http=True,
)

# Tools are registered dynamically based on available API keys
# Each tool: call provider → save to canvas → return base64 preview
```

### Tool Handler Pattern

Each MCP tool calls the provider `.generate()` method directly (NOT `generate_image_with_provider()` which returns localhost URLs), then saves to canvas and returns base64:

```python
@mcp.tool()
async def generate_image_gpt_image_1(
    prompt: str,
    aspect_ratio: str,
    canvas_id: str | None = None,
    input_images: list[str] | None = None,
) -> list:
    """Generate an image using GPT Image 1. Supports multiple input images for reference/editing."""

    # canvas_id defaults to per-user canvas (set by auth middleware context)
    canvas_id = canvas_id or get_user_canvas_id()

    # 1. Process input images (reuse existing logic)
    processed_images = None
    if input_images:
        processed_images = []
        for img_id in input_images:
            processed = await process_input_image(img_id)
            if processed:
                processed_images.append(processed)

    # 2. Call provider directly (NOT generate_image_with_provider which returns localhost URLs)
    provider = IMAGE_PROVIDERS["jaaz"]
    mime_type, width, height, filename = await provider.generate(
        prompt=prompt,
        model="openai/gpt-image-1",
        aspect_ratio=aspect_ratio,
        input_images=processed_images,
        metadata={"prompt": prompt, "model": "openai/gpt-image-1"},
    )

    # 3. Save to canvas (reuse existing canvas logic)
    session_id = f"mcp_{canvas_id}"
    await save_image_to_canvas(
        session_id, canvas_id, filename, mime_type, width, height
    )

    # 4. Read saved file and convert to base64 for Claude preview
    #    Resize to max 1024px for preview to avoid MCP size limits
    file_path = os.path.join(FILES_DIR, filename)
    image_base64 = create_preview_base64(file_path, max_size=1024)

    # 5. Return both image preview and canvas info
    canvas_url = f"https://{DEPLOY_HOST}/canvas/{canvas_id}"
    return [
        ImageContent(type="image", data=image_base64, mimeType="image/png"),
        TextContent(
            type="text",
            text=f"image_id: {filename}\nCanvas: {canvas_url}"
        ),
    ]
```

### Router Mounting

```python
# routers/mcp_router.py
from fastapi import APIRouter, Request, Response
from mcp_endpoint import mcp

router = APIRouter()

@router.post("/mcp")
@router.get("/mcp")
async def handle_mcp(request: Request) -> Response:
    # Auth check (Google OAuth token validation)
    # Forward to MCP transport
    ...

# main.py — add one line
app.include_router(mcp_router.router)
```

## Authentication

### Google OAuth for MCP Endpoint

```python
# routers/mcp_auth.py
from fastapi import Request, HTTPException
import httpx

ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "")

async def verify_google_oauth(request: Request) -> dict:
    """Verify Google OAuth token from MCP request."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth_header[7:]

    # Verify with Google
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"}
        )
        if res.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_info = res.json()

    # Domain check
    if ALLOWED_DOMAIN and not user_info["email"].endswith(f"@{ALLOWED_DOMAIN}"):
        raise HTTPException(status_code=403, detail=f"Only @{ALLOWED_DOMAIN} allowed")

    return user_info
```

Note: The exact OAuth flow depends on how Claude chat handles remote MCP authentication. If Claude supports the full OAuth dance (like Cloudflare's OAuthProvider pattern), we implement that. If it only supports Bearer token, we use the simpler token validation above. This will be determined during implementation.

## Environment Variables

```bash
# Provider API keys (at least one required)
JAAZ_API_KEY=xxx           # Covers most models
REPLICATE_API_KEY=xxx      # Optional: Imagen 4, Recraft, Flux Kontext
OPENAI_API_KEY=xxx         # Optional: GPT Image 1 direct
VOLCES_API_KEY=xxx         # Optional: Doubao series

# Google OAuth
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
ALLOWED_DOMAIN=yourcompany.com

# Deployment
DEPLOY_HOST=jaaz.yourcompany.com  # For canvas URL generation
DEFAULT_PORT=57988
```

### Config Service Update

`config_service.py` updated to also read from environment variables as fallback:

```python
# Priority: config.toml > environment variables
def _get_api_key(self, provider: str) -> str:
    # 1. Try config.toml
    key = self.app_config.get(provider, {}).get("api_key", "")
    if key:
        return key
    # 2. Fallback to env var
    env_map = {
        "jaaz": "JAAZ_API_KEY",
        "replicate": "REPLICATE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "volces": "VOLCES_API_KEY",
    }
    return os.environ.get(env_map.get(provider, ""), "")
```

## Tool Definitions

14 image generation tools (all video tools excluded):

| MCP Tool | Description | Provider | Model ID | input_images |
|---|---|---|---|---|
| `generate_image_gpt_image_1` | Multi-image reference, editing | jaaz | `openai/gpt-image-1` | Multiple |
| `generate_image_imagen_4` | High-quality realistic | jaaz | `google/imagen-4` | None |
| `generate_image_recraft_v3` | Vector design, text rendering | jaaz | `recraft-ai/recraft-v3` | None |
| `generate_image_ideogram_3` | Text-in-image | jaaz | `ideogram-ai/ideogram-v3-balanced` | None |
| `generate_image_flux_kontext_pro` | Single image editing, object removal | jaaz | `black-forest-labs/flux-kontext-pro` | Single |
| `generate_image_flux_kontext_max` | High-quality single image editing | jaaz | `black-forest-labs/flux-kontext-max` | Single |
| `generate_image_midjourney` | Artistic style generation | jaaz | `midjourney` | Single |
| `generate_image_doubao_seedream_3` | General generation | jaaz | `doubao-seedream-3` | None |
| `generate_image_doubao_seedream_3_volces` | General generation (Volces direct) | volces | `doubao-seedream-3-0-t2i-250301` | None |
| `edit_image_doubao_seededit_3` | Image editing (Volces direct) | volces | `doubao-seededit-3-0-i2i-250628` | Required, single |
| `generate_image_imagen_4_replicate` | Imagen 4 (Replicate direct) | replicate | `google/imagen-4` | None |
| `generate_image_recraft_v3_replicate` | Recraft (Replicate direct) | replicate | `recraft-ai/recraft-v3` | None |
| `generate_image_flux_kontext_pro_replicate` | Flux Kontext Pro (Replicate direct) | replicate | `black-forest-labs/flux-kontext-pro` | Single |
| `generate_image_flux_kontext_max_replicate` | Flux Kontext Max (Replicate direct) | replicate | `black-forest-labs/flux-kontext-max` | Single |

### Dynamic Registration

```python
async def register_mcp_tools(mcp_server):
    for tool_id, tool_info in TOOL_MAPPING.items():
        # Skip video tools
        if tool_info.get("type") == "video":
            continue
        # Only register if provider API key is available
        provider = tool_info.get("provider")
        if config_service.get_api_key(provider):
            register_mcp_tool(mcp_server, tool_id, tool_info)
```

## Image Generation + Canvas Flow

```
1. Claude calls MCP tool
   generate_image_gpt_image_1({ prompt: "a cat in suit", aspect_ratio: "1:1", canvas_id: "abc" })

2. MCP tool handler:
   a. Call existing provider: JaazImageProvider.generate()
      → provider downloads image, saves to user_data/files/{id}.png
      → returns (mime_type, width, height, filename)

   b. Save to canvas: save_image_to_canvas(session_id, canvas_id, filename, ...)
      → creates canvas element with position
      → saves to SQLite DB
      → broadcasts via WebSocket (if canvas UI is open, image appears in real-time)

   c. Read file → base64 encode → return as MCP ImageContent
      → Claude shows image preview in chat

   d. Return canvas URL
      → "Image placed on canvas: https://jaaz.yourcompany.com"

3. User opens canvas URL in browser
   → sees all generated images on infinite canvas
   → can drag, resize, layer, manually adjust
```

## Image Editing Flow

```
1. User in Claude: "Edit this image, change background to beach"

2. Claude calls MCP tool with previous image_id
   generate_image_flux_kontext_pro({
     prompt: "change background to beach",
     input_images: ["abc123.png"],
     canvas_id: "abc"
   })

3. MCP tool handler:
   a. process_input_image("abc123.png")
      → reads from user_data/files/abc123.png
      → converts to base64 data URL

   b. Call provider with input image
      → provider generates edited image

   c. Save new image to canvas (same flow as generation)

   d. Return base64 preview + canvas URL
```

## MCP Instructions

```
You are the Jaaz image generation assistant. Generated images are placed on an interactive canvas
where users can drag, resize, layer, and manually adjust them.

Tool selection guide:
- Multi-image reference editing -> GPT Image 1 (only tool supporting multiple input images)
- Single image editing / object removal -> Flux Kontext Pro or Max
- Vector design, text rendering -> Recraft v3
- Text embedded in images -> Ideogram 3
- High-quality realistic photos -> Imagen 4
- Artistic / creative style -> Midjourney
- Chinese text scenes -> Doubao Seedream 3
- Image editing (Volces) -> Doubao Seededit 3

When editing images, reference the image_id returned from previous generations.
For batches over 10 images, split into batches of max 10 each.
Always return the canvas URL so the user can open it for manual editing.
```

## MCP Prompt: plan_image_task

```python
@mcp.prompt()
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
5. Choose the right tool for each image based on the instructions
6. Answer in the SAME LANGUAGE as the task description"""
```

## Midjourney Special Handling

Midjourney uses async task creation + polling and returns multiple images:

```python
@mcp.tool()
async def generate_image_midjourney(
    prompt: str,
    canvas_id: str = "default",
    input_images: list[str] | None = None,
) -> list:
    """Generate images using Midjourney. Returns multiple artistic images."""
    jaaz_service = JaazService()

    # Process input images
    processed = None
    if input_images:
        processed = [await process_input_image(img) for img in input_images]
        processed = [p for p in processed if p]

    # Async generation with polling (existing JaazService logic)
    result = await jaaz_service.generate_image_by_midjourney(
        prompt=prompt, model="midjourney", input_images=processed
    )

    # Save all images to canvas and return previews
    content = []
    for img_data in result.get("images", []):
        image_id = generate_image_id()
        mime_type, width, height, ext = await get_image_info_and_save(
            img_data["url"], os.path.join(FILES_DIR, image_id)
        )
        filename = f"{image_id}.{ext}"
        await save_image_to_canvas(session_id, canvas_id, filename, mime_type, width, height)

        with open(os.path.join(FILES_DIR, filename), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        content.append(ImageContent(type="image", data=b64, mimeType=mime_type))

    content.append(TextContent(type="text", text=f"Generated {len(content)} images on canvas"))
    return content
```

## Dependencies Addition

```
# Update in server/requirements.txt (mcp already exists, update version constraint)
mcp>=1.26.0
httpx          # For Google OAuth token verification (may already be a transitive dep)
```

## Deployment (Zeabur)

1. Connect GitHub repo to Zeabur
2. Set root directory to `server/` (or configure build command)
3. Build React UI: `cd react && npm run build` → output to `react/dist/`
4. Set environment variables in Zeabur dashboard:
   - `JAAZ_API_KEY`, `REPLICATE_API_KEY`, etc.
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
   - `ALLOWED_DOMAIN=yourcompany.com`
   - `DEPLOY_HOST=jaaz.yourcompany.com`
5. Deploy
6. Employees add the MCP URL in Claude chat: `https://jaaz.yourcompany.com/mcp`
7. First use: Google OAuth login → done

## Known Issues and Mitigations

### 1. MCP ASGI Mounting (Critical)

FastMCP's `stateless_http=True` provides its own ASGI transport. Instead of manual router forwarding, mount the MCP app as a sub-application with auth middleware:

```python
# main.py
from mcp_endpoint import mcp

# Mount MCP as ASGI sub-app at /mcp
mcp_app = mcp.streamable_http_app()
app.mount("/mcp", AuthMiddleware(mcp_app, allowed_domain=ALLOWED_DOMAIN))
```

Note: The existing `socketio.ASGIApp(sio, other_asgi_app=app)` wrapping means Socket.IO handles `/socket.io` paths and delegates everything else (including `/mcp`) to FastAPI. This works without changes.

### 2. WebSocket session_id for Real-Time Canvas Updates

MCP tool calls use a hardcoded `session_id`. If no browser has an active Socket.IO connection with that session, the WebSocket broadcast silently does nothing — the canvas DB save still works, but the browser won't see updates in real-time.

**Mitigation**: The canvas URL opens a page that loads canvas data from DB on page load. Images will always be there — they just won't animate in live. This is acceptable for the initial version. A future enhancement could assign each OAuth user a stable session_id.

### 3. Canvas ID Discovery

Users interacting via Claude chat need to know which canvas to use. Solutions:

- **Default**: Each authenticated user gets a personal default canvas (keyed by email)
- **Add utility tool**: `list_canvases` tool lets Claude show available canvases
- **Auto-create**: If canvas_id doesn't exist, `save_image_to_canvas` does an upsert — verified in existing `db_service.save_canvas_data`

### 4. OAuth Flow

Claude.ai remote MCP supports OAuth 2.1. The implementation must provide:
- `GET /authorize` — redirect to Google OAuth
- `POST /token` — exchange code for access token
- OAuth client dynamic registration (or pre-configured client)

This follows the same pattern as shifu-toolbox but implemented in Python/FastAPI instead of Cloudflare Workers. If Claude's MCP client only sends Bearer tokens, fall back to the simpler token validation.

### 5. CORS

Add `CORSMiddleware` to FastAPI for Claude's MCP client cross-origin requests:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

### 6. File Storage Persistence

Cloud platforms (Zeabur, Railway) have ephemeral filesystems that reset on redeploy. Options:
- **Zeabur persistent volume**: mount at `/app/user_data` (simplest)
- **Object storage**: migrate to S3/R2 for images (future enhancement)
- **Acceptable loss**: for initial version, acknowledge that redeployment clears generated images

### 7. Base64 Image Size

Generated images can be large (5-10 MB → 7-14 MB base64). Mitigations:
- Return a compressed/resized thumbnail (e.g., max 1024px) as MCP ImageContent preview
- Full-resolution image stays on canvas, accessible via URL
- If image exceeds a size threshold, return only text with canvas URL, skip inline preview

### 8. localhost URL Leakage

Existing `generate_image_with_provider()` returns `http://localhost:{port}{url}`. MCP tools must NOT call this function directly — instead call the provider's `.generate()` method and `save_image_to_canvas()` separately, constructing the canvas URL with `DEPLOY_HOST`.

### 9. Tool Names

MCP tools use shorter names (e.g., `generate_image_gpt_image_1`) than the existing TOOL_MAPPING keys (e.g., `generate_image_by_gpt_image_1_jaaz`). A name mapping table in `definitions.py` maps TOOL_MAPPING keys to MCP tool names. Dynamic registration iterates TOOL_MAPPING but registers under the shorter MCP names.

### 10. Per-User Canvas Isolation

Multiple employees sharing `canvas_id="default"` would be chaotic. Solution: the MCP auth middleware extracts the user's email and the default canvas_id is derived from it (e.g., `canvas_{email_hash}`). Each user has their own canvas by default, with the option to specify a shared canvas_id explicitly.

## Error Handling

- Provider API failure: return sanitized text error to Claude (strip API keys/internal URLs)
- Image download failure: return text error with suggestion to retry
- Canvas save failure: return image preview (base64) even if canvas save fails, with warning
- Auth failure: HTTP 401/403
- Rate limiting: surface provider rate limit errors to Claude
- Missing canvas_id: auto-create per-user default canvas

## Future Enhancements (Out of Scope)

- Persistent object storage (S3/R2) instead of local filesystem
- Real-time WebSocket bridging between MCP session and canvas browser session
- Image cleanup / retention policy for storage management
- Token caching for Google OAuth validation (reduce per-request latency)
- `list_recent_images` tool for easier editing workflow in long conversations
