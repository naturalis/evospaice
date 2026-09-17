import csv, sys
import numpy as np

def ranks(x):
    # average ranks, ties shared
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    cum = np.cumsum(cnt)
    return ((cum - cnt + 1 + cum) / 2.0)[inv]

rows = [r for r in csv.DictReader(open(sys.argv[1]), delimiter="\t") if r["sequence_distance"] != "NA"]
pd = np.array([float(r["patristic_distance"]) for r in rows])
sd = np.array([float(r["sequence_distance"]) for r in rows])
ns = np.array([int(r["n_sites"]) for r in rows])
print(f"pairs: {len(rows)}   distinct patristic values: {len(np.unique(pd))}")
print(f"Pearson {np.corrcoef(pd, sd)[0,1]:.3f}   Spearman {np.corrcoef(ranks(pd), ranks(sd))[0,1]:.3f}")
print(f"n_sites median {np.median(ns):.0f}, <300 sites: {(ns < 300).mean():.0%}")
print(f"seq distance > 0.25: {(sd > 0.25).mean():.0%}")
edges = np.unique(np.quantile(pd, np.linspace(0, 1, 11)))
print("\npatristic bin          n   seqdist median  IQR")
for lo, hi in zip(edges[:-1], edges[1:]):
    m = (pd >= lo) & ((pd < hi) | (hi == edges[-1]))
    if m.any():
        q1, q2, q3 = np.quantile(sd[m], [0.25, 0.5, 0.75])
        print(f"[{lo:8.4g}, {hi:8.4g}]  {m.sum():5d}   {q2:.3f}          {q1:.3f}-{q3:.3f}")

if rows and "lca_level" in rows[0]:
    lv = np.array([int(r["lca_level"]) for r in rows])
    print("\nLCA level      n   patristic median   seqdist median")
    for l in np.unique(lv):
        m = lv == l
        print(f"{l:9d}  {m.sum():5d}   {np.median(pd[m]):16.4g}   {np.median(sd[m]):.3f}")
