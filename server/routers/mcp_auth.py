"""Google OAuth authentication for MCP endpoint."""
import os
import httpx
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

            # Handle CORS preflight
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
