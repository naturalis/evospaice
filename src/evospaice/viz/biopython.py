"""Static tree rendering with Biopython and Matplotlib."""

from __future__ import annotations

from pathlib import Path


def render_tree(
    tree_path: Path,
    output_path: Path,
    *,
    title: str = "Evospaice phylogenetic reference tree",
    show_branch_lengths: bool = False,
    show_internal_labels: bool = False,
) -> Path:
    """Render a Newick tree to PNG using a non-interactive backend."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from Bio import Phylo

    tree = Phylo.read(tree_path, "newick")
    leaf_count = tree.count_terminals()
    figure_height = max(6.0, min(40.0, 0.45 * leaf_count + 2.0))
    figure, axes = plt.subplots(figsize=(16, figure_height), constrained_layout=True)
    figure.patch.set_facecolor("#f7f7f2")
    axes.set_facecolor("#f7f7f2")

    branch_labels = (
        (lambda clade: f"{clade.branch_length:.3g}" if clade.branch_length else None)
        if show_branch_lengths
        else None
    )
    Phylo.draw(
        tree,
        axes=axes,
        do_show=False,
        branch_labels=branch_labels,
        label_func=lambda clade: (
            clade.name or "" if show_internal_labels or clade.is_terminal() else ""
        ),
    )
    axes.set_title(title, fontsize=16, fontweight="bold", pad=18)
    axes.set_xlabel("Embedding distance", fontsize=11)
    axes.set_ylabel("")
    axes.tick_params(axis="y", left=False, labelleft=False)
    for spine in ("top", "right", "left"):
        axes.spines[spine].set_visible(False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, facecolor=figure.get_facecolor())
    plt.close(figure)
    return output_path
