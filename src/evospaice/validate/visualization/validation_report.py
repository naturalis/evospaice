"""Render an `evospaice validate` run as a self-contained HTML report.

Draws the reference and inferred trees as side-by-side dendrograms, color-coded
by shared / inferred-only / reference-only splits, plus a tip-to-root rank
correlation scatter plot. Reads the Newick inputs and the `--output-dir` a
prior `evospaice validate` run already wrote (`validation.json` and
`tip_to_root_correlation.csv`), and writes one HTML file with no external
dependencies (fonts are the only network fetch, from Google Fonts).

Run as a script, e.g.:
    python -m evospaice.viz.validation_report \\
        --reference tests/data/reference_tree_large_mock.nwk \\
        --inferred tests/data/embedding_tree_large_mock.nwk \\
        --results-dir results/validation-mock-large2 \\
        --output results/validation-mock-large2/report.html
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

import dendropy

LEAF_GAP = 24
TOP_MARGIN = 24
BOTTOM_MARGIN = 24
X_UNIT = 60
LEFT_MARGIN = 16
LABEL_GAP = 8


def _height(node: dendropy.Node) -> int:
    children = node.child_nodes()
    if not children:
        return 0
    return 1 + max(_height(c) for c in children)


def _mean_y(ys: list[float]) -> float:
    return sum(ys) / len(ys)


class TreeLayout:
    """x/y pixel coordinates for every node of one tree, given a fixed leaf order."""

    def __init__(self, tree: dendropy.Tree, leaf_order: list[str]):
        self.tree = tree
        order_index = {label: i for i, label in enumerate(leaf_order)}
        self.max_height = _height(tree.seed_node)
        self.x: dict[int, float] = {}
        self.y: dict[int, float] = {}

        def visit(node: dendropy.Node) -> float:
            node_height = _height(node)
            x_level = self.max_height - node_height
            self.x[id(node)] = LEFT_MARGIN + x_level * X_UNIT
            if node.is_leaf():
                y = TOP_MARGIN + order_index[node.taxon.label] * LEAF_GAP
            else:
                y = _mean_y([visit(c) for c in node.child_nodes()])
            self.y[id(node)] = y
            return y

        visit(tree.seed_node)

    @property
    def width(self) -> float:
        return LEFT_MARGIN + self.max_height * X_UNIT

    @property
    def height(self) -> float:
        return TOP_MARGIN + (len(self.y) and max(self.y.values()) - TOP_MARGIN) + BOTTOM_MARGIN


def informative_splits(tree: dendropy.Tree) -> dict[frozenset[str], dendropy.Node]:
    """Map each non-trivial split's leaf set to the node whose branch defines it."""
    n = len(tree.leaf_nodes())
    splits = {}
    for node in tree.preorder_node_iter():
        if node.parent_node is None:
            continue
        leaves = frozenset(leaf.taxon.label for leaf in node.leaf_iter())
        if 1 < len(leaves) < n:
            splits[leaves] = node
    return splits


