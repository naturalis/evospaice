from services.species_splitter.job_request import SpeciesSplitRequest
from services.species_splitter.worker.species import shard_for_key, species_key


def test_unknown_species_share_the_unknown_files() -> None:
    for value in (None, "", "None", "unknown", "unidentified", "unclassified"):
        assert species_key(value) == "unknown"


def test_species_keys_are_stable_safe_and_collision_resistant() -> None:
    first = species_key("Danaus plexippus")
    second = species_key("Danaus-plexippus")

    assert first.startswith("danaus-plexippus-")
    assert first == species_key("Danaus plexippus")
    assert first != second
    assert "/" not in first and " " not in first


def test_species_is_assigned_to_exactly_one_stable_shard() -> None:
    key = species_key("Danaus plexippus")

    assert shard_for_key(key, 8) == shard_for_key(key, 8)
    assert 0 <= shard_for_key(key, 8) < 8
    assert shard_for_key("unknown", 8) == shard_for_key(species_key(None), 8)


def test_split_request_targets_embedding_bundle_parent() -> None:
    payload = b'''{
      "data": {
        "url": "https://account.blob.core.windows.net/embedding-results/insecta/etag/index.faiss",
        "eTag": "\\"0xABC123\\""
      }
    }'''

    request = SpeciesSplitRequest.from_event(
        payload,
        expected_host="account.blob.core.windows.net",
        expected_container="embedding-results",
    )

    assert request.bundle_prefix == "insecta/etag"
    assert request.job_prefix.startswith("split-species-")