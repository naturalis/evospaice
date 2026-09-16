const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const html = fs.readFileSync(
  path.join(__dirname, "../src/evospaice/viz/tree_comparison.html"), "utf8",
);
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({});
vm.runInContext(script, context);
const {parseNewick, matchNewick, treeRF, treePaths, correlation, serializeNewick} = context;
const plain = value => JSON.parse(JSON.stringify(value));
const tree = (newick, ids) => matchNewick(parseNewick(newick), ids).tree;

test("supports comments, support labels, quoted IDs, apostrophes and exponents", () => {
  const ids = ["a_b", "O'Brien", "x:y"];
  const result = tree("[&R](('a_b':1e-2[comment[nested]],'O''Brien':2)0.98:3,'x:y':4);", ids);
  assert.equal(result.hasLengths, true);
  assert.deepEqual(plain(treePaths(result, ids)), [2.01, 7.01, 9]);
  const roundTrip = tree(serializeNewick(result), ids);
  assert.deepEqual(plain(treePaths(roundTrip, ids)), plain(treePaths(result, ids)));
  assert.deepEqual(result.nodes.filter(n => n.leaf).map(n => n.label).sort().join("|"),
    [...ids].sort().join("|"));
});

test("pruning and unary collapse preserve retained pairwise distances", () => {
  const matched = matchNewick(
    parseNewick("(((a:1,b:2):3,x:7):5,c:4,unused:1);"), ["a", "b", "c"],
  );
  assert.equal(matched.originalTips, 5);
  assert.equal(matched.prunedTips, 2);
  assert.deepEqual(plain(treePaths(matched.tree, ["a", "b", "c"])), [3, 13, 14]);
});

test("unrooted RF deduplicates complementary root edges", () => {
  const ids = ["a", "b", "c", "d"];
  const first = tree("((a:1,b:1):2,(c:1,d:1):2);", ids);
  const rerooted = tree("(a:1,b:1,(c:1,d:1):4);", ids);
  const second = tree("((a:1,c:1):2,(b:1,d:1):2);", ids);
  assert.equal(treeRF(first, rerooted).rf, 0);
  assert.equal(treeRF(first, rerooted).shared, 1);
  assert.equal(treeRF(first, second).rf, 2);
  assert.equal(treeRF(first, second).rf_normalized, 1);
  const star = tree("(a,b,c,d);", ids);
  assert.equal(treeRF(first, star).rf, 1);
  assert.equal(treeRF(star, star).rf_normalized, null);
});

test("missing lengths are distinct from zero lengths", () => {
  const ids = ["a", "b", "c"];
  const incomplete = tree("((a:1,b:2),c:4);", ids);
  assert.equal(incomplete.hasLengths, false);
  assert.equal(treePaths(incomplete, ids), null);
  assert.equal(tree(serializeNewick(incomplete), ids).hasLengths, false);
  const zero = tree("(a:0,b:0,c:0);", ids);
  assert.equal(zero.hasLengths, true);
  assert.deepEqual(plain(treePaths(zero, ids)), [0, 0, 0]);
  assert.equal(tree("((a:1,b:2):3,unused);", ["a", "b"]).hasLengths, true);
});

test("rejects duplicate IDs, including duplicates outside the cohort", () => {
  assert.throws(() => tree("(a,b,a);", ["a", "b"]), /Duplicate tip ID: a/);
  assert.throws(() => tree("(a,b,x,x);", ["a", "b"]), /Duplicate tip ID: x/);
});

test("requires all original record IDs and preserves case", () => {
  assert.throws(() => tree("(a,b,x);", ["a", "b", "c", "d"]), /Missing 2 of 4/);
  assert.throws(() => tree("(A,b);", ["a", "b"]), /Missing 1 of 2/);
});

for (const input of [
  "", "(a,b)", "(a,b);(c,d);", "(a,,b);", "();", "(a,b));", "('a,b);",
  "(a:NaN,b:1);", "(a:Infinity,b:1);", "(a:1e999,b:1);", "(a:-1,b:1);",
  "(a:1x,b:1);", "(a:,b:1);", "(a,b)[unfinished;", "(a,b)];",
]) {
  test(`rejects malformed or unsupported Newick: ${JSON.stringify(input)}`, () => {
    assert.throws(() => parseNewick(input));
  });
}

test("handles deep input without recursive parsing or pruning", () => {
  const input = "(".repeat(12000) + "a:1" + "):1".repeat(12000) + ";";
  const result = tree(input, ["a"]);
  assert.equal(result.nodes.length, 1);
  assert.equal(result.nodes[0].label, "a");
});

test("rejects overflowing retained paths", () => {
  assert.throws(() => tree("((a:1e308,b:1):1e308,c:1);", ["a", "b", "c"]),
    /numeric range/);
});

test("correlations are scale-independent and unavailable for missing or constant paths", () => {
  assert.equal(correlation([1, 2, 3], [10, 20, 30]), 1);
  assert.equal(correlation([1, 2, 3], [30, 20, 10]), -1);
  assert.equal(correlation([1, 2, 3], [1e300, 2e300, 3e300]), 1);
  assert.equal(correlation(null, [1, 2, 3]), null);
  assert.equal(correlation([0, 0, 0], [1, 2, 3]), null);
});
