Trim records to the primer window, dereplicate within taxon, embed each record. Outputs vectors + taxonomy.

Scripts
-------

- `filter_bcdm_bin_representatives.py`
	- Input: BCDM TSV datapackage table from BOLD.
	- Filters to a configurable higher taxon (`--taxon`, default `phylum:Arthropoda`).
	  Any BCDM Linnaean rank works: kingdom, phylum, class, order, family,
	  subfamily, tribe, genus, species, subspecies — e.g. `--taxon order:Lepidoptera`
	  or `--taxon genus:Vanessa`.
	- Keeps one representative per BIN (`bin_uri`).
	- Representative scoring (best first): primer coverage tier, then closeness
	  to the target length, then fewer ambiguities. What counts as the top
	  coverage tier depends on whether the chosen primer set has a reverse
	  primer:
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
	  kept only as a last resort so every BIN still gets a representative.
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
	- Output format: TSV (default) or FASTA (`--output-format`).
	- Always writes a text report (`--report`, default `<output stem>_report.txt`)
	  with row counts, drop reasons, primer-support breakdown, window length and
	  ambiguity stats, and a top-N breakdown of the next rank down from `--taxon`
	  (e.g. class counts within a phylum filter).

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
