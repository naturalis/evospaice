# Manuscript build instructions

This folder contains a preprint-style manuscript in Pandoc Markdown format.

## Files

- `manuscript.md` — main manuscript text
- `references.bib` — BibTeX database used by Pandoc citeproc
- `pipeline-overview.svg` — high-level pipeline figure referenced in the manuscript

## Build to PDF with Pandoc

From the repository root:

```bash
pandoc docs/manuscript/manuscript.md \
  --resource-path=docs/manuscript \
  --citeproc \
  --bibliography docs/manuscript/references.bib \
  --pdf-engine=xelatex \
  -o docs/manuscript/manuscript.pdf
```

If `xelatex` is not available, replace `--pdf-engine=xelatex` with another installed engine (for example `pdflatex`).

