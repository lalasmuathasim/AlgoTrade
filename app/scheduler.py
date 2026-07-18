"""Compatibility wrapper for the legacy app package."""

from backend.app.scheduler import run_scheduler


if __name__ == "__main__":
    run_scheduler()
