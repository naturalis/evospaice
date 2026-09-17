const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const html = fs.readFileSync(path.join(__dirname, "../src/evospaice/tree/explorer.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].split("try{initialize()}")[0];

function fixture(shape, labels = ["a", "b", "c", "d"]) {
  const taxa = [{label: "root", children: labels.map((_, i) => i + 1), parent: null, depth: 0}];
  labels.forEach(label => taxa.push({label, children: [], parent: 0, depth: 1, records: 1}));
  const nodes = [], taxonRoots = {};
  function visit(part, root = false) {
    const index = nodes.length, leaf = typeof part === "number", taxon = leaf ? part : root ? 0 : null;
    nodes.push({label: taxon === null ? "" : taxa[taxon].label,
      children: [], taxon, length: root ? 0 : 1});
    if (taxon !== null) taxonRoots[taxon] = index;
    if (!leaf) nodes[index].children = part.map(p => visit(p));
    return index;
  }
  visit(shape, true);
  const data = {taxa, trees: {centroid: {nodes, root: 0, taxonRoots}}};
  const context = vm.createContext({document: {getElementById: id =>
    id === "explorer-data" ? {textContent: JSON.stringify(data)} : {value: "topology"}}});
  vm.runInContext(script, context);
  return context;
}

test("unrooted RF deduplicates complementary root edges and excludes trivial splits", () => {
  const c = fixture([[1, 2], [3, 4]]), a = c.buildView("centroid", 0, 1);
  const rerooted = fixture([1, 2, [3, 4]]).buildView("centroid", 0, 1);
  const b = fixture([[1, 3], [2, 4]]).buildView("centroid", 0, 1);
  const star = fixture([1, 2, 3, 4]).buildView("centroid", 0, 1);
  assert.equal(a.splits.size, 1);
  assert.equal(c.splitDifference(a.splits, rerooted.splits).rf, 0);
  assert.equal(c.splitDifference(a.splits, b.splits).rf, 2);
  assert.equal(c.splitDifference(a.splits, star.splits).rf, 1);
  assert.equal(c.splitDifference(star.splits, star.splits).rf, 0);
});

test("topology and source branch lengths survive encoding and repeated views", () => {
  const c = fixture([[1, 2], [3, 4]]);
  const first = c.newick("centroid", 0);
  c.buildView("centroid", 0, 1);
  c.buildView("centroid", 0, 1);
  assert.equal(c.newick("centroid", 0), first);
  assert.equal(first, "(('a':1,'b':1):1,('c':1,'d':1):1)'root':0;\n");
  assert.equal(c.newick("centroid", 1), "'a':0;\n");
});

test("Newick quotes apostrophes, delimiters and HTML-like labels", () => {
  const c = fixture([1, 2, 3, 4], ["O'Brien", "x:y", "(x)", "</script>"]);
  const output = c.newick("centroid", 0);
  assert.ok(output.includes("'O''Brien':1"));
  assert.ok(output.includes("'x:y':1"));
  assert.ok(output.includes("'(x)':1"));
  assert.ok(output.includes("'</script>':1"));
});

test("large views preserve all tips but stop display-specific split work", () => {
  const count = 601, labels = Array.from({length: count}, (_, i) => String(i));
  const c = fixture(labels.map((_, i) => i + 1), labels);
  const view = c.buildView("centroid", 0, 1);
  assert.equal(view.tips.length, 601);
  assert.equal(view.nodes.length, 602);
  assert.equal(view.splits.size, 0);
  assert.equal((c.newick("centroid", 0).match(/:1/g) || []).length, 601);
});

test("singletons have no nontrivial splits", () => {
  const c = fixture([1], ["only"]);
  const view = c.buildView("centroid", 0, 1);
  assert.equal(view.tips.length, 1);
  assert.equal(view.splits.size, 0);
  assert.equal(view.nodes[0].length, 0);
});
