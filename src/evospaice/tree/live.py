"""Loopback-only live merging lab. Azure inputs and computed results stay in memory."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import multiprocessing as mp
import os
import platform
import secrets
import subprocess
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from time import monotonic, perf_counter
from uuid import uuid4

import numpy as np

from evospaice.tree.centroid import NJ_BACKENDS, RANKS, Dataset, build_tree
from evospaice.tree.explore import (
    AzureMemoryStore,
    encode_hierarchy,
    render_html,
    representative_summaries,
    taxonomy_index,
)
from evospaice.tree.representations import METHODS

DEFAULT_PREFIX = (
    "https://mlstaiseqhacke1lkzk.blob.core.windows.net/"
    "azureml-blobstore-5d4c35ac-f934-4955-b80b-96faeb4e489c/"
    "embeddings/Lepidoptera-BIN-representatives/omni20m/subsets/"
    "butterfly-5000-seed42-20260917T081501Z/"
)
DEFAULT_SUBSCRIPTION = "caeead51-e874-4122-ba0e-c3c601c862ca"
ASSETS = Path(__file__).parent
MAX_BODY = 8192
MAX_BLOB = 64 * 1024 * 1024
MAX_UNPACKED = 128 * 1024 * 1024
JOB_SECONDS = 180


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class LiveAzureStore(AzureMemoryStore):
    """Read only the three pinned artifacts, with bounded reads and snapshot checks."""

    def load(self, expected_records: int | None = None) -> tuple[Dataset, dict]:
        try:
            reply = subprocess.check_output([
                "az", "account", "get-access-token", "--resource", "https://storage.azure.com/",
                "--subscription", self.subscription, "-o", "json",
            ], stderr=subprocess.PIPE, timeout=45)
            self._token = json.loads(reply)["accessToken"]
        except (OSError, subprocess.SubprocessError, KeyError, ValueError) as from_error:
            raise ValueError(
                "Azure authentication failed. Run az login for the configured subscription "
                "and ensure your identity has Storage Blob Data Reader access."
            ) from from_error
        self.blobs: dict[str, dict] = {}
        try:
            data, provenance = super().load(expected_records)
            manifest_hash = provenance["manifestSha256"]
            if hashlib.sha256(self.request("manifest.json")).hexdigest() != manifest_hash:
                raise ValueError("Azure manifest changed during loading; refresh again")
            if len(data.ids) > 10000 or data.embeddings.shape[1] > 512:
                raise ValueError("Live resource limit: at most 10,000 records and 512 dimensions")
            manifest = provenance["manifest"]
            if ("selection" in manifest
                    and manifest["selection"].get("records") != len(data.ids)):
                raise ValueError("Manifest selected-record count differs from the verified NPZ")
            if ("embedding_shape" in manifest
                    and manifest["embedding_shape"] != list(data.embeddings.shape)):
                raise ValueError("Manifest embedding shape differs from the verified NPZ")
            taxa = taxonomy_index(data)[0]
            counts = {rank: sum(t["rank"] == rank for t in taxa) for rank in RANKS}
            if ("distinct_taxa_by_full_path" in manifest
                    and manifest["distinct_taxa_by_full_path"] != counts):
                raise ValueError("Manifest taxonomy counts differ from the verified NPZ")
            for array in (data.ids, data.embeddings, data.taxonomy):
                array.flags.writeable = False
            provenance.update({"loadedUtc": utcnow(), "blobs": self.blobs})
            return data, provenance
        finally:
            self._token = None

    def request(self, name: str, data: bytes | None = None) -> bytes:
        if (name not in {"manifest.json", "embeddings.npz", "selected-records.tsv"}
                or data is not None):
            raise ValueError("Live Azure source is read-only and restricted to three artifacts")
        headers = {"Authorization": f"Bearer {self._token}", "x-ms-version": "2023-11-03"}
        if name in self.blobs:
            headers["If-Match"] = self.blobs[name]["etag"]
        request = urllib.request.Request(self.prefix + name, headers=headers)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None

        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
                etag = response.headers.get("ETag")
                if not etag:
                    raise ValueError(f"Azure response is missing its version ETag: {name}")
                content = response.read(MAX_BLOB + 1)
                if len(content) > MAX_BLOB:
                    raise ValueError(f"Azure artifact exceeds the 64 MiB live limit: {name}")
                self.blobs[name] = {
                    "etag": etag, "lastModified": response.headers.get("Last-Modified"),
                    "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                }
        except urllib.error.HTTPError as error:
            if error.code == 412:
                raise ValueError("Azure source changed during loading; refresh again") from None
            raise ValueError(
                f"Azure read failed (HTTP {error.code}) for {name}. "
                "Check the configured prefix and your storage data permissions."
            ) from None
        except (OSError, urllib.error.URLError):
            raise ValueError(
                "Azure is unreachable or timed out; check your connection and refresh"
            ) from None
        if name == "embeddings.npz":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > MAX_UNPACKED:
                    raise ValueError("NPZ exceeds the 128 MiB uncompressed live limit")
        return content


def compute_payload(data: Dataset, provenance: dict, parameters: dict, progress) -> dict:
    """Rebuild only requested methods on the selected descendants, never induced pruning."""
    started = perf_counter()
    path = parameters["path"]
    mask = np.ones(len(data.ids), dtype=bool)
    for depth, label in enumerate(path):
        mask &= data.taxonomy[:, depth] == label
    scoped = Dataset(
        data.ids[mask], data.embeddings[mask], data.taxonomy[mask],
        {**data.coverage, "outside_requested_clade": int((~mask).sum()),
         "retained": int(mask.sum())},
    )
    if not len(scoped.ids):
        raise ValueError("Selected clade no longer exists; refresh the taxonomy selection")
    taxa, paths = taxonomy_index(scoped)
    trees, methods = {}, {}
    for index, method in enumerate(parameters["methods"]):
        progress(f"Rebuilding {METHODS[method]['label']} ({index + 1}/"
                 f"{len(parameters['methods'])}) on {len(scoped.ids)} records")
        step = perf_counter()
        tree, diagnostics = build_tree(
            scoped, method=method, nj_backend=parameters["backend"],
            max_children=parameters["maxChildren"],
        )
        encoded = encode_hierarchy(tree, paths)
        encoded["representatives"] = representative_summaries(
            scoped, tree, encoded, paths, method,
        )
        trees[method] = encoded
        methods[method] = {**METHODS[method], "seconds": perf_counter() - step,
                           "diagnostics": diagnostics}
    return {
        "schemaVersion": 1, "records": len(scoped.ids), "dimensions": scoped.embeddings.shape[1],
        "taxa": taxa, "trees": trees, "methods": methods, "coverage": scoped.coverage,
        "counts": {rank: sum(t["rank"] == rank for t in taxa) for rank in RANKS},
        "provenance": provenance,
        "computation": {
            "live": True, "cached": False, "sourceGeneration": parameters["generation"],
            "scope": "Rebuilt from all selected descendants, not pruned from a full-cohort tree. "
                     "Ancestor ranks above the selected clade are unary context only.",
            "path": path, "backend": parameters["backend"],
            "maxChildren": parameters["maxChildren"], "methods": parameters["methods"],
            "seconds": perf_counter() - started, "createdUtc": utcnow(),
            "versions": {name: version(name) for name in ("numpy", "scipy", "scikit-bio")},
            "python": platform.python_version(),
            "initialTaxon": paths[tuple(path)] if path else (
                taxa[0]["children"][0] if len(taxa[0]["children"]) == 1 else 0
            ),
        },
    }


def _worker(connection, kind: str, config: dict, data, provenance, parameters):
    """A disposable spawned process makes cancel/timeout terminate actual numerical work."""
    try:
        if kind == "refresh":
            connection.send(("progress", "Authenticating and verifying three Azure artifacts"))
            store = LiveAzureStore(config["prefix"], config["subscription"])
            result = store.load(config["records"])
        else:
            result = compute_payload(
                data, provenance, parameters,
                lambda message: connection.send(("progress", message)),
            )
        connection.send(("result", result))
    except ValueError as error:
        connection.send(("error", str(error)))
    except Exception:
        # Do not expose request headers, Azure CLI output, tokens, or tracebacks to the browser.
        connection.send(("error", "The worker failed to load or compute this request. "
                         "Check the source bundle and selected numerical parameters."))
    finally:
        connection.close()


class LiveState:
    """One active job; eight status records; only the latest successful result in RAM."""

    def __init__(self, config: dict, *, dataset=None, provenance=None, timeout=JOB_SECONDS):
        self.config = config
        self.data = dataset
        self.provenance = provenance or {}
        self.generation = uuid4().hex if dataset is not None else None
        self.csrf = secrets.token_urlsafe(32)
        self.timeout = timeout
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.active = None
        self.result = None
        self.result_id = None
        self.context = mp.get_context("spawn")
        self._closed = False

    def metadata(self) -> dict:
        with self.lock:
            taxa = taxonomy_index(self.data)[0] if self.data is not None else []
            return {
                "ready": self.data is not None, "generation": self.generation,
                "records": len(self.data.ids) if self.data is not None else 0,
                "dimensions": self.data.embeddings.shape[1] if self.data is not None else 0,
                "taxa": taxa, "methods": METHODS, "backends": NJ_BACKENDS,
                "source": self.provenance or {"subsetPrefix": self.config["prefix"]},
                "activeJob": self.active["id"] if self.active else None, "csrfToken": self.csrf,
            }

    def start(self, kind: str, parameters: dict) -> dict:
        parameters = json.loads(json.dumps(parameters))
        with self.lock:
            if self._closed:
                raise ValueError("Service is shutting down")
            if self.active:
                raise BusyError("Another job is running; wait or cancel it first")
            if kind == "compute":
                self._validate(parameters)
            elif kind != "refresh" or parameters:
                raise ValueError("Refresh takes an empty JSON object")
            job_id = uuid4().hex
            receive, send = self.context.Pipe(duplex=False)
            process = self.context.Process(
                target=_worker,
                args=(send, kind, self.config, self.data if kind == "compute" else None,
                      self.provenance, parameters),
                daemon=True,
            )
            cancel = threading.Event()
            job = {"id": job_id, "kind": kind, "status": "running", "progress": "Starting worker",
                   "createdUtc": utcnow(), "parameters": parameters, "cached": False}
            # Failed refreshes must not silently leave an older snapshot available for new runs.
            if kind == "refresh":
                self.data = None
                self.generation = None
                self.provenance = {"subsetPrefix": self.config["prefix"]}
            self.result = self.result_id = None
            try:
                process.start()
            except (OSError, RuntimeError):
                receive.close()
                send.close()
                raise ValueError("Cannot start the isolated worker; restart the local service") \
                    from None
            send.close()
            self.jobs[job_id] = job
            while len(self.jobs) > 8:
                del self.jobs[next(iter(self.jobs))]
            self.active = {"id": job_id, "cancel": cancel}
            monitor = threading.Thread(
                target=self._monitor, args=(job, process, receive, cancel), daemon=True,
            )
            self.active["thread"] = monitor
            monitor.start()
            return dict(job)

    def _validate(self, parameters: dict):
        if self.data is None:
            raise ValueError("Load and verify the Azure dataset before running merges")
        if set(parameters) != {"generation", "path", "methods", "backend", "maxChildren"}:
            raise ValueError("Specify generation, path, methods, backend, and maxChildren only")
        if parameters["generation"] != self.generation:
            raise BusyError("Source version is stale; reload the current taxonomy before running")
        path, methods = parameters["path"], parameters["methods"]
        if (not isinstance(path, list) or len(path) > 4
                or any(not isinstance(label, str) for label in path)):
            raise ValueError("Clade path must contain zero to four taxonomy labels")
        _, paths = taxonomy_index(self.data)
        if tuple(path) not in paths:
            raise ValueError("Unknown taxonomy path")
        if (not isinstance(methods, list) or not 1 <= len(methods) <= len(METHODS)
                or any(not isinstance(m, str) or m not in METHODS for m in methods)
                or len(set(methods)) != len(methods)):
            raise ValueError(f"Select one to {len(METHODS)} distinct supported methods")
        if parameters["backend"] not in NJ_BACKENDS:
            raise ValueError("Unsupported NJ backend")
        maximum = parameters["maxChildren"]
        if type(maximum) is not int or not 2 <= maximum <= 512:
            raise ValueError("maxChildren must be an integer between 2 and 512")

    def _monitor(self, job, process, receive, cancel):
        started = monotonic()
        outcome, value = "failed", "Worker exited without returning a result"
        try:
            while True:
                if cancel.is_set():
                    outcome, value = "cancelled", "Cancelled; worker terminated, no result retained"
                    break
                if monotonic() - started > self.timeout:
                    value = f"Job exceeded {self.timeout} seconds; choose a smaller clade"
                    break
                if receive.poll(.1):
                    kind, content = receive.recv()
                    if kind == "progress":
                        with self.lock:
                            job["progress"] = content
                        continue
                    outcome, value = ("succeeded", content) if kind == "result" else (
                        "failed", content,
                    )
                    break
                if not process.is_alive():
                    break
        except (EOFError, OSError):
            value = "Worker stopped before producing a complete result"
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            receive.close()
        with self.lock:
            if cancel.is_set():
                outcome, value = "cancelled", "Cancelled; no result retained"
            if outcome == "succeeded":
                if job["kind"] == "refresh":
                    self.data, self.provenance = value
                    self.generation = uuid4().hex
                    job["generation"] = self.generation
                    job["records"] = len(self.data.ids)
                else:
                    self.result, self.result_id = value, job["id"]
                    job["seconds"] = value["computation"]["seconds"]
                    job["records"] = value["records"]
                    job["resultUrl"] = f"/api/jobs/{job['id']}/result"
                    job["viewUrl"] = f"/api/jobs/{job['id']}/view"
                job["progress"] = "Verified Azure data loaded" if job["kind"] == "refresh" else (
                    "Newly computed; not cached"
                )
            else:
                job["error"] = value
            job["status"], job["finishedUtc"] = outcome, utcnow()
            self.active = None

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            if self.active and self.active["id"] == job_id:
                self.active["cancel"].set()
                self.jobs[job_id]["progress"] = "Cancelling worker"
            return dict(self.jobs[job_id])

    def close(self):
        with self.lock:
            self._closed = True
            active = self.active
            if active:
                active["cancel"].set()
        if active:
            active["thread"].join(timeout=10)


class BusyError(ValueError):
    pass


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, state: LiveState):
        if address[0] != "127.0.0.1":
            raise ValueError(
                "Live service must bind to 127.0.0.1; remote authentication is not enabled"
            )
        self.state = state
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, LiveHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self):
        self.state.close()
        super().server_close()


class LiveHandler(BaseHTTPRequestHandler):
    server_version = "MergingLab/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # No URLs, source labels, request bodies, or credentials in access logs.
        pass

    def _reply(self, status: int, value, content_type="application/json"):
        body = (json.dumps(value, allow_nan=False).encode() if content_type == "application/json"
                else value.encode() if isinstance(value, str) else value)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; "
                         "object-src 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _guard(self, mutation=False) -> bool:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if (host not in hosts or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or (origin is not None and origin != f"http://{host}")):
            self._reply(403, {"error": "Only same-origin loopback requests are allowed"})
            return False
        if mutation and (
            origin != f"http://{host}" or not secrets.compare_digest(
                self.headers.get("X-Live-Token", ""), self.server.state.csrf,
            )
        ):
            self._reply(403, {"error": "Missing same-origin session token; reload the live page"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        state = self.server.state
        if self.path == "/health":
            self._reply(200, {"status": "ok", "mode": "loopback-only",
                              "ready": state.data is not None})
        elif self.path in {"/", "/live.js"}:
            name, mime = ("live.html", "text/html; charset=utf-8") if self.path == "/" else (
                "live.js", "text/javascript; charset=utf-8",
            )
            self._reply(200, (ASSETS / name).read_bytes(), mime)
        elif self.path == "/api/source":
            self._reply(200, state.metadata())
        else:
            parts = self.path.strip("/").split("/")
            if len(parts) not in (3, 4) or parts[:2] != ["api", "jobs"]:
                self._reply(404, {"error": "Unknown route"})
                return
            with state.lock:
                job = state.jobs.get(parts[2])
                if job is None:
                    self._reply(404, {"error": "Job not found or expired"})
                elif len(parts) == 3:
                    self._reply(200, job)
                elif parts[3] not in {"result", "view"}:
                    self._reply(404, {"error": "Unknown route"})
                elif state.result_id != job["id"]:
                    self._reply(410, {"error": "Result unavailable; run merges again"})
                elif parts[3] == "result":
                    self._reply(200, state.result)
                else:
                    self._reply(200, render_html(state.result), "text/html; charset=utf-8")

    def do_POST(self):
        if not self._guard(mutation=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
            self._reply(413, {"error": "Supply Content-Length for at most 8192 bytes"})
            return
        if self.headers.get("Content-Type") != "application/json":
            self._reply(415, {"error": "Use application/json"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            state = self.server.state
            if self.path == "/api/refresh":
                response = state.start("refresh", body)
            elif self.path == "/api/jobs":
                response = state.start("compute", body)
            else:
                parts = self.path.strip("/").split("/")
                if (len(parts) != 4 or parts[:2] != ["api", "jobs"]
                        or parts[3] != "cancel" or body):
                    self._reply(404, {"error": "Unknown route"})
                    return
                response = state.cancel(parts[2])
            self._reply(202, response)
        except BusyError as error:
            self._reply(409, {"error": str(error)})
        except (ValueError, TypeError) as error:
            self._reply(400, {"error": str(error)})
        except KeyError:
            self._reply(404, {"error": "Job not found or expired"})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--azure-prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--subscription", default=DEFAULT_SUBSCRIPTION)
    parser.add_argument("--expect-records", type=int, default=5000)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 1 <= args.expect_records <= 10000 or not 0 <= args.port <= 65535:
        parser.error("expect-records must be 1–10000 and port must be 0–65535")
    store = LiveAzureStore(args.azure_prefix, args.subscription)
    # Spawned numerical workers inherit bounded native thread pools.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    state = LiveState({"prefix": store.prefix, "subscription": args.subscription,
                       "records": args.expect_records})
    with LiveServer(("127.0.0.1", args.port), state) as server:
        print(f"Live merging lab: http://127.0.0.1:{server.server_port}/", flush=True)
        print("Localhost only; Azure data and results remain in RAM. Ctrl+C to stop.", flush=True)
        state.start("refresh", {})
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
