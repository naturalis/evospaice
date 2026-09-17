import hashlib
import io
import json
from unittest.mock import patch

import numpy as np
import pytest
from Bio import Phylo

from evospaice import cli
from evospaice.tree.centroid import RANKS, Dataset, build_tree
from evospaice.tree.explore import (
    AzureMemoryStore,
    azure_prefix,
    encode_hierarchy,
    generate_payload,
    render_html,
    taxonomy_index,
)
from evospaice.tree.representations import METHODS


def synthetic_dataset():
    rows = [[order, family, genus, species]
            for order in ["Lepidoptera"]
            for family in ["Family A", "Family B", "Family C", "Family D"]
            for genus in ["Shared genus", "Other genus"]
            for species in ["Species A", "Species B", "Species C"]
            for _ in range(2)]
    rng = np.random.default_rng(42)
    return Dataset(
        np.array([f"record-{i:02}" for i in range(len(rows))]),
        rng.uniform(.1, 2, (len(rows), 4)), np.array(rows), {"retained": len(rows)},
    )


@pytest.fixture(scope="module")
def payload():
    return generate_payload(synthetic_dataset(), provenance={"kind": "Synthetic test fixture"})


def test_all_five_complete_trees_and_compact_taxonomy(payload):
    assert set(payload["methods"]) == set(METHODS) == set(payload["trees"])
    assert payload["records"] == 48
    assert payload["counts"] == {"order": 1, "family": 4, "genus": 8, "species": 24}
    taxa = payload["taxa"]
    assert len(taxa) == 1 + 1 + 4 + 8 + 24 + 48
    for method, tree in payload["trees"].items():
        assert len(tree["taxonRoots"]) == len(taxa)
        assert tree["nodes"][0]["taxon"] == 0
        leaves = [n for n in tree["nodes"] if not n["children"]]
        assert {n["label"] for n in leaves} == set(synthetic_dataset().ids)
        assert len(leaves) == 48
        assert all(n["length"] >= 0 for n in tree["nodes"])
        assert all("descendants" not in n for n in tree["nodes"])
        assert payload["methods"][method]["diagnostics"]["skbio_nj_merges"] > 0
        summaries = tree["representatives"]
        assert len(summaries) == len(taxa) - 48
        if method == "centroid":
            assert all(s["cosineToRawMean"] < 1e-14 for s in summaries.values())
        elif method == "medoid":
            assert all(s["medoidId"] in synthetic_dataset().ids for s in summaries.values())
        elif method == "wasserstein":
            assert all(s["covarianceTrace"] >= 0 for s in summaries.values())
        elif method == "frechet":
            assert all(s["norm"] == pytest.approx(1.0) for s in summaries.values())
    for index, taxon in enumerate(taxa):
        if taxon["children"]:
            assert taxon["records"] == sum(taxa[c]["records"] for c in taxon["children"])
        assert all(taxa[c]["parent"] == index for c in taxon["children"])
    # Repeated genus labels under different families have distinct IDs.
    assert sum(t["label"] == "Shared genus" for t in taxa) == 4


def test_generator_and_encoder_do_not_mutate_inputs_or_trees():
    data = synthetic_dataset()
    vectors, taxonomy, ids = data.embeddings.copy(), data.taxonomy.copy(), data.ids.copy()
    generate_payload(data)
    np.testing.assert_array_equal(data.embeddings, vectors)
    np.testing.assert_array_equal(data.taxonomy, taxonomy)
    np.testing.assert_array_equal(data.ids, ids)
    tree, _ = build_tree(data, nj_backend="skbio")
    before, after = io.StringIO(), io.StringIO()
    Phylo.write(tree, before, "newick")
    _, paths = taxonomy_index(data)
    encode_hierarchy(tree, paths)
    Phylo.write(tree, after, "newick")
    assert before.getvalue() == after.getvalue()


def test_html_is_self_contained_and_safely_escapes_labels(payload):
    dangerous = "</script><img src=x onerror=alert(1)>&\u2028"
    content = render_html({**payload, "provenance": {"unsafe": dangerous}})
    assert dangerous not in content
    assert "\\u003c/script\\u003e" in content
    encoded = content.split('<script id="explorer-data" type="application/json">')[1]
    decoded = json.loads(encoded.split("</script>")[0])
    assert decoded["provenance"]["unsafe"] == dangerous
    assert "/* EXPLORER_DATA */" not in content
    assert "<script src=" not in content
    assert "fetch(" not in content
    assert ".innerHTML" not in content


@pytest.mark.parametrize("url", [
    "http://account.blob.core.windows.net/container/subset/",
    "https://account.blob.core.windows.net/container/subset/?sig=secret",
    "https://account.blob.core.windows.net.evil.test/container/subset/",
    "https://user:pass@account.blob.core.windows.net/container/subset/",
    "https://account.blob.core.windows.net/container/",
])
def test_azure_prefix_rejects_unsafe_sources(url):
    with pytest.raises(ValueError):
        azure_prefix(url)


def azure_fixture():
    data = synthetic_dataset()
    buffer = io.BytesIO()
    np.savez(buffer, ids=data.ids, embeddings=data.embeddings,
             **{rank: data.taxonomy[:, i] for i, rank in enumerate(RANKS)})
    table = "id\t" + "\t".join(RANKS) + "\n"
    table += "".join("\t".join([identifier, *row]) + "\n"
                     for identifier, row in zip(data.ids, data.taxonomy, strict=True))
    blobs = {"embeddings.npz": buffer.getvalue(), "selected-records.tsv": table.encode()}
    manifest = {"artifacts": {name: {"sha256": hashlib.sha256(content).hexdigest(),
                                    "bytes": len(content)}
                              for name, content in blobs.items()}}
    blobs["manifest.json"] = json.dumps(manifest).encode()
    return blobs


def test_azure_load_verifies_full_cohort_and_manifest_without_disk():
    store = AzureMemoryStore("https://example.blob.core.windows.net/container/subset", "sub")
    blobs = azure_fixture()
    with patch.object(store, "request", side_effect=lambda name: blobs[name]):
        data, provenance = store.load(48)
        assert len(data.ids) == 48
        assert "metadataVerified" in provenance
        with pytest.raises(ValueError, match="Expected 5000"):
            store.load(5000)
        blobs["embeddings.npz"] += b"corrupt"
        with pytest.raises(ValueError, match="checksum"):
            store.load()


def test_azure_publish_uses_unique_names_and_get_verification():
    store = AzureMemoryStore("https://example.blob.core.windows.net/container/subset/", "sub")
    blobs = {}

    def request(name, data=None):
        if data is not None:
            assert name not in blobs
            assert name.startswith("merging-explorer-") and name.endswith(".html")
            blobs[name] = data
            return b""
        return blobs[name]

    with patch.object(store, "request", side_effect=request):
        first, second = store.publish("<html>one</html>"), store.publish("<html>one</html>")
        assert first["url"] != second["url"]
        assert first["sha256"] == hashlib.sha256(b"<html>one</html>").hexdigest()
    with patch.object(store, "request", return_value=b"corrupt"):
        with pytest.raises(ValueError, match="SHA-256"):
            store.publish("<html>one</html>")


def test_azure_request_uses_immutable_block_blob_headers_and_rejects_redirects():
    store = AzureMemoryStore("https://example.blob.core.windows.net/container/subset/", "sub")
    seen = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b""

    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert timeout == 600
            return Response()

    with (patch("evospaice.tree.explore.subprocess.check_output",
                return_value=b'{"accessToken":"synthetic-test-token"}') as token,
          patch("evospaice.tree.explore.urllib.request.build_opener",
                return_value=Opener()) as opener):
        store.request("unique.html", b"<html></html>")
        token.assert_called_once()
        request = seen[0]
        assert request.method == "PUT"
        assert request.get_header("If-none-match") == "*"
        assert request.get_header("X-ms-blob-type") == "BlockBlob"
        assert request.get_header("X-ms-version") == "2023-11-03"
        redirect_handler = opener.call_args.args[0]()
        assert redirect_handler.redirect_request(None, None, 302, "", {}, "https://elsewhere") \
            is None
    with pytest.raises(ValueError, match="safe filename"):
        store.request("../embeddings.npz", b"forbidden")


def test_azure_metadata_must_agree_even_with_valid_file_checksums():
    store = AzureMemoryStore("https://example.blob.core.windows.net/container/subset/", "sub")
    blobs = azure_fixture()
    blobs["selected-records.tsv"] = blobs["selected-records.tsv"].replace(
        b"record-00", b"record-XX",
    )
    manifest = json.loads(blobs["manifest.json"])
    manifest["artifacts"]["selected-records.tsv"]["sha256"] = hashlib.sha256(
        blobs["selected-records.tsv"],
    ).hexdigest()
    blobs["manifest.json"] = json.dumps(manifest).encode()
    with patch.object(store, "request", side_effect=lambda name: blobs[name]):
        with pytest.raises(ValueError, match="Metadata IDs/taxonomy"):
            store.load()


def test_explore_cli_dispatch(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["tree", "explore", "--help"])
    assert caught.value.code == 0
    assert "--publish" in capsys.readouterr().out


def test_stdout_cli_in_memory(capsys, payload):
    with (patch("evospaice.tree.explore.AzureMemoryStore.load",
                return_value=(synthetic_dataset(), {})),
          patch("evospaice.tree.explore.generate_payload", return_value=payload)):
        assert cli.main(["tree", "explore", "--azure-prefix",
                         "https://example.blob.core.windows.net/container/subset/",
                         "--subscription", "example"]) == 0
    assert capsys.readouterr().out.startswith("<!doctype html>")
