"""Serve the Evospaice Taxonium viewer and its Newick input."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VIEWER_PATH = "/src/evospaice/viz/taxonium/"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    handler = partial(SimpleHTTPRequestHandler, directory=REPOSITORY_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Taxonium viewer: http://localhost:{args.port}{VIEWER_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()