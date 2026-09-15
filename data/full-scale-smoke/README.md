# Representative full-scale smoke data

This deterministic fixture exercises the complete local equivalent of the
full-scale cloud workflow: Parquet and FAISS input, BIN selection, taxonomy
partition planning, queued workers, subtree grafting, and final validation.

The source contains 13 embedded-record identities and 12 distinct BINs. The
second `BOLD:SMOKE-DAN-1` record verifies deterministic one-record-per-BIN
selection. FAISS IDs deliberately interleave genera within `Nymphalidae` so a
record-count chunker would split those genera. `BOLD:SMOKE-PIE-1` is classified
only to `Pieridae`, exercising direct attachment to a partition root.

The smoke test uses a three-record partition limit. Expected partitions are:

| Taxonomy attachment | Leaves |
| --- | ---: |
| `Muscidae` | 3 |
| `Danaini` | 3 |
| `Junonia` | 2 |
| `Vanessa` | 3 |
| `Pieridae` | 1 |

Vectors are deterministic, normalized, taxonomy-shaped synthetic vectors with
the production dimension of 256. The test writes them to a real
`IndexIDMap2(IndexFlatIP)` FAISS index and writes metadata and the BIN mapping
as Parquet before invoking production tree code. They validate technical data
flow and tree assembly, not biological accuracy.

Run the local smoke test from the repository root:

```bash
uv run pytest -q tests/test_tree_full_scale_smoke.py
```