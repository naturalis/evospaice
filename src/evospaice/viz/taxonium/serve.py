"""Serve the Evospaice Taxonium viewer and its Newick input."""

# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import gzip
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VIEWER_PATH = "/src/evospaice/viz/taxonium/"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RICH_TAXONOMY_PATH = "/data/unified_taxonomic_tree_metadata.tsv"


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        if request_path == RICH_TAXONOMY_PATH and accepts_gzip:
            source_path = Path(self.translate_path(request_path))
            if source_path.is_file():
                content = gzip.compress(source_path.read_bytes(), mtime=0)
                self.send_response(200)
                self.send_header("Content-Type", "text/tab-separated-values")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", str(len(content)))
                self.send_header(
                    "Last-Modified",
                    self.date_time_string(source_path.stat().st_mtime),
                )
                self.end_headers()
                self.wfile.write(content)
                return
        super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    handler = partial(ViewerRequestHandler, directory=REPOSITORY_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Taxonium viewer: http://localhost:{args.port}{VIEWER_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()