def render_tree_svg(
    layout: TreeLayout, leaf_order: list[str], status: dict[int, str], colors: dict[str, str],
    split_labels: dict[int, str],
) -> str:
    max_label_len = max((len(label) for label in leaf_order), default=1)
    label_space = max_label_len * 7 + LABEL_GAP + 6
    view_w = layout.width + label_space
    view_h = layout.height

    parts = []
    tree = layout.tree

    def edge_status(node: dendropy.Node) -> str:
        return status.get(id(node), "structural")

    # structural verticals: at each internal node's x, span its children's y range
    for node in tree.preorder_node_iter():
        children = node.child_nodes()
        if len(children) < 2:
            continue
        cx = layout.x[id(node)]
        ys = [layout.y[id(c)] for c in children]
        parts.append(
            f'<line x1="{cx:.1f}" y1="{min(ys):.1f}" x2="{cx:.1f}" y2="{max(ys):.1f}" '
            f'stroke="{colors["structural"]}" stroke-width="1.5"/>'
        )

    # root stub
    root_x = layout.x[id(tree.seed_node)]
    root_y = layout.y[id(tree.seed_node)]
    parts.append(
        f'<line x1="{root_x - 12:.1f}" y1="{root_y:.1f}" x2="{root_x:.1f}" y2="{root_y:.1f}" '
        f'stroke="{colors["muted"]}" stroke-width="1.5"/>'
    )

    # branches: for every non-root node, a horizontal segment from parent.x to node.x at node.y
    leaf_edges, colored_edges = [], []
    for node in tree.preorder_node_iter():
        if node.parent_node is None:
            continue
        px = layout.x[id(node.parent_node)]
        nx = layout.x[id(node)]
        ny = layout.y[id(node)]
        if node.is_leaf():
            leaf_edges.append((px, nx, ny))
        else:
            st = edge_status(node)
            colored_edges.append((px, nx, ny, st))

    for px, nx, ny in leaf_edges:
        parts.append(
            f'<line x1="{px:.1f}" y1="{ny:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
            f'stroke="{colors["muted"]}" stroke-width="1.2"/>'
        )
    for px, nx, ny, st in colored_edges:
        color = colors.get(st, colors["structural"])
        parts.append(
            f'<line x1="{px:.1f}" y1="{ny:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
            f'stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
        )
        if st in ("inferred_only", "reference_only"):
            parts.append(f'<circle cx="{px:.1f}" cy="{ny:.1f}" r="3" fill="{color}"/>')

    # split labels for non-shared splits
    for node in tree.preorder_node_iter():
        if id(node) not in split_labels:
            continue
        px = layout.x[id(node.parent_node)]
        nx = layout.x[id(node)]
        ny = layout.y[id(node)]
        color = colors.get(edge_status(node), colors["structural"])
        mid = (px + nx) / 2
        parts.append(
            f'<text class="clade-label" fill="{color}" x="{mid:.1f}" y="{ny - 6:.1f}" '
            f'text-anchor="middle">{html.escape(split_labels[id(node)])}</text>'
        )

    # leaf labels
    for leaf in tree.leaf_node_iter():
        lx = layout.x[id(leaf)]
        ly = layout.y[id(leaf)]
        parts.append(
            f'<text class="leaf-label" x="{lx + LABEL_GAP:.1f}" y="{ly + 4:.1f}">'
            f'{html.escape(leaf.taxon.label)}</text>'
        )

    body = "\n          ".join(parts)
    return f'<svg viewBox="0 0 {view_w:.1f} {view_h:.1f}" role="img" aria-label="Dendrogram">\n          {body}\n        </svg>'


def build_tree_section(
    ref_tree: dendropy.Tree, inf_tree: dendropy.Tree, leaf_order: list[str], colors: dict[str, str],
) -> tuple[str, dict]:
    ref_splits = informative_splits(ref_tree)
    inf_splits = informative_splits(inf_tree)
    shared_keys = set(ref_splits) & set(inf_splits)
    ref_only_keys = set(ref_splits) - set(inf_splits)
    inf_only_keys = set(inf_splits) - set(ref_splits)

    ref_status, inf_status, ref_labels, inf_labels = {}, {}, {}, {}
    for key in shared_keys:
        ref_status[id(ref_splits[key])] = "shared"
        inf_status[id(inf_splits[key])] = "shared"
    for key in ref_only_keys:
        ref_status[id(ref_splits[key])] = "reference_only"
        ref_labels[id(ref_splits[key])] = ", ".join(sorted(key))
    for key in inf_only_keys:
        inf_status[id(inf_splits[key])] = "inferred_only"
        inf_labels[id(inf_splits[key])] = ", ".join(sorted(key))

    ref_layout = TreeLayout(ref_tree, leaf_order)
    inf_layout = TreeLayout(inf_tree, leaf_order)
    ref_svg = render_tree_svg(ref_layout, leaf_order, ref_status, colors, ref_labels)
    inf_svg = render_tree_svg(inf_layout, leaf_order, inf_status, colors, inf_labels)

    counts = dict(
        shared=len(shared_keys), reference_only=len(ref_only_keys), inferred_only=len(inf_only_keys),
        reference_only_clades=sorted(sorted(k) for k in ref_only_keys),
        inferred_only_clades=sorted(sorted(k) for k in inf_only_keys),
    )
    section = f"""
    <div class="trees">
      <div class="tree-panel">
        <div class="cap">Inferred &middot; {len(inf_splits)} informative splits</div>
        {inf_svg}
      </div>
      <div class="tree-panel">
        <div class="cap">Reference &middot; {len(ref_splits)} informative splits</div>
        {ref_svg}
      </div>
    </div>
    """
    return section, counts


