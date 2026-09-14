from __future__ import annotations

import pytest

from services.class_filter.filtering import FastaFormatError, FilterStats, filter_fasta_by_class
from services.class_filter.trigger import TriggerRequest


def test_trigger_selects_class_and_derives_output_blob() -> None:
    request = TriggerRequest.from_json(
        b'{"source_blob_url":"https://example.blob.core.windows.net/input/source.fasta",'
        b'"target_class":"Aves"}'
    )

    assert request.target_class == "Aves"
    assert request.output_blob_name == "aves.fasta"


@pytest.mark.parametrize("missing_field", ["source_blob_url", "target_class"])
def test_trigger_requires_all_fields(missing_field: str) -> None:
    data = {
        "source_blob_url": "https://example.blob.core.windows.net/input/source.fasta",
        "target_class": "Insecta",
    }
    del data[missing_field]

    with pytest.raises(ValueError, match=missing_field):
        TriggerRequest.from_json(__import__("json").dumps(data).encode())


@pytest.mark.parametrize("target_class", ["../Insecta", "Insecta/Aves", "Insecta Aves"])
def test_trigger_rejects_class_names_that_cannot_form_a_blob_name(target_class: str) -> None:
    payload = (
        '{"source_blob_url":"https://example.blob.core.windows.net/input/source.fasta",'
        f'"target_class":"{target_class}"}}'
    )

    with pytest.raises(ValueError, match="target_class"):
        TriggerRequest.from_json(payload.encode())


def test_filters_records_by_class_without_loading_the_whole_file() -> None:
    chunks = [
        b">one|class=In",
        b"secta|order=Lepidoptera\nAC",
        b"GT\nTGCA\n>two;class:Aves\nGGGG\n",
        b">three class=insecta\nCCCC",
    ]
    stats = FilterStats()

    output = b"".join(filter_fasta_by_class(chunks, "Insecta", stats=stats))

    assert output == (
        b">one|class=Insecta|order=Lepidoptera\nACGT\nTGCA\n"
        b">three class=insecta\nCCCC"
    )
    assert stats.records_seen == 3
    assert stats.records_written == 2


def test_skips_records_without_class_metadata() -> None:
    fasta = b">one species=Example\nACGT\n>two class=Insecta\nTGCA\n"

    assert b"".join(filter_fasta_by_class([fasta], "Insecta")) == b">two class=Insecta\nTGCA\n"


def test_target_class_is_configurable() -> None:
    fasta = b">one class=Insecta\nACGT\n>two class=Aves\nTGCA\n"

    assert b"".join(filter_fasta_by_class([fasta], "Aves")) == b">two class=Aves\nTGCA\n"


def test_filters_bold_rank_prefixed_class() -> None:
    fasta = (
        b">BOLD|record-1|COI-5P k__Animalia;p__Arthropoda;c__Insecta;o__Lepidoptera\n"
        b"ACGT\n"
        b">BOLD|record-2|COI-5P k__Animalia;p__Chordata;c__Aves;o__Passeriformes\n"
        b"TGCA\n"
    )

    assert b"".join(filter_fasta_by_class([fasta], "Insecta")) == (
        b">BOLD|record-1|COI-5P k__Animalia;p__Arthropoda;c__Insecta;o__Lepidoptera\n"
        b"ACGT\n"
    )


def test_rejects_sequence_data_before_first_header() -> None:
    with pytest.raises(FastaFormatError, match="before the first FASTA header"):
        b"".join(filter_fasta_by_class([b"ACGT\n>one class=Insecta\nACGT\n"], "Insecta"))