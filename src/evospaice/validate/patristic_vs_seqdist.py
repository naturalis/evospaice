#!/usr/bin/env python3
"""
patristic_vs_seqdist.py

Compare patristic distances on a tree with pairwise sequence distances for
randomly sampled tip pairs.

Steps:
  1. Read a Newick tree (FigTree/BEAST [&key=value] comments are tolerated).
  2. Randomly sample n distinct unordered pairs of tips, either uniformly or
     (--stratify) in equal numbers per LCA level, so that shallow pairs are
     represented rather than swamped by deep ones.
  3. Compute the patristic distance for each pair (root-depth arithmetic with
     an LCA walk, so no all-pairs matrix is ever built).
  4. Stream a BOLD BCDM TSV (.tar.gz, .tsv.gz or plain .tsv) and extract the
     sequences whose label column (default: processid) matches a sampled tip.
  5. Write those sequences as FASTA and align them to a profile HMM with
     hmmalign (HMMER 3). Only HMM match-state columns are retained, so all
     sequences share one coordinate system and insert residues, which are not
     homologous across sequences, are ignored.
  6. Compute pairwise sequence distances (pairwise deletion over sites where
     both sequences have an unambiguous base) for the same pairs.
  7. Write a TSV: source, target, patristic_distance, sequence_distance,
     plus the number of compared sites and the level (edges from the root)
     of the pair's last common ancestor.

Requirements: Python 3.8+, biopython, numpy, HMMER (hmmalign on PATH).
Optional: pigz, for faster decompression of large BCDM archives.
"""

import argparse
import csv
import io
import logging
import math
import os
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile

import numpy as np
from Bio import Phylo, SeqIO

log = logging.getLogger("patristic_vs_seqdist")

IUPAC_DNA = set("ACGTRYSWKMBDHVN")


# --------------------------------------------------------------------------
# Tree handling
# --------------------------------------------------------------------------

class FlatTree:
    """Minimal array representation of a rooted tree: parent index, depth
    from the root (sum of branch lengths) and level (number of edges from
    the root). Built once, after which the Biopython object can be freed."""

    def __init__(self, tree):
        self.parent = []
        self.depth = []
        self.level = []
        self.tip_index = {}
        duplicates = 0

        # Iterative pre-order traversal; avoids recursion limits on deep trees
        stack = [(tree.root, -1)]
        while stack:
            clade, par = stack.pop()
            idx = len(self.parent)
            bl = clade.branch_length or 0.0
            if par < 0:
                d, lv = 0.0, 0  # ignore any root branch length
            else:
                d, lv = self.depth[par] + bl, self.level[par] + 1
            self.parent.append(par)
            self.depth.append(d)
            self.level.append(lv)
            if clade.clades:
                for child in reversed(clade.clades):
                    stack.append((child, idx))
            else:
                name = clade.name
                if name is None:
                    log.debug("Unlabelled tip at node %d ignored", idx)
                    continue
                if name in self.tip_index:
                    duplicates += 1
                    continue
                self.tip_index[name] = idx
        if duplicates:
            log.warning("%d duplicate tip labels ignored (first occurrence kept)", duplicates)
        self.tips = list(self.tip_index)

    def lca(self, a, b):
        par, lev = self.parent, self.level
        while lev[a] > lev[b]:
            a = par[a]
        while lev[b] > lev[a]:
            b = par[b]
        while a != b:
            a, b = par[a], par[b]
        return a

    def patristic(self, name_a, name_b):
        """Return (patristic distance, level of the LCA)."""
        a, b = self.tip_index[name_a], self.tip_index[name_b]
        c = self.lca(a, b)
        return self.depth[a] + self.depth[b] - 2.0 * self.depth[c], self.level[c]

    # -- stratified sampling support --------------------------------------
    #
    # Node indices are assigned in pre-order, so the subtree of node i is the
    # contiguous index range [i, i + size[i]), its first child is i + 1 and
    # each next sibling follows the previous child's subtree. Labelled tips
    # are also stored in pre-order, so the tips below node i are the slice
    # tips[tipcum[i]:tipcum[i + size[i]]]. No child lists are needed.

    def prepare_strata(self):
        n = len(self.parent)
        size = [1] * n
        for i in range(n - 1, 0, -1):
            size[self.parent[i]] += size[i]
        is_tip = bytearray(n)
        for idx in self.tip_index.values():
            is_tip[idx] = 1
        tipcum = [0] * (n + 1)
        run = 0
        for i in range(n):
            tipcum[i] = run
            run += is_tip[i]
        tipcum[n] = run
        self._size, self._tipcum = size, tipcum
        self._kids = {}

        by_level = {}
        for i in range(n):
            if size[i] > 1 and self._count_tip_children(i) >= 2:
                by_level.setdefault(self.level[i], []).append(i)
        return by_level

    def _iter_tip_children(self, i):
        """Yield (lo, hi) tip ranges of the children of i holding labelled tips."""
        size, tipcum = self._size, self._tipcum
        c, end = i + 1, i + size[i]
        while c < end:
            lo, hi = tipcum[c], tipcum[c + size[c]]
            if hi > lo:
                yield lo, hi
            c += size[c]

    def _count_tip_children(self, i):
        count = 0
        for _ in self._iter_tip_children(i):
            count += 1
            if count == 2:
                break
        return count

    def _tip_children(self, i):
        """Cached child tip ranges; only nodes actually drawn are cached."""
        kids = self._kids.get(i)
        if kids is None:
            kids = self._kids[i] = list(self._iter_tip_children(i))
        return kids

    def draw_pair_at(self, node, rng):
        """Draw a tip pair whose LCA is exactly `node`: two different
        children, then one random tip below each."""
        (alo, ahi), (blo, bhi) = rng.sample(self._tip_children(node), 2)
        a = self.tips[rng.randrange(alo, ahi)]
        b = self.tips[rng.randrange(blo, bhi)]
        return (a, b) if a < b else (b, a)


