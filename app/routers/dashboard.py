"""Compatibility wrapper for the legacy app package."""

from backend.app.routers.dashboard import router as router

__all__ = ["router"]
