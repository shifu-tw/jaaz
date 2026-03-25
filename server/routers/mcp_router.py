"""Mount MCP server as ASGI sub-app on FastAPI."""
import os
from mcp_server import mcp_server
from routers.mcp_auth import MCPAuthMiddleware

ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "")

# Wrap MCP's ASGI app with auth middleware
# Note: FastAPI's CORSMiddleware does NOT apply to mounted sub-apps,
# so we handle CORS inside MCPAuthMiddleware.
mcp_asgi_app = MCPAuthMiddleware(
    mcp_server.streamable_http_app(),
    allowed_domain=ALLOWED_DOMAIN,
)