def read_tree(path):
    log.info("Reading tree %s", path)
    tree = Phylo.read(path, "newick")
    flat = FlatTree(tree)
    del tree
    log.info("Tree has %d labelled tips and %d nodes", len(flat.tips), len(flat.parent))
    return flat


def sample_pairs(tips, n, rng):
    """Sample up to n distinct unordered pairs of distinct tips, uniformly."""
    k = len(tips)
    if k < 2:
        sys.exit("Tree has fewer than two labelled tips")
    max_pairs = k * (k - 1) // 2
    if n > max_pairs:
        log.warning("Requested %d pairs but only %d exist; using all", n, max_pairs)
        n = max_pairs
    if n > max_pairs // 2:
        # Dense case (small trees): enumerate and sample
        allpairs = [(i, j) for i in range(k) for j in range(i + 1, k)]
        chosen = rng.sample(allpairs, n)
    else:
        # Sparse case (large trees): rejection sampling
        seen = set()
        while len(seen) < n:
            i, j = rng.randrange(k), rng.randrange(k)
            if i == j:
                continue
            seen.add((i, j) if i < j else (j, i))
        chosen = list(seen)
        rng.shuffle(chosen)
    return [(tips[i], tips[j]) for i, j in chosen]


def sample_pairs_stratified(tree, n, rng, max_tries=50):
    """Sample up to n distinct pairs, spread evenly over LCA levels.

    Within a level, a node is drawn uniformly from the nodes at that level
    with at least two tip-bearing children, and a pair is drawn across two
    of its children, so the pair's LCA is that node. Levels that run out of
    distinct pairs hand their remaining quota to the other levels."""
    strata = tree.prepare_strata()
    if not strata:
        sys.exit("No internal node has two tip-bearing children")
    levels = sorted(strata)
    log.info("Stratifying over %d LCA levels (%d to %d)", len(levels), levels[0], levels[-1])
    seen = set()
    per_level = dict.fromkeys(levels, 0)
    active = list(levels)
    while len(seen) < n and active:
        quota = max(1, math.ceil((n - len(seen)) / len(active)))
        still_active = []
        for lv in active:
            nodes = strata[lv]
            added = tries = 0
            while added < quota and tries < quota * max_tries and len(seen) < n:
                tries += 1
                pair = tree.draw_pair_at(rng.choice(nodes), rng)
                if pair not in seen:
                    seen.add(pair)
                    added += 1
            per_level[lv] += added
            if added == quota:
                still_active.append(lv)
        active = still_active
    if len(seen) < n:
        log.warning("Only %d distinct stratified pairs found (requested %d)", len(seen), n)
    for lv in levels:
        log.debug("  level %d: %d nodes, %d pairs", lv, len(strata[lv]), per_level[lv])
    log.info("Pairs per level: %s", ", ".join(f"{lv}:{per_level[lv]}" for lv in levels))
    pairs = list(seen)
    pairs.sort()  # set order is not reproducible across runs; sort then shuffle
    rng.shuffle(pairs)
    return pairs


