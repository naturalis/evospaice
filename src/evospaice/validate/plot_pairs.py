import csv, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

src, out = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open(src), delimiter="\t") if r["sequence_distance"] != "NA"]
pd = np.array([float(r["patristic_distance"]) for r in rows])
sd = np.array([float(r["sequence_distance"]) for r in rows])
lv = np.array([int(r["lca_level"]) for r in rows]) if rows and "lca_level" in rows[0] else None

def ranks(x):
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    cum = np.cumsum(cnt)
    return ((cum - cnt + 1 + cum) / 2.0)[inv]

r = np.corrcoef(pd, sd)[0, 1]
rho = np.corrcoef(ranks(pd), ranks(sd))[0, 1]

order = np.argsort(pd)
bins = np.array_split(order, 10)
bx = [np.median(pd[b]) for b in bins]
by = [np.median(sd[b]) for b in bins]
blo = [np.quantile(sd[b], 0.25) for b in bins]
bhi = [np.quantile(sd[b], 0.75) for b in bins]

fig, ax = plt.subplots(figsize=(7, 5.5), dpi=150)
if lv is None:
    ax.scatter(pd, sd, s=10, alpha=0.35, color="#4c72b0", edgecolor="none", label="tip pairs")
else:
    sc = ax.scatter(pd, sd, s=10, alpha=0.6, c=lv, cmap="viridis", edgecolor="none",
                    label="tip pairs")
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("LCA level (edges from root)")
ax.errorbar(bx, by, yerr=[np.subtract(by, blo), np.subtract(bhi, by)], fmt="o-",
            color="#c44e52", ms=5, lw=1.5, capsize=3, label="decile median (IQR)")
lim = max(pd.max(), sd.max()) * 1.03
ax.plot([0, lim], [0, lim], ls=":", color="grey", lw=1, label="1:1")
ax.set_xlim(0, pd.max() * 1.03)
ax.set_ylim(0, max(sd.max() * 1.1, 0.3))
ax.set_xlabel("Patristic distance (tree)")
ax.set_ylabel("K2P distance (HMM match states)")
ax.set_title(f"Patristic vs sequence distance, n = {len(rows)}\n"
             f"Pearson r = {r:.3f}, Spearman \u03c1 = {rho:.3f}", fontsize=11)
ax.legend(frameon=False, loc="upper right")
ax.grid(alpha=0.2)
fig.tight_layout()
fig.savefig(out)
