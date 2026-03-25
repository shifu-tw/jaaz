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