# --------------------------------------------------------------------------
# BCDM streaming
# --------------------------------------------------------------------------

class _ProcStream:
    """Wraps a subprocess pipe so it can be closed early and cleaned up."""

    def __init__(self, cmd):
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.text = io.TextIOWrapper(self.proc.stdout, encoding="utf-8",
                                     errors="replace", newline="")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait()


class _Unseekable(io.RawIOBase):
    """Adapter for tarfile stream-mode members, whose file objects do not
    implement seekable() and so cannot be wrapped by TextIOWrapper directly."""

    def __init__(self, fh):
        self._fh = fh

    def readable(self):
        return True

    def readinto(self, buf):
        data = self._fh.read(len(buf))
        buf[:len(data)] = data
        return len(data)


def open_bcdm(path):
    """Return (text_stream, closer) for a BCDM TSV in .tar.gz, .tsv.gz or .tsv form."""
    lower = path.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        tar_bin, pigz = shutil.which("tar"), shutil.which("pigz")
        if tar_bin and pigz:
            # GNU tar with pigz is considerably faster than Python's gzip on
            # a multi-GB archive. Only members ending in .tsv are emitted.
            log.info("Streaming %s with tar + pigz", path)
            ps = _ProcStream([tar_bin, "-I", pigz, "-xOf", path, "--wildcards", "*.tsv"])
            return ps.text, ps.close
        log.info("Streaming %s with Python tarfile (install pigz for speed)", path)
        tf = tarfile.open(path, mode="r|gz")
        for member in tf:
            if member.isfile() and member.name.lower().endswith(".tsv"):
                fh = tf.extractfile(member)
                raw = io.BufferedReader(_Unseekable(fh), buffer_size=1 << 20)
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
                return text, tf.close
        tf.close()
        sys.exit(f"No .tsv member found in {path}")
    if lower.endswith(".gz"):
        import gzip
        fh = gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
        return fh, fh.close
    fh = open(path, "r", encoding="utf-8", errors="replace", newline="")
    return fh, fh.close


def clean_seq(raw):
    """Strip gaps and whitespace, upper-case, map non-IUPAC characters to N."""
    s = "".join(raw.split()).replace("-", "").replace(".", "").upper()
    return "".join(c if c in IUPAC_DNA else "N" for c in s)


def acgt_count(s):
    return sum(s.count(c) for c in "ACGT")


def extract_sequences(path, wanted, label_col, marker):
    """Return {label: sequence} for labels in `wanted`.

    With label_col == 'processid' each label is expected once, and reading
    stops as soon as all labels are found. For other columns (e.g. bin_uri)
    the record with the most unambiguous bases is kept per label."""
    csv.field_size_limit(sys.maxsize)
    stream, closer = open_bcdm(path)
    found = {}
    unique_labels = label_col == "processid"
    try:
        reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader)
        cols = {name: i for i, name in enumerate(header)}
        for needed in (label_col, "nuc"):
            if needed not in cols:
                sys.exit(f"Column '{needed}' not in BCDM header")
        li, ni = cols[label_col], cols["nuc"]
        mi = cols.get("marker_code")
        if marker and mi is None:
            log.warning("No marker_code column; marker filter disabled")
        maxcol = max(li, ni, mi if mi is not None else 0)

        for nrec, row in enumerate(reader, 1):
            if nrec % 5_000_000 == 0:
                log.info("  %d records scanned, %d/%d labels found", nrec, len(found), len(wanted))
            if len(row) <= maxcol:
                continue
            label = row[li]
            if label not in wanted:
                continue
            if marker and mi is not None and row[mi] != marker:
                continue
            seq = clean_seq(row[ni])
            if not seq:
                continue
            if unique_labels:
                found.setdefault(label, seq)
                if len(found) == len(wanted):
                    log.info("All labels found after %d records; stopping early", nrec)
                    break
            else:
                prev = found.get(label)
                if prev is None or acgt_count(seq) > acgt_count(prev):
                    found[label] = seq
    finally:
        closer()
    return found


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------

