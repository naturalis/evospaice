Trim records to the primer window, dereplicate within taxon, embed each
record. Outputs vectors + taxonomy. So far, only the first two are
implemented, in `filter_bcdm_bin_representatives.py`: it takes a BOLD BCDM
TSV export and, for a chosen taxon, picks one representative record per BIN
(Barcode Index Number), trimmed to the window between a chosen primer pair.

- `filter_bcdm_bin_representatives.py`
	- Input: BCDM TSV datapackage table from BOLD.
	- Filters to a configurable higher taxon (`--taxon`, default `phylum:Arthropoda`).
	  Any BCDM Linnaean rank works: kingdom, phylum, class, order, family,
	  subfamily, tribe, genus, species, subspecies — e.g. `--taxon order:Lepidoptera`
	  or `--taxon genus:Vanessa`.
	- Keeps one representative per BIN (`bin_uri`).
	- Representative scoring within a BIN (best first): primer coverage tier,
	  then closeness of the window length to the primer set's target length,
	  then fewer ambiguities (fraction, then raw count), then — only if still
	  tied — the longer window wins. What counts as the top coverage tier
	  depends on whether the chosen primer set has a reverse primer:
	  - **Primer set defines both a forward and reverse primer** (`folmer`,
	    `zeale`): a record where *both* primers were found ranks above one
	    where only the forward or only the reverse primer was found — only
	    "both" confirms the fragment's true start and end.
	  - **Primer set is forward-only by design** (`leray`, `elbrecht_bf2`,
	    i.e. `reverse=""`): there is no reverse boundary to look for, so the
	    forward primer cropped to the end of the read *is* the intended
	    window — exactly how `extract_primer_regions.py` handles Leray. A
	    forward match with a plausible length is already top tier.
	  Records with no primer match at all ("none") are always the lowest tier,
	  kept only as a last resort so every BIN still gets a representative —
	  **and for these, the "window" is the entire raw sequence**, so
	  closeness-to-target-length would be meaningless (a coincidental length
	  isn't evidence of the right region). Instead, `none` candidates are
	  tie-broken by **longer wins, then fewer ambiguities** — more sequence is
	  more likely to actually contain the target region even without a clean
	  primer hit.
	- Primer search tries an **exact IUPAC match first**, then falls back to a
	  **mismatch-tolerant search** (`--max-primer-mismatches`, default `2`) so
	  a single sequencing error/SNP in the ~20–30 bp primer site doesn't sink a
	  record straight to `none`. An exact match still outranks a mismatched one
	  within the same coverage tier (`evospaice_primer_mismatches` records how
	  many). Use `--max-primer-mismatches 0` to restore the old exact-only
	  behaviour. On a 100k-row Arthropoda sample, mismatches=2 cut the `none`
	  share from 57% to 7% of representatives, for about +30% runtime.
	- Primer pair is configurable via `--primer-set` (`leray` [default, ~313 bp,
	  forward-only], `folmer` [~658 bp full barcode, both primers], `zeale`
	  [~157 bp bat-diet fragment, both primers], `elbrecht_bf2` [~440 bp,
	  forward-only]). Individual primers/lengths can be overridden with
	  `--forward-primer`, `--reverse-primer`, `--target-length`, `--min-length`,
	  `--max-length` — pass `--reverse-primer ""` to make any primer set
	  forward-only, or supply a reverse primer to require "both" for the top
	  tier.
	- Optional sub-window crop with `--crop-window START:END` (applied on top of
	  the primer window).
	- Optional quality gates, off by default so behaviour is unchanged unless you
	  opt in — unlike primer-window scoring, which only deprioritizes a poor
	  candidate, these **hard-reject** it, so a BIN can end up missing from the
	  output entirely if every one of its records fails the gate (check the
	  report's drop-reason counts):
	  - `--min-sequence-length N` — reject candidates shorter than N bp before
	    any primer scoring (guards against failed/short reads winning a BIN by
	    default when nothing better is available).
	  - `--max-ambiguity-fraction F` — reject candidates whose primer window is
	    more than fraction F non-ACGT bases (e.g. mostly N's).
	- Output format: TSV (default) or FASTA (`--output-format`).
	- Always writes a text report (`--report`, default `<output stem>_report.txt`)
	  with row counts, drop reasons, primer-support breakdown, window length and
	  ambiguity stats, and a top-N breakdown of the next rank down from `--taxon`
	  (e.g. class counts within a phylum filter). Row and breakdown counts also
	  show their percentage (of total rows, of filtered rows, or of BINs).

Output columns (TSV)
--------------------

The TSV output is the input row unchanged, **except**:

- The sequence column (`nuc`) is replaced by the selected primer window (the
  cropped sub-sequence), not the original full read.
- Other BCDM columns still describe the *original* record and are **not**
  recomputed — `nuc_basecount`, `insdc_acs`, `primers_forward`, etc. still refer
  to the untrimmed sequence. Use the `evospaice_*` columns below for the window.

Seven `evospaice_*` columns are appended:

| column | meaning |
| --- | --- |
| `evospaice_primer_set` | Name of the `--primer-set` used for this run (`leray`, `folmer`, `zeale`, `elbrecht_bf2`). Constant for every row of one run. |
| `evospaice_primer_support` | Which primers were *located in this sequence*: `both`, `forward_only`, `reverse_only`, or `none`. **Not** the primer-set name — for a forward-only set like `leray` the best possible value is `forward_only`; `none` means neither primer matched (even with mismatches allowed) and the "window" is the whole untrimmed sequence (last-resort representative). |
| `evospaice_primer_mismatches` | Mismatches in the located primer(s) versus an exact IUPAC match (0 = exact). `0` for `none` (nothing was found to mismatch-count). Governed by `--max-primer-mismatches`. |
| `evospaice_window_start` | 0-based start offset of the window in the cleaned (gap-stripped, upper-cased) original sequence. |
| `evospaice_window_end` | 0-based, exclusive end offset of the window. |
| `evospaice_window_length` | Length in bp of the emitted window (`= end - start`, before any `--crop-window`). This, not `nuc_basecount`, is the trimmed length. |
| `evospaice_ambiguities` | Count of non-ACGT bases in the window. |

Primer matching tries an exact IUPAC match first, then a mismatch-tolerant
fallback (`--max-primer-mismatches`, default `2`) — see "Representative
scoring" above. Even so, on the full BOLD datapackage expect a nonzero `none`
share (a substantial fraction of COI-5P records were uploaded with primers
already trimmed off, so there's nothing left to match). Those rows are kept
untrimmed so every BIN still gets a representative. Tighten with
`--min-sequence-length` / `--max-ambiguity-fraction` if you don't want
low-quality last-resort picks.

Running on the full BOLD datapackage
-------------------------------------

The full datapackage TSV is much larger and messier than a pre-filtered
COI-5P subset — it contains every marker (COI-3P, ITS2, matK, rbcL, 16S, etc.)
and a wide spread of read qualities/lengths. This script already handles the
cleaning that implies: gap-stripping, missing/`N/A` sequence rejection,
column-name synonyms, case-insensitive null handling, and taxon/rank
validation. Two things worth turning on explicitly for a full-datapackage run:

1. Keep `--marker-filter COI-5P` (the default) — essential once other markers
   are mixed in, since `bin_uri` and primer-window scoring only make sense for
   COI-5P records.
2. Add a sequence-quality floor, since the full datapackage includes failed or
   very short reads that a pre-filtered subset wouldn't:
   ```bash
   uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
   	--input data/BOLD_Public.30-Jun-2026.tsv \
   	--output data/arthropoda_bin_representatives.tsv \
   	--min-sequence-length 100 \
   	--max-ambiguity-fraction 0.02
   ```
   Check the report afterwards — `dropped (below_min_sequence_length)` and
   `dropped (too_ambiguous)` tell you how many BINs lost their only candidate
   and are absent from the output, so you can decide whether to relax the
   thresholds.

Examples
--------

```bash
# Default arthropod set, output as TSV
uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
	--input data/BOLD_Public.30-Jun-2026.tsv \
	--output data/arthropoda_bin_representatives.tsv

# Lepidoptera toy set, output as FASTA
uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
	--input data/BOLD_Public.30-Jun-2026.tsv \
	--taxon order:Lepidoptera \
	--output-format fasta \
	--output data/lepidoptera_bin_representatives.fasta

# Optional narrower crop inside the selected primer window
uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
	--input data/BOLD_Public.30-Jun-2026.tsv \
	--output data/arthropoda_windowed.tsv \
	--crop-window 20:280

# Full-length Folmer barcode instead of the Leray mini-barcode
uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
	--input data/BOLD_Public.30-Jun-2026.tsv \
	--primer-set folmer \
	--output data/arthropoda_folmer.tsv

# Filter to a single genus, custom report location
uv run python src/evospaice/ingest/filter_bcdm_bin_representatives.py \
	--input data/BOLD_Public.30-Jun-2026.tsv \
	--taxon genus:Vanessa \
	--output data/vanessa_bin_representatives.tsv \
	--report data/vanessa_report.txt
```
