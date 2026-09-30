"""Command-line entry point: ``planrunner [--server URI] [--api-key KEY] [--connect]``."""

import argparse
import logging
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from planrunner.app import App, AppOptions

DESCRIPTION = """\
===============================================================================
      GUI for building, scheduling and running Bluesky plans on a queueserver
===============================================================================
"""


def _version() -> str:
    try:
        return version("planrunner")
    except PackageNotFoundError:
        return "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="planrunner",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"PlanRunner {_version()}")
    parser.add_argument(
        "-s", "--server",
        default=os.environ.get("QSERVER_HTTP_SERVER_URI"),
        help="bluesky-httpserver address, e.g. http://localhost:60610 "
             "(default: $QSERVER_HTTP_SERVER_URI, else the last server used)",
    )
    parser.add_argument(
        "-k", "--api-key",
        help="API key for the server. Normally not needed: planrunner uses the key the bsqs "
             "role deploys (/etc/qs_client/<server host>, then $QSERVER_HTTP_SERVER_API_KEY). "
             "Without any key it connects read only.",
    )
    parser.add_argument("-c", "--connect", action="store_true",
                        help="connect as soon as the window opens")
    parser.add_argument(
        "--source", action="append", default=[], metavar="PATH",
        help="a local checkout the plan source viewer reads (the profile collection, "
             "hextools, ...); repeat for several",
    )
    parser.add_argument("--debug", action="store_true", help="log debug messages")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    options = AppOptions(
        server_uri=args.server,
        api_key=args.api_key,
        connect=args.connect,
        source_roots=tuple(Path(p) for p in args.source),
    )
    sys.exit(App(options).run())


if __name__ == "__main__":
    main()