def write_fasta(seqs, path):
    with open(path, "w") as fh:
        for label, seq in seqs.items():
            fh.write(f">{label}\n")
            for i in range(0, len(seq), 80):
                fh.write(seq[i:i + 80] + "\n")


def hmm_align(fasta, hmm, out_a2m, hmmalign_bin):
    """Align with hmmalign and return {label: match-state-only sequence}.

    In A2M output, match columns are upper case or '-', insert residues are
    lower case (and insert gaps are omitted), so dropping lower case yields
    equal-length rows over the HMM's match states."""
    cmd = [hmmalign_bin, "--trim", "--dna", "--outformat", "A2M", "-o", out_a2m, hmm, fasta]
    log.info("Running: %s", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"hmmalign failed:\n{res.stderr}")
    aligned = {}
    for rec in SeqIO.parse(out_a2m, "fasta"):
        s = "".join(c for c in str(rec.seq) if not c.islower() and c != ".")
        aligned[rec.id] = s
    lengths = {len(s) for s in aligned.values()}
    if len(lengths) > 1:
        sys.exit(f"Match-state rows have unequal lengths: {sorted(lengths)}")
    return aligned


# --------------------------------------------------------------------------
# Distances
# --------------------------------------------------------------------------

_CODE = np.full(256, 4, dtype=np.uint8)
for _c, _v in zip("ACGT", range(4)):  # A=0 C=1 G=2 T=3; purines even, pyrimidines odd
    _CODE[ord(_c)] = _v


def encode(aligned):
    labels = list(aligned)
    mat = np.stack([_CODE[np.frombuffer(aligned[l].encode("ascii"), dtype=np.uint8)]
                    for l in labels])
    return {l: i for i, l in enumerate(labels)}, mat


