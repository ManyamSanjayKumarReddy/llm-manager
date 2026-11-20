"""Serves the built React dashboard from the same origin as the API."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_API_PREFIXES = ("api/", "v1/", "healthz", "install-agent.sh")


class SpaStaticFiles(StaticFiles):
    """Static files where unknown paths fall back to ``index.html`` (client-side routing).

    Paths under the API prefixes are never rewritten, so a mistyped API URL is a plain 404.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Return the file, or the app shell for unknown non-API paths."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith(_API_PREFIXES):
                raise
        shell = await super().get_response("index.html", scope)
        shell.headers["Cache-Control"] = "no-cache"  # hashed assets are cached, the shell is not
        return shell
