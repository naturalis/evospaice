"""In-memory synthetic live/static fixture; no Azure credentials or dataset files."""

import argparse
import os

from test_explorer import synthetic_dataset

from evospaice.tree.explore import generate_payload, render_html
from evospaice.tree.live import LiveHandler, LiveServer, LiveState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    data = synthetic_dataset()
    static = render_html(generate_payload(data, provenance={"kind": "Synthetic fixture"}))

    class Handler(LiveHandler):
        def do_GET(self):
            if self.path == "/synthetic" and self._guard():
                self._reply(200, static, "text/html; charset=utf-8")
            else:
                super().do_GET()

    state = LiveState(
        {"prefix": "https://example.blob.core.windows.net/container/synthetic/",
         "subscription": "synthetic", "records": 48},
        dataset=data, provenance={"kind": "Synthetic browser fixture"},
    )
    with LiveServer(("127.0.0.1", args.port), state) as server:
        server.RequestHandlerClass = Handler
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
