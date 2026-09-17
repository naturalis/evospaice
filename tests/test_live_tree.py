import hashlib
import http.client
import io
import json
import threading
import time
import urllib.error
from unittest.mock import patch

import numpy as np
import pytest
from test_explorer import azure_fixture, synthetic_dataset

from evospaice import cli
from evospaice.tree import live
from evospaice.tree.explore import render_html
from evospaice.tree.live import BusyError, LiveAzureStore, LiveServer, LiveState, compute_payload

CONFIG = {"prefix": "https://example.blob.core.windows.net/container/subset/",
          "subscription": "synthetic", "records": 48}


def parameters(state, **changes):
    return {"generation": state.generation, "path": [],
            "methods": ["centroid", "wasserstein"], "backend": "skbio",
            "maxChildren": 512, **changes}


def wait_job(state, job, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with state.lock:
            status = dict(state.jobs[job["id"]])
        if status["status"] != "running":
            return status
        time.sleep(.05)
    pytest.fail("Job did not reach a terminal state")


class Response:
    def __init__(self, content, etag='"version-1"'):
        self.content = content
        self.headers = {"ETag": etag, "Last-Modified": "Wed, 17 Sep 2026 08:15:01 GMT"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        assert size == live.MAX_BLOB + 1
        return self.content[:size]


def test_live_azure_authenticated_snapshot_and_no_local_writes():
    blobs = azure_fixture()
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert timeout == 60
            assert request.get_header("Authorization") == "Bearer test-only-token"
            return Response(blobs[request.full_url.rsplit("/", 1)[-1]])

    store = LiveAzureStore(CONFIG["prefix"], CONFIG["subscription"])
    with (patch("evospaice.tree.live.subprocess.check_output",
                return_value=b'{"accessToken":"test-only-token"}') as auth,
          patch("evospaice.tree.live.urllib.request.build_opener",
                return_value=Opener()) as opener,
          patch("builtins.open", side_effect=AssertionError("No file I/O allowed"))):
        data, provenance = store.load(48)
        auth.assert_called_once()
        assert auth.call_args.kwargs["timeout"] == 45
        assert len(data.ids) == 48
        assert store._token is None
        assert not data.embeddings.flags.writeable
        assert len(requests) == 4
        assert requests[-1].get_header("If-match") == '"version-1"'
        assert set(provenance["blobs"]) == set(blobs)
        assert provenance["blobs"]["embeddings.npz"]["sha256"] == hashlib.sha256(
            blobs["embeddings.npz"],
        ).hexdigest()
        assert "loadedUtc" in provenance
        assert "test-only-token" not in json.dumps(provenance)
        handler = opener.call_args.args[0]()
        assert handler.redirect_request(None, None, 302, "", {}, "https://evil.test") is None
        store.load(48)
        assert auth.call_count == 2  # Refresh obtains a new Azure CLI token.


@pytest.mark.parametrize("mode", ["checksum", "changed", "etag", "huge", "http"])
def test_live_azure_rejects_invalid_or_changed_snapshot(mode, monkeypatch):
    blobs = azure_fixture()
    manifest_calls = 0

    class Opener:
        def open(self, request, timeout):
            nonlocal manifest_calls
            name = request.full_url.rsplit("/", 1)[-1]
            content = blobs[name]
            if name == "manifest.json":
                manifest_calls += 1
            if mode == "http":
                raise urllib.error.HTTPError(request.full_url, 412, "changed", {}, None)
            if mode == "checksum" and name == "embeddings.npz":
                content += b"x"
            if mode == "changed" and manifest_calls == 2:
                content += b" "
            return Response(content, None if mode == "etag" else '"v1"')

    if mode == "huge":
        monkeypatch.setattr(live, "MAX_UNPACKED", 10)
    store = LiveAzureStore(CONFIG["prefix"], CONFIG["subscription"])
    with (patch("evospaice.tree.live.subprocess.check_output",
                return_value=b'{"accessToken":"test-only-token"}'),
          patch("evospaice.tree.live.urllib.request.build_opener", return_value=Opener()),
          pytest.raises(ValueError)):
        store.load(48)
    assert store._token is None


def test_live_azure_auth_errors_do_not_disclose_cli_output():
    store = LiveAzureStore(CONFIG["prefix"], CONFIG["subscription"])
    error = live.subprocess.CalledProcessError(1, ["az"], output=b"sensitive-token")
    with (patch("evospaice.tree.live.subprocess.check_output", side_effect=error),
          pytest.raises(ValueError, match="Azure authentication failed") as caught):
        store.load(48)
    assert "sensitive-token" not in str(caught.value)
    with pytest.raises(ValueError, match="read-only"):
        store.request("something-else.npz")
    with pytest.raises(ValueError, match="read-only"):
        store.request("embeddings.npz", b"never-upload")


@pytest.mark.parametrize("declaration", [
    {"selection": {"records": 5000}},
    {"embedding_shape": [48, 256]},
    {"distinct_taxa_by_full_path": {"family": 99}},
])
def test_manifest_declarations_must_match_actual_data(declaration):
    blobs = azure_fixture()
    blobs["manifest.json"] = json.dumps({
        **json.loads(blobs["manifest.json"]), **declaration,
    }).encode()
    store = LiveAzureStore(CONFIG["prefix"], CONFIG["subscription"])
    with (patch("evospaice.tree.live.subprocess.check_output",
                return_value=b'{"accessToken":"synthetic"}'),
          patch.object(store, "request", side_effect=lambda name: blobs[name]),
          pytest.raises(ValueError, match="Manifest")):
        store.load(48)


def test_scoped_computation_is_lazy_exact_and_does_not_mutate_input():
    data = synthetic_dataset()
    before = data.embeddings.copy()
    state = LiveState(CONFIG, dataset=data)
    args = parameters(state, path=["Lepidoptera", "Family B"], methods=["medoid", "weighted"])
    updates = []
    with patch("evospaice.tree.live.build_tree", wraps=live.build_tree) as build:
        result = compute_payload(data, {"loadedUtc": "synthetic"}, args, updates.append)
    assert build.call_count == 2
    assert [call.kwargs["method"] for call in build.call_args_list] == ["medoid", "weighted"]
    assert result["records"] == 12
    assert result["counts"] == {"order": 1, "family": 1, "genus": 2, "species": 6}
    assert set(result["trees"]) == {"medoid", "weighted"}
    assert result["computation"]["cached"] is False
    assert "not pruned" in result["computation"]["scope"]
    assert result["taxa"][result["computation"]["initialTaxon"]]["label"] == "Family B"
    np.testing.assert_array_equal(before, data.embeddings)
    assert len(updates) == 2
    assert "live-result" in render_html(result)
    for tree in result["trees"].values():
        assert len([n for n in tree["nodes"] if not n["children"]]) == 12


def test_real_job_lifecycle_concurrency_input_copy_failure_cancel_and_timeout():
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    try:
        args = parameters(state, methods=["centroid"])
        job = state.start("compute", args)
        args["methods"].append("medoid")
        with pytest.raises(BusyError, match="Another job"):
            state.start("compute", parameters(state))
        finished = wait_job(state, job)
        assert finished["status"] == "succeeded", finished
        assert finished["cached"] is False
        assert set(state.result["trees"]) == {"centroid"}
        assert finished["records"] == 48
        failed = state.start("compute", parameters(state, maxChildren=2))
        assert state.result is None
        finished = wait_job(state, failed)
        assert finished["status"] == "failed", finished
        assert "exceeding" in finished["error"]
        cancelled = state.start("compute", parameters(state))
        state.cancel(cancelled["id"])
        assert wait_job(state, cancelled)["status"] == "cancelled"
        assert state.active is None and state.result is None
        state.timeout = .001
        timed_out = state.start("compute", parameters(state))
        finished = wait_job(state, timed_out)
        assert finished["status"] == "failed"
        assert "exceeded" in finished["error"]
    finally:
        state.close()


def test_all_five_methods_can_be_computed_in_one_live_job():
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    try:
        methods = list(live.METHODS)
        job = state.start("compute", parameters(state, methods=methods))
        finished = wait_job(state, job)
        assert finished["status"] == "succeeded", finished
        assert set(state.result["trees"]) == set(methods)
        assert set(state.result["methods"]) == set(methods)
        assert finished["records"] == 48
        for tree in state.result["trees"].values():
            assert len([n for n in tree["nodes"] if not n["children"]]) == 48
    finally:
        state.close()


def test_refresh_invalidates_data_even_when_cancelled():
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    old_generation = state.generation
    try:
        job = state.start("refresh", {})
        assert state.data is None and state.generation is None
        state.cancel(job["id"])
        assert wait_job(state, job)["status"] == "cancelled"
        assert not state.metadata()["ready"]
        with pytest.raises(ValueError, match="Load and verify"):
            state.start("compute", parameters(state, generation=old_generation))
    finally:
        state.close()


def test_job_history_is_bounded_and_shutdown_terminates_work():
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    try:
        for _ in range(10):
            job = state.start("compute", parameters(state))
            state.cancel(job["id"])
            assert wait_job(state, job)["status"] == "cancelled"
        assert len(state.jobs) == 8
        last = state.start("compute", parameters(state))
        monitor = state.active["thread"]
        state.close()
        assert not monitor.is_alive()
        assert wait_job(state, last)["status"] == "cancelled"
        assert state.active is None
        with pytest.raises(ValueError, match="shutting down"):
            state.start("compute", parameters(state))
    finally:
        state.close()


def test_native_math_failure_is_reported_not_replaced_with_a_fake_result():
    data = synthetic_dataset()
    data.embeddings[0] = -data.embeddings[1]
    state = LiveState(CONFIG, dataset=data)
    try:
        job = state.start("compute", parameters(
            state, methods=["frechet"],
            path=["Lepidoptera", "Family A", "Shared genus", "Species A"],
        ))
        failed = wait_job(state, job)
        assert failed["status"] == "failed"
        assert "antipodal" in failed["error"]
        assert state.result is None
    finally:
        state.close()


@pytest.mark.parametrize("changes", [
    {"methods": []}, {"methods": list(live.METHODS) + ["centroid"]},
    {"methods": ["centroid", "centroid"]}, {"methods": ["fake"]},
    {"methods": [{}]}, {"path": ["missing"]}, {"path": "Lepidoptera"},
    {"path": [[], []]}, {"backend": "shell"}, {"maxChildren": True},
    {"maxChildren": 513}, {"maxChildren": 1}, {"maxChildren": 2.5},
    {"generation": "stale"}, {"url": "http://evil.test/"},
])
def test_invalid_inputs_are_rejected_without_starting_work(changes):
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    with pytest.raises(ValueError):
        state.start("compute", parameters(state, **changes))
    assert not state.jobs and state.active is None


@pytest.fixture
def server():
    state = LiveState(CONFIG, dataset=synthetic_dataset())
    service = LiveServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield service
    finally:
        service.shutdown()
        service.server_close()
        thread.join()


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
    try:
        default = {"Origin": f"http://127.0.0.1:{server.server_port}",
                   "X-Live-Token": server.state.csrf, "Content-Type": "application/json"}
        default.update(headers or {})
        connection.request(method, path, body=body, headers=default)
        response = connection.getresponse()
        return response.status, dict(response.headers), response.read()
    finally:
        connection.close()


def test_http_routes_security_and_actual_compute(server):
    status, headers, body = request(server, "GET", "/health")
    assert status == 200 and json.loads(body)["mode"] == "loopback-only"
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in headers
    assert request(server, "GET", "/../pyproject.toml")[0] == 404
    assert request(server, "GET", "/api/source", headers={"Host": "evil.test"})[0] == 403
    assert request(server, "GET", "/api/source",
                   headers={"Origin": "https://evil.test"})[0] == 403
    assert request(server, "GET", "/api/source",
                   headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(server, "POST", "/api/refresh", "{}",
                   {"X-Live-Token": "wrong"})[0] == 403
    assert request(server, "POST", "/api/refresh", "[]")[0] == 400
    assert request(server, "POST", "/api/refresh", "{")[0] == 400
    assert request(server, "POST", "/api/refresh", "{}",
                   {"Content-Type": "text/plain"})[0] == 415
    assert request(server, "POST", "/api/refresh", " " * 8193)[0] == 413
    assert request(server, "GET", "/api/jobs/missing")[0] == 404
    assert request(server, "POST", "/api/jobs/missing/cancel", "{}")[0] == 404
    source = json.loads(request(server, "GET", "/api/source")[2])
    assert source["records"] == 48
    assert "embeddings" not in source
    args = parameters(server.state, methods=["medoid"], path=["Lepidoptera", "Family A"])
    status, _, body = request(server, "POST", "/api/jobs", json.dumps(args))
    assert status == 202
    job = json.loads(body)
    finished = wait_job(server.state, job)
    assert finished["status"] == "succeeded", finished
    assert request(server, "GET", finished["viewUrl"])[0] == 200
    result = json.loads(request(server, "GET", finished["resultUrl"])[2])
    assert result["records"] == 12 and set(result["trees"]) == {"medoid"}
    status, _, html = request(server, "GET", "/")
    assert status == 200 and b"Run merges" in html
    assert request(server, "GET", "/live.js")[0] == 200


def test_medoid_with_zero_raw_mean_serves_valid_json_and_html(server):
    server.state.data = live.Dataset(
        np.array(["positive", "negative"]), np.array([[1., 0.], [-1., 0.]]),
        np.array([["Order", "Family", "Genus", "Species"]] * 2), {"retained": 2},
    )
    args = parameters(server.state, methods=["medoid"])
    status, _, body = request(server, "POST", "/api/jobs", json.dumps(args))
    assert status == 202
    finished = wait_job(server.state, json.loads(body))
    assert finished["status"] == "succeeded", finished
    status, _, body = request(server, "GET", finished["resultUrl"])
    assert status == 200
    result = json.loads(body)
    summaries = result["trees"]["medoid"]["representatives"]
    assert all(summary["cosineToRawMean"] is None for summary in summaries.values())
    assert all(summary["medoidId"] == "positive" for summary in summaries.values())
    assert len([n for n in result["trees"]["medoid"]["nodes"] if not n["children"]]) == 2
    status, _, html = request(server, "GET", finished["viewUrl"])
    assert status == 200 and b"undefined (raw arithmetic mean is zero)" in html
    json.dumps(result, allow_nan=False)


def test_remote_binding_is_refused_and_cli_dispatch(capsys):
    with pytest.raises(ValueError, match="127.0.0.1"):
        LiveServer(("0.0.0.0", 1234), LiveState(CONFIG))
    with pytest.raises(SystemExit) as caught:
        cli.main(["tree", "live", "--help"])
    assert caught.value.code == 0
    assert "--azure-prefix" in capsys.readouterr().out


def test_oversized_npz_is_rejected_before_loading(monkeypatch):
    monkeypatch.setattr(live, "MAX_UNPACKED", 8)
    contents = io.BytesIO()
    np.savez(contents, large=np.ones(10))
    store = LiveAzureStore(CONFIG["prefix"], CONFIG["subscription"])
    store._token, store.blobs = "synthetic", {}
    with (patch("evospaice.tree.live.urllib.request.build_opener") as opener,
          pytest.raises(ValueError, match="uncompressed")):
        opener.return_value.open.return_value = Response(contents.getvalue())
        store.request("embeddings.npz")
