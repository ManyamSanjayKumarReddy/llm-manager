"""Liveness probe."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Used by Docker health checks; needs no authentication and reveals nothing."""
    return {"ok": True}
