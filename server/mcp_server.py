"""MCP Server for Jaaz image generation.

Registers image generation tools dynamically based on available API keys.
Each tool calls providers directly, saves to canvas, returns base64 preview.
"""
import os
from mcp.server.fastmcp import FastMCP
from services.config_service import config_service
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

# Tool definition table
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


def _has_provider_key(provider: str) -> bool:
    """Check if a provider has an API key configured (config.toml or env var)."""
    return bool(config_service.get_api_key(provider))


def register_all_tools():
    """Register MCP tools for all providers with available API keys.

    MUST be called after config_service.initialize() (from FastAPI lifespan).
    """
    registered_count = 0
    for tool_name, tool_def in TOOL_DEFS.items():
        provider = tool_def["provider"]
        if not _has_provider_key(provider):
            continue

        supports_input = tool_def.get("supports_input", False)
        is_midjourney = tool_def.get("is_midjourney", False)

        if is_midjourney:
            _register_midjourney_tool(tool_name, tool_def)
        elif supports_input:
            _register_tool_with_input(tool_name, tool_def)
        else:
            _register_tool_no_input(tool_name, tool_def)

        registered_count += 1

    print(f"\u2705 MCP: Registered {registered_count} tools")


def _register_tool_no_input(name: str, tool_def: dict):
    @mcp_server.tool(name=name, description=tool_def["description"])
    async def handler(prompt: str, aspect_ratio: str, canvas_id: str = "") -> list:
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
    async def handler(prompt: str, aspect_ratio: str, canvas_id: str = "", input_images: list[str] | None = None) -> list:
        cid = canvas_id or "default"
        return await _generate_image(
            provider_name=tool_def["provider"],
            model=tool_def["model"],
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            canvas_id=cid,
            input_images=input_images,
        )


def _register_midjourney_tool(name: str, tool_def: dict):
    """Midjourney uses a special handler (async polling, multi-image return)."""
    from mcp_tools import _generate_midjourney

    @mcp_server.tool(name=name, description=tool_def["description"])
    async def handler(prompt: str, canvas_id: str = "", input_images: list[str] | None = None) -> list:
        cid = canvas_id or "default"
        return await _generate_midjourney(prompt=prompt, canvas_id=cid, input_images=input_images)


# Planning Prompt
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
