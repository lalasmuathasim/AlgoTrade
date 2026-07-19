from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


Fetcher = Callable[[str], str]


def _default_fetch(url: str) -> str:
    with urlopen(url, timeout=5) as response:  # noqa: S310
        return response.read().decode("utf-8")


def wait_for_url(
    url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
    fetcher: Fetcher | None = None,
) -> str:
    fetch = fetcher or _default_fetch
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    while time.monotonic() < deadline:
        try:
            return fetch(url)
        except (HTTPError, URLError, OSError) as exc:
            last_error = str(exc)
            time.sleep(interval_seconds)

    raise TimeoutError(f"Timed out waiting for {url}. Last error: {last_error or 'unknown error'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for an HTTP endpoint to become healthy.")
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    body = wait_for_url(
        args.url,
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
    )
    if args.output is not None:
        args.output.write_text(body, encoding="utf-8")
    else:
        print(body)


if __name__ == "__main__":
    main()
