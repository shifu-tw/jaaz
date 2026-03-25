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
