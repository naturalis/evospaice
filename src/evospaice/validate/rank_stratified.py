"""Rank-stratified comparison of distances against an independent reference tree.

For the tip pairs sampled by ``patristic_vs_seqdist.py`` this script adds:

* the patristic distance between the same two tips on a reference tree
  (default: the Bactria Lepidoptera tree, ``data/pruned.tre.txt``);
* an alignment-free k-mer (Mash-style) distance computed from the sequences in
  the pair FASTA, as a model-free baseline;
* the taxonomic rank at which the two tips diverge (same species, same genus,
  same family, different family), looked up in the BOLD taxonomy scaffold.

It then reports, per divergence class, how well each distance (K2P sequence
distance, k-mer distance, and the patristic distance on the embedding tree)
tracks the reference patristic distance, and draws a three-panel figure.

Usage (from the repository root)::

    python -m evospaice.validate.rank_stratified \
        --pairs src/evospaice/validate/strat_validate_results/pairs_strat.tsv \
        --fasta src/evospaice/validate/strat_validate_results/pairs_strat.fasta \
        --reference data/pruned.tre.txt \
        --taxonomy data/pruned.taxonomy.tsv \
        --scaffold data/BOLD_Public.30-Jun-2026.tre.gz \
        --out src/evospaice/validate/strat_validate_results/rank_stratified

No third-party dependencies beyond numpy, scipy and matplotlib.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr, spearmanr

CLASSES = ["same species", "same genus", "same family", "different family"]


# ---------------------------------------------------------------------------
# Minimal streaming Newick parser (quoted labels, [&...] comments, lengths)
# ---------------------------------------------------------------------------

def parse_newick(text: str):
    """Return (parent, label, length) lists; node 0 is the root."""
    parent, label, length = [-1], [None], [0.0]
    cur, i, n = 0, 0, len(text)
    stack = []

    def read_label(i):
        if i < n and text[i] == "'":
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            return "".join(buf), j + 1
        j = i
        while j < n and text[j] not in "(),:;[":
            j += 1
        return text[i:j].strip() or None, j

    def skip_comment(i):
        while i < n and text[i] == "[":
            i = text.index("]", i) + 1
        return i

    while i < n:
        c = text[i]
        if c == "(":
            parent.append(cur)
            label.append(None)
            length.append(0.0)
            stack.append(cur)
            cur = len(parent) - 1
            i += 1
        elif c == ",":
            p = stack[-1]
            parent.append(p)
            label.append(None)
            length.append(0.0)
            cur = len(parent) - 1
            i += 1
        elif c == ")":
            cur = stack.pop()
            i += 1
        elif c == ";":
            break
        elif c.isspace():
            i += 1
        else:
            lab, i = read_label(i)
            if lab is not None:
                label[cur] = lab
            i = skip_comment(i)
            if i < n and text[i] == ":":
                j = i + 1
                while j < n and text[j] not in "(),;[":
                    j += 1
                length[cur] = float(text[i + 1:j])
                i = skip_comment(j)
    return parent, label, length


def read_text(path: Path) -> str:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Reference tree patristic distances
# ---------------------------------------------------------------------------

class PatristicTree:
    def __init__(self, path: Path):
        parent, label, length = parse_newick(read_text(path))
        self.parent = parent
        self.depth = [0] * len(parent)
        self.dist = [0.0] * len(parent)
        for v in range(1, len(parent)):  # parents are created before children
            p = parent[v]
            self.depth[v] = self.depth[p] + 1
            self.dist[v] = self.dist[p] + length[v]
        self.tip = {lab: v for v, lab in enumerate(label) if lab is not None}

    def patristic(self, a: str, b: str):
        if a not in self.tip or b not in self.tip:
            return None
        u, v = self.tip[a], self.tip[b]
        x, y = u, v
        while self.depth[x] > self.depth[y]:
            x = self.parent[x]
        while self.depth[y] > self.depth[x]:
            y = self.parent[y]
        while x != y:
            x, y = self.parent[x], self.parent[y]
        return self.dist[u] + self.dist[v] - 2 * self.dist[x]


# ---------------------------------------------------------------------------
# Taxonomy: species name -> genus / family from the BOLD scaffold
# ---------------------------------------------------------------------------

def species_lineages(scaffold: Path) -> dict[str, dict[str, str]]:
    parent, label, _ = parse_newick(read_text(scaffold))
    out = {}
    for v, lab in enumerate(label):
        if not lab or not lab.startswith("species:"):
            continue
        lineage = {}
        p = parent[v]
        while p >= 0:
            pl = label[p]
            if pl and ":" in pl:
                rank, name = pl.split(":", 1)
                lineage.setdefault(rank, name)
            p = parent[p]
        out[lab.split(":", 1)[1]] = lineage
    return out


def divergence_class(sp_a, sp_b, lineages):
    if not sp_a or not sp_b:
        return None
    if sp_a == sp_b:
        return "same species"
    la, lb = lineages.get(sp_a, {}), lineages.get(sp_b, {})
    ga = la.get("genus", sp_a.split()[0])
    gb = lb.get("genus", sp_b.split()[0])
    if ga == gb:
        return "same genus"
    fa, fb = la.get("family"), lb.get("family")
    if fa is None or fb is None:
        return None
    return "same family" if fa == fb else "different family"


# ---------------------------------------------------------------------------
# k-mer (Mash-style) distance
# ---------------------------------------------------------------------------

def read_fasta(path: Path) -> dict[str, str]:
    seqs, name, buf = {}, None, []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if name:
                    seqs[name] = "".join(buf)
                name, buf = line[1:].split()[0], []
            elif line:
                buf.append(line.upper())
    if name:
        seqs[name] = "".join(buf)
    return seqs


def kmers(seq: str, k: int) -> set[str]:
    seq = seq.replace("-", "").replace(".", "")
    return {seq[i:i + k] for i in range(len(seq) - k + 1) if set(seq[i:i + k]) <= set("ACGT")}


def mash_distance(a: set[str], b: set[str], k: int) -> float:
    if not a or not b:
        return float("nan")
    j = len(a & b) / len(a | b)
    if j == 0:
        return 1.0
    return min(1.0, -1.0 / k * math.log(2 * j / (1 + j)))


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--fasta", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--taxonomy", type=Path, required=True,
                    help="TSV mapping tip label (node) to species")
    ap.add_argument("--scaffold", type=Path, required=True,
                    help="BOLD taxonomy scaffold Newick (rank:name internal labels)")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--out", type=Path, required=True, help="output prefix")
    args = ap.parse_args(argv)

    ref = PatristicTree(args.reference)
    with open(args.taxonomy) as fh:
        species = {r["node"]: r["species"] for r in csv.DictReader(fh, delimiter="\t")}
    lineages = species_lineages(args.scaffold)
    seqs = read_fasta(args.fasta)
    kcache = {name: kmers(s, args.k) for name, s in seqs.items()}

    rows = []
    with open(args.pairs) as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            a, b = r["source"], r["target"]
            cls = divergence_class(species.get(a), species.get(b), lineages)
            kd = mash_distance(kcache.get(a, set()), kcache.get(b, set()), args.k)
            rows.append({
                "source": a, "target": b,
                "embedding_tree_patristic": float(r["patristic_distance"]),
                "k2p": float(r["sequence_distance"]),
                "kmer_mash": kd,
                "reference_patristic": ref.patristic(a, b),
                "divergence": cls or "",
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tsv = args.out.with_suffix(".tsv")
    with open(tsv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})

    usable = [r for r in rows if r["reference_patristic"] is not None and r["divergence"]]
    metrics = ["k2p", "kmer_mash", "embedding_tree_patristic"]
    lines = [f"pairs: {len(rows)}; with reference distance and divergence class: {len(usable)}", ""]
    header = f"{'class':<18}{'n':>5}" + "".join(f"{m + ' rho':>30}" for m in metrics)
    lines.append(header)
    groups = defaultdict(list)
    for r in usable:
        groups[r["divergence"]].append(r)
    groups["all"] = usable
    summary = []
    for cls in CLASSES + ["all"]:
        g = groups.get(cls, [])
        cells = []
        rec = {"class": cls, "n": len(g)}
        for m in metrics:
            x = np.array([r["reference_patristic"] for r in g])
            y = np.array([r[m] for r in g])
            ok = ~np.isnan(y)
            if ok.sum() >= 5:
                rho, p = spearmanr(x[ok], y[ok])
                cells.append(f"{rho:>22.3f} (p={p:.1g})")
                rec[m + "_spearman"] = round(float(rho), 3)
                rec[m + "_p"] = float(p)
            else:
                cells.append(f"{'n/a':>30}")
        summary.append(rec)
        lines.append(f"{cls:<18}{len(g):>5}" + "".join(f"{c:>30}" for c in cells))
    lines.append("")
    lines.append(f"{'median':<18}" + "".join(f"{m:>26}" for m in ["reference_patristic"] + metrics))
    for cls in CLASSES:
        g = groups.get(cls, [])
        if not g:
            continue
        meds = [np.nanmedian([r[m] for r in g]) for m in ["reference_patristic"] + metrics]
        lines.append(f"{cls:<18}" + "".join(f"{v:>26.3f}" for v in meds))
    x = np.array([r["reference_patristic"] for r in usable])
    y = np.array([r["embedding_tree_patristic"] for r in usable])
    lines.append("")
    lines.append(f"Pearson (reference vs embedding-tree patristic, all): {pearsonr(x, y)[0]:.3f}")
    report = "\n".join(lines)
    args.out.with_suffix(".txt").write_text(report + "\n")
    print(report)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {"same species": "#1b9e77", "same genus": "#7570b3",
               "same family": "#d95f02", "different family": "#e7298a"}
    titles = {"k2p": "K2P sequence distance",
              "kmer_mash": f"k-mer (Mash, k={args.k}) distance",
              "embedding_tree_patristic": "Patristic distance, embedding tree"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), constrained_layout=True)
    for ax, m, tag in zip(axes, metrics, "ABC"):
        for cls in CLASSES:
            g = groups.get(cls, [])
            ax.scatter([r["reference_patristic"] for r in g], [r[m] for r in g],
                       s=12, alpha=0.7, color=colours[cls], label=f"{cls} (n={len(g)})")
        ax.set_xlabel("Patristic distance, reference tree")
        ax.set_ylabel(titles[m])
        ax.set_title(tag, loc="left", fontweight="bold")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, frameon=False)
    fig.savefig(args.out.with_suffix(".png"), dpi=200)
    fig.savefig(args.out.with_suffix(".svg"))


if __name__ == "__main__":
    main()
