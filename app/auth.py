"""Simple HTTP Basic Auth gate for the whole app.

This data has FEINs and personal contact info in it, and Vercel deployments
are reachable by anyone with the URL by default. Set APP_USERNAME/APP_PASSWORD
as environment variables to require a login; leave them unset (e.g. local dev)
and the app stays open, matching the previous no-auth behavior.
"""

import base64
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="H-2A Transfer Matcher"'},
        content="Authentication required.",
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self.username = username
        self.password = password

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization")
        if not header or not header.startswith("Basic "):
            return _unauthorized()
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
        except Exception:
            return _unauthorized()
        if not (secrets.compare_digest(user, self.username) and secrets.compare_digest(pwd, self.password)):
            return _unauthorized()
        return await call_next(request)


def add_auth_middleware(app) -> None:
    username = os.environ.get("APP_USERNAME")
    password = os.environ.get("APP_PASSWORD")
    if not username or not password:
        return
    app.add_middleware(BasicAuthMiddleware, username=username, password=password)
