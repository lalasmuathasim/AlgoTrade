"""Compatibility wrapper for the legacy app package."""

from backend.app.worker import run_worker


if __name__ == "__main__":
    run_worker()

