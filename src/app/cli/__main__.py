"""Entry point: `python -m app.cli [--url URL] [--agent NAME]`."""

from __future__ import annotations

import argparse
import os

from app.cli.app import ManfredCli

_DEFAULT_URL = os.environ.get("MANFRED_API_URL", "http://localhost:3000")


def main() -> None:
    parser = argparse.ArgumentParser(prog="manfred-cli", description="Manfred terminal client")
    parser.add_argument("--url", default=_DEFAULT_URL, help=f"Backend base URL (default {_DEFAULT_URL})")
    parser.add_argument("--agent", default=None, help="Agent to start with (default: first available)")
    args = parser.parse_args()
    ManfredCli(base_url=args.url, agent=args.agent).run()


if __name__ == "__main__":
    main()