def seq_distances(mat, idx_a, idx_b, model, min_sites, chunk=10000):
    """Vectorised pairwise distances with pairwise deletion.
    Returns (distances, n_sites); NaN where undefined or below min_sites."""
    n = len(idx_a)
    dist = np.full(n, np.nan)
    sites = np.zeros(n, dtype=np.int64)
    for s in range(0, n, chunk):
        ia, ib = idx_a[s:s + chunk], idx_b[s:s + chunk]
        ok = (ia >= 0) & (ib >= 0)
        if not ok.any():
            continue
        a, b = mat[ia[ok]], mat[ib[ok]]
        valid = (a < 4) & (b < 4)
        diff = (a != b) & valid
        L = valid.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            if model == "p":
                d = diff.sum(axis=1) / L
            elif model == "jc69":
                p = diff.sum(axis=1) / L
                d = -0.75 * np.log(1.0 - (4.0 / 3.0) * p)
            else:  # k2p
                ts = (diff & ((a % 2) == (b % 2))).sum(axis=1)
                tv = diff.sum(axis=1) - ts
                P, Q = ts / L, tv / L
                d = -0.5 * np.log(1.0 - 2.0 * P - Q) - 0.25 * np.log(1.0 - 2.0 * Q)
        d = np.where(np.isfinite(d) & (L >= min_sites), d, np.nan)
        d = np.where(d == 0, 0.0, d)  # normalise -0.0
        pos = np.arange(s, s + len(ia))[ok]
        dist[pos] = d
        sites[pos] = L
    return dist, sites


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def fmt(x):
    return "NA" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.6g}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tree", help="Newick tree")
    ap.add_argument("bcdm", help="BOLD BCDM TSV (.tar.gz, .tsv.gz or .tsv)")
    ap.add_argument("hmm", help="Profile HMM (HMMER 3 format)")
    ap.add_argument("-n", "--npairs", type=int, default=1000, help="Tip pairs to sample [1000]")
    ap.add_argument("--stratify", action="store_true",
                    help="Spread pairs evenly over LCA levels instead of sampling uniformly")
    ap.add_argument("-s", "--seed", type=int, default=None, help="Random seed")
    ap.add_argument("-o", "--out", default="pairs_distances.tsv", help="Output table [%(default)s]")
    ap.add_argument("--fasta", default=None, help="Write extracted sequences here [<out>.fasta]")
    ap.add_argument("--aln", default=None, help="Write hmmalign A2M output here [<out>.a2m]")
    ap.add_argument("--model", choices=["p", "jc69", "k2p"], default="k2p",
                    help="Sequence distance model [%(default)s]")
    ap.add_argument("--min-sites", type=int, default=100,
                    help="Minimum shared unambiguous sites for a distance [%(default)s]")
    ap.add_argument("--label-column", default="processid",
                    help="BCDM column matching the tip labels [%(default)s]; "
                         "use bin_uri for BIN-labelled trees")
    ap.add_argument("--marker", default="COI-5P",
                    help="Only use records with this marker_code; '' disables [%(default)s]")
    ap.add_argument("--hmmalign", default="hmmalign", help="Path to hmmalign [%(default)s]")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)

    hmmalign_bin = shutil.which(args.hmmalign)
    if not hmmalign_bin:
        sys.exit(f"hmmalign not found ({args.hmmalign}); install HMMER 3")
    base = os.path.splitext(args.out)[0]
    fasta_path = args.fasta or base + ".fasta"
    aln_path = args.aln or base + ".a2m"

    rng = random.Random(args.seed)

    # 1-3: tree, pairs, patristic distances
    tree = read_tree(args.tree)
    if args.stratify:
        pairs = sample_pairs_stratified(tree, args.npairs, rng)
    else:
        pairs = sample_pairs(tree.tips, args.npairs, rng)
    pat_lv = [tree.patristic(a, b) for a, b in pairs]
    patristic = [p for p, _ in pat_lv]
    lca_level = [lv for _, lv in pat_lv]
    del tree
    log.info("Sampled %d pairs", len(pairs))

    # 4-5: sequences
    wanted = {x for p in pairs for x in p}
    log.info("Extracting sequences for %d labels from %s", len(wanted), args.bcdm)
    seqs = extract_sequences(args.bcdm, wanted, args.label_column, args.marker or None)
    missing = len(wanted) - len(seqs)
    if missing:
        log.warning("%d of %d labels have no usable sequence", missing, len(wanted))
    if not seqs:
        sys.exit("No sequences found; check --label-column and --marker")
    write_fasta(seqs, fasta_path)

    # 6: align
    aligned = hmm_align(fasta_path, args.hmm, aln_path, hmmalign_bin)
    index, mat = encode(aligned)
    log.info("Alignment: %d sequences x %d match columns", mat.shape[0], mat.shape[1])

    # 7: distances
    ia = np.array([index.get(a, -1) for a, _ in pairs], dtype=np.int64)
    ib = np.array([index.get(b, -1) for _, b in pairs], dtype=np.int64)
    seqdist, nsites = seq_distances(mat, ia, ib, args.model, args.min_sites)

    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["source", "target", "patristic_distance", "sequence_distance",
                    "n_sites", "lca_level"])
        for (a, b), pd, sd, ns, lv in zip(pairs, patristic, seqdist, nsites, lca_level):
            w.writerow([a, b, fmt(pd), fmt(float(sd)), int(ns), lv])

    ok = np.isfinite(seqdist)
    log.info("Wrote %s: %d pairs, %d with a %s distance", args.out, len(pairs), ok.sum(), args.model)
    if ok.sum() > 2:
        pa = np.array(patristic)[ok]
        r = np.corrcoef(pa, seqdist[ok])[0, 1]
        log.info("Pearson r(patristic, %s) = %.3f over %d pairs", args.model, r, ok.sum())


if __name__ == "__main__":
    main()