def build_scatter_svg(rows: list[dict], colors: dict[str, str]) -> str:
    n = len(rows)
    pad, plot_w, plot_h = 36, 260, 260
    view_w, view_h = plot_w + pad * 2 + 10, plot_h + pad * 2

    def sx(rank: float) -> float:
        return pad + (rank - 1) / max(n - 1, 1) * plot_w

    def sy(rank: float) -> float:
        return pad + plot_h - (rank - 1) / max(n - 1, 1) * plot_h

    parts = [
        f'<line x1="{pad}" y1="{pad + plot_h}" x2="{pad + plot_w}" y2="{pad + plot_h}" '
        f'stroke="{colors["muted"]}" stroke-width="1"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{pad + plot_h}" stroke="{colors["muted"]}" stroke-width="1"/>',
        f'<line x1="{pad}" y1="{pad + plot_h}" x2="{pad + plot_w}" y2="{pad}" '
        f'stroke="{colors["structural"]}" stroke-width="1.5" stroke-dasharray="4 3"/>',
        f'<text x="{pad + plot_w / 2:.1f}" y="{pad + plot_h + 26}" text-anchor="middle" class="axis-label">'
        f'reference rank (root&#8594;tip distance)</text>',
        f'<text x="{-(pad + plot_h / 2):.1f}" y="12" text-anchor="middle" class="axis-label" '
        f'transform="rotate(-90)">inferred rank</text>',
    ]
    for row in rows:
        x = sx(float(row["reference_rank"]))
        y = sy(float(row["inferred_rank"]))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{colors["inferred_only"]}" fill-opacity="0.85"/>')
        parts.append(
            f'<text x="{x + 7:.1f}" y="{y + 3:.1f}" class="scatter-label">{html.escape(row["taxon"])}</text>'
        )
    body = "\n          ".join(parts)
    return f'<svg viewBox="0 0 {view_w} {view_h}" role="img" aria-label="Tip-to-root rank correlation scatter plot">\n          {body}\n        </svg>'


PALETTE = dict(
    shared="#3B7A4E", inferred_only="#2569A0", reference_only="#B15A1E",
    structural="#D6E1D0", muted="#56695C", ink="#1E2B22",
)

