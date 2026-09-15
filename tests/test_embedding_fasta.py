from services.embedding_submitter.worker.fasta import iter_fasta_records
from services.embedding_submitter.job_request import EmbeddingJobRequest


def test_embedding_job_request_is_deterministic_and_versioned() -> None:
        payload = b'''{
            "data": {
                "url": "https://account.blob.core.windows.net/filtered-sequences/insecta.fasta",
                "eTag": "\\"0xABC123\\""
            }
        }'''

        first = EmbeddingJobRequest.from_event(
                payload,
                expected_host="account.blob.core.windows.net",
                expected_container="filtered-sequences",
        )
        second = EmbeddingJobRequest.from_event(
                payload,
                expected_host="account.blob.core.windows.net",
                expected_container="filtered-sequences",
        )

        assert first == second
        assert first.job_name.startswith("embed-insecta-")
        assert first.output_prefix == "insecta/0xabc123"


def test_streams_records_and_preserves_bold_metadata() -> None:
    chunks = [
        b">BOLD|ABC-1|COI-5P k__Animalia;p__Arthropoda;c__In",
        b"secta;o__Lepidoptera;f__None;g__Danaus;s__Danaus plexippus\nAC",
        b"GT\nTGCA\n>plain-record class=Insecta\nAAAA\n",
    ]

    records = list(iter_fasta_records(chunks))

    assert len(records) == 2
    assert records[0].ordinal == 0
    assert records[0].record_id == "ABC-1"
    assert records[0].sequence == "ACGTTGCA"
    assert records[0].taxonomy == {
        "kingdom": "Animalia",
        "phylum": "Arthropoda",
        "class": "Insecta",
        "order": "Lepidoptera",
        "family": None,
        "genus": "Danaus",
        "species": "Danaus plexippus",
    }
    assert records[1].ordinal == 1
    assert records[1].record_id == "plain-record"


def test_rejects_sequence_before_header() -> None:
    try:
        list(iter_fasta_records([b"ACGT\n>record\nTGCA\n"]))
    except ValueError as error:
        assert "before the first FASTA header" in str(error)
    else:
        raise AssertionError("malformed FASTA was accepted")