PAGE_TEMPLATE = """<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root{{
    --bg:#F3F6F0; --surface:#FFFFFF; --surface-alt:#EAF0E6; --ink:#1E2B22; --muted:#56695C; --border:#D6E1D0;
    --agree:#3B7A4E; --agree-soft:#E4F1E7; --inferred:#2569A0; --inferred-soft:#E3EEF7;
    --refonly:#B15A1E; --refonly-soft:#F7E9DC;
  }}
  @media (prefers-color-scheme: dark){{
    :root:not([data-theme="light"]){{
      --bg:#12180F; --surface:#1B2318; --surface-alt:#20291C; --ink:#E7EDE3; --muted:#9CAD97; --border:#33402D;
      --agree:#72C287; --agree-soft:rgba(114,194,135,0.14); --inferred:#74B6EB; --inferred-soft:rgba(116,182,235,0.14);
      --refonly:#E49A54; --refonly-soft:rgba(228,154,84,0.16);
    }}
  }}
  :root[data-theme="dark"]{{
    --bg:#12180F; --surface:#1B2318; --surface-alt:#20291C; --ink:#E7EDE3; --muted:#9CAD97; --border:#33402D;
    --agree:#72C287; --agree-soft:rgba(114,194,135,0.14); --inferred:#74B6EB; --inferred-soft:rgba(116,182,235,0.14);
    --refonly:#E49A54; --refonly-soft:rgba(228,154,84,0.16);
  }}
  * {{ box-sizing: border-box; }}
  body{{ background:var(--bg); color:var(--ink); font-family:"Public Sans", ui-sans-serif, system-ui, sans-serif;
        padding-inline:20px; padding-block:40px; }}
  .page{{ max-width:960px; margin-inline:auto; display:flex; flex-direction:column; gap:32px; }}
  .eyebrow{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:12px; letter-spacing:0.08em;
            text-transform:uppercase; color:var(--muted); }}
  h1{{ font-family:"Source Serif 4", Georgia, serif; font-weight:700; font-size:clamp(26px, 4vw, 36px);
      line-height:1.15; margin:8px 0 0; text-wrap:balance; }}
  .lede{{ max-width:64ch; color:var(--muted); font-size:15px; line-height:1.6; margin-top:10px; }}
  .lede code{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:0.92em; background:var(--surface-alt);
              padding:1px 5px; border-radius:4px; color:var(--ink); }}
  .stats{{ display:grid; grid-template-columns:repeat(6, 1fr); gap:1px; background:var(--border);
          border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
  .stat{{ background:var(--surface); padding:14px 10px; display:flex; flex-direction:column; gap:4px; }}
  .stat .n{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums;
            font-size:21px; font-weight:500; }}
  .stat .lbl{{ font-size:11px; color:var(--muted); line-height:1.35; }}
  .stat.agree .n{{ color:var(--agree); }} .stat.inf .n{{ color:var(--inferred); }} .stat.ref .n{{ color:var(--refonly); }}
  @media (max-width: 720px){{ .stats{{ grid-template-columns:repeat(3, 1fr); }} }}
  section h2{{ font-family:"Source Serif 4", Georgia, serif; font-size:19px; font-weight:600; margin:0 0 4px; }}
  section .sub{{ color:var(--muted); font-size:13.5px; margin:0 0 16px; max-width:62ch; line-height:1.5; }}
  .legend{{ display:flex; flex-wrap:wrap; gap:18px; font-size:13px; color:var(--muted); margin-bottom:18px; }}
  .legend .item{{ display:flex; align-items:center; gap:7px; }}
  .legend .swatch{{ width:18px; height:3px; border-radius:2px; flex:none; }}
  .legend .swatch.agree{{ background:var(--agree); }} .legend .swatch.inf{{ background:var(--inferred); }}
  .legend .swatch.ref{{ background:var(--refonly); }}
  .trees{{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media (max-width: 720px){{ .trees{{ grid-template-columns:1fr; }} }}
  .tree-panel{{ background:var(--surface); border:1px solid var(--border); border-radius:12px;
               padding:18px 16px 14px; }}
  .tree-panel .cap{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:11px; letter-spacing:0.04em;
                     text-transform:uppercase; color:var(--muted); margin-bottom:10px; }}
  .tree-panel svg{{ width:100%; height:auto; display:block; overflow:visible; }}
  .leaf-label{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:11px; fill:var(--ink); }}
  .clade-label{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:9px; }}
  .scatter-panel{{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px;
                   display:flex; flex-direction:column; align-items:center; gap:10px; }}
  .scatter-panel svg{{ max-width:360px; width:100%; height:auto; }}
  .axis-label{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:10px; fill:var(--muted); }}
  .scatter-label{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:9.5px; fill:var(--ink); }}
  .rho-note{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:12px; color:var(--muted); }}
  .rho-note strong{{ color:var(--ink); font-size:14px; }}
  .diverge{{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media (max-width: 720px){{ .diverge{{ grid-template-columns:1fr; }} }}
  .diverge .col{{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }}
  .diverge .col h3{{ font-size:13px; font-weight:600; margin:0 0 12px; display:flex; align-items:center; gap:8px; }}
  .diverge .col h3 .dot{{ width:9px; height:9px; border-radius:50%; flex:none; }}
  .diverge .col.inf h3 .dot{{ background:var(--inferred); }} .diverge .col.ref h3 .dot{{ background:var(--refonly); }}
  .clade-row{{ display:flex; align-items:baseline; justify-content:space-between; gap:10px; padding:8px 0;
              border-top:1px solid var(--border); font-size:13px; }}
  .clade-row:first-of-type{{ border-top:none; }}
  .clade-row .taxa{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:12px; }}
  .clade-row .n{{ color:var(--muted); font-size:11px; white-space:nowrap; }}
  footer{{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:11.5px; color:var(--muted);
          line-height:1.7; border-top:1px solid var(--border); padding-top:16px; }}
  footer .path{{ color:var(--ink); }}
</style>
<div class="page">
  <header>
    <div class="eyebrow">{eyebrow}</div>
    <h1>{heading}</h1>
    <p class="lede">{lede}</p>
  </header>
  <div class="stats">
    <div class="stat rf"><div class="n">{rf}</div><div class="lbl">RF distance</div></div>
    <div class="stat rf"><div class="n">{rf_pct}</div><div class="lbl">normalized ({rf}/{denom})</div></div>
    <div class="stat agree"><div class="n">{shared}</div><div class="lbl">shared splits</div></div>
    <div class="stat inf"><div class="n">{inferred_only}</div><div class="lbl">inferred&#8209;only</div></div>
    <div class="stat ref"><div class="n">{reference_only}</div><div class="lbl">reference&#8209;only</div></div>
    <div class="stat"><div class="n">{rho}</div><div class="lbl">tip&#8209;to&#8209;root &rho;</div></div>
  </div>
  <section>
    <h2>Topology side by side</h2>
    <p class="sub">Same taxa, same vertical order in both panels &mdash; a branch that lines up at a different height marks a disagreement.</p>
    <div class="legend">
      <div class="item"><span class="swatch agree"></span> shared split</div>
      <div class="item"><span class="swatch inf"></span> only in inferred</div>
      <div class="item"><span class="swatch ref"></span> only in reference</div>
    </div>
    {tree_section}
  </section>
  <section>
    <h2>Tip-to-root rank correlation</h2>
    <p class="sub">Each tip's root-to-tip branch-length sum, ranked within its own tree (raw sums can be in different units between trees, so ranks are what Spearman &rho; actually compares). Points on the dashed diagonal agree exactly.</p>
    <div class="scatter-panel">
      {scatter_svg}
      <div class="rho-note">Spearman &rho; = <strong>{rho}</strong> across {tip_count} matched tips</div>
    </div>
  </section>
  <section>
    <h2>Where they diverge</h2>
    <p class="sub">The non-shared splits from the diagram above, spelled out.</p>
    <div class="diverge">
      <div class="col inf">
        <h3><span class="dot"></span>Only in the inferred tree</h3>
        {inferred_only_rows}
      </div>
      <div class="col ref">
        <h3><span class="dot"></span>Only in the reference tree</h3>
        {reference_only_rows}
      </div>
    </div>
  </section>
  <footer>
    <div>inferred: <span class="path">{inferred_path}</span></div>
    <div>reference: <span class="path">{reference_path}</span></div>
    <div>source: <span class="path">{results_dir}</span></div>
  </footer>
</div>
"""


def clade_rows(clades: list[list[str]]) -> str:
    if not clades:
        return '<p class="sub" style="margin:0;">none</p>'
    return "\n        ".join(
        f'<div class="clade-row"><span class="taxa">{{{html.escape(", ".join(c))}}}</span>'
        f'<span class="n">{len(c)} taxa</span></div>'
        for c in clades
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--inferred", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True, help="Output dir from `evospaice validate`.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Validation Report")
    args = parser.parse_args(argv)

    validation = json.loads((args.results_dir / "validation.json").read_text())
    with open(args.results_dir / "tip_to_root_correlation.csv", newline="") as f:
        corr_rows = list(csv.DictReader(f))

    namespace = dendropy.TaxonNamespace()
    ref_tree = dendropy.Tree.get(path=str(args.reference), schema="newick", taxon_namespace=namespace)
    inf_tree = dendropy.Tree.get(path=str(args.inferred), schema="newick", taxon_namespace=namespace)
    leaf_order = [leaf.taxon.label for leaf in ref_tree.leaf_node_iter()]

    tree_section, counts = build_tree_section(ref_tree, inf_tree, leaf_order, PALETTE)
    scatter_svg = build_scatter_svg(corr_rows, PALETTE)

    topo = validation["topology"]
    rho = validation.get("tip_to_root_correlation", {}).get("rho")
    tip_count = validation.get("tip_to_root_correlation", {}).get("compared_tip_count", len(corr_rows))

    page = PAGE_TEMPLATE.format(
        title=html.escape(args.title),
        eyebrow=html.escape(f"Topology validation &middot; {validation.get('mode', '')} mode"),
        heading="Where the inferred tree agrees with the reference &mdash; and where it doesn&rsquo;t",
        lede=(
            f"Comparing <code>{html.escape(args.inferred.name)}</code> (inferred) against "
            f"<code>{html.escape(args.reference.name)}</code> (reference) across "
            f"{validation.get('retained_taxa', len(leaf_order))} shared taxa."
        ),
        rf=topo["rf"], rf_pct=f"{topo['rf_normalized'] * 100:.1f}%", denom=topo["rf_denominator"],
        shared=counts["shared"], inferred_only=counts["inferred_only"], reference_only=counts["reference_only"],
        rho=f"{rho:.3f}" if rho is not None else "n/a", tip_count=tip_count,
        tree_section=tree_section, scatter_svg=scatter_svg,
        inferred_only_rows=clade_rows(counts["inferred_only_clades"]),
        reference_only_rows=clade_rows(counts["reference_only_clades"]),
        inferred_path=str(args.inferred), reference_path=str(args.reference), results_dir=str(args.results_dir),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
