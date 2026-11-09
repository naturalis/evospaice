const assert = require("node:assert/strict");

module.exports = async (page, {records = 48, clade = "Family B", refresh = false} = {}) => {
  const errors = [], submissions = [], results = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/jobs") {
      submissions.push(request.postDataJSON());
    }
  });
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => !document.getElementById("run").disabled, null, {timeout: 120000});
  assert.ok((await page.locator("#source-title").textContent()).includes(records.toLocaleString()));
  assert.equal(await page.locator("#result").isVisible(), false, "no precomputed view on load");
  assert.equal(submissions.length, 0);
  const initial = await (await page.request.get("/api/source")).json();
  const frame = page.frameLocator("#result");
  const allMethods = Object.keys(initial.methods);
  assert.equal(await page.locator("#method-options input:checked").count(), 5);
  for (const method of allMethods) {
    assert.ok(await page.locator(`#method-${method}`).isVisible());
  }

  async function selectMethods(methods) {
    for (const method of allMethods) {
      await page.locator(`#method-${method}`).setChecked(methods.includes(method));
    }
  }

  async function run(expectedMethods, expectedRecords) {
    await page.click("#run");
    await page.waitForFunction(() => document.getElementById("job-status").textContent.startsWith(
      "Newly computed"), null, {timeout: 120000});
    await frame.locator("#specimens").waitFor({timeout: 30000});
    assert.ok(await frame.locator("#specimens path.edge").count() > 0);
    const src = await page.locator("#result").getAttribute("src");
    const data = await (await page.request.get(src.replace("/view", "/result"))).json();
    assert.deepEqual(Object.keys(data.trees).sort(), [...expectedMethods].sort());
    assert.equal(data.records, expectedRecords);
    assert.equal(data.computation.cached, false);
    assert.equal(data.computation.live, true);
    assert.ok((await frame.locator("#computation-mode").textContent()).includes("rebuilt on demand"));
    const serialized = JSON.stringify(data.trees);
    results.push({records: data.records, methods: expectedMethods, seconds: data.computation.seconds});
    return {data, serialized, src};
  }
  await page.click("#clear-methods");
  assert.equal(await page.locator("#run").isDisabled(), true);
  await page.click("#select-all");
  const first = await run(allMethods, records);
  assert.equal(await frame.locator("#tip-table tr").count(), records === 48 ? 4 : 7);
  assert.equal(submissions.length, 1);
  assert.deepEqual(submissions[0].path, []);
  const selectors = frame.locator("#left-method, #right-method");
  assert.equal(await selectors.count(), 2);
  await selectors.nth(1).selectOption("wasserstein");
  await frame.locator("#view-mode").selectOption("length");
  assert.ok((await frame.locator("#view-notice").textContent()).includes("Independent horizontal"));
  assert.ok((await frame.locator("#specimens").textContent()).includes("W2 in raw vector units"));
  for (const selector of await selectors.all()) {
    for (const method of allMethods) {
      assert.equal(await selector.locator(`option[value="${method}"]`).count(), 1);
      await selector.selectOption(method);
    }
  }
  await selectMethods(["medoid", "weighted"]);
  assert.equal(await page.locator("#result").isVisible(), false, "changed methods hide stale view");
  assert.equal(submissions.length, 1, "selection alone does not silently show an old computation");
  await page.fill("#clade-search", clade);
  await page.locator("#clade-results button").first().click();
  const taxon = initial.taxa.find(taxon => taxon.label === clade && taxon.rank === "family");
  assert.ok(taxon);
  const second = await run(["medoid", "weighted"], taxon.records);
  assert.equal(submissions.length, 2, "Run triggered a second live POST");
  assert.notEqual(first.serialized, second.serialized);
  assert.equal(submissions[1].path.at(-1), clade);
  assert.equal(await frame.locator("#selected-label").textContent(), clade);
  const computed = page.frames().find(frame => frame.url().endsWith(second.src));
  const exported = await computed.evaluate(() => newick("medoid", 0));
  assert.ok(exported.trim().endsWith(";"));
  assert.equal((exported.match(/'record-/g) || []).length, records === 48 ? taxon.records : 0);
  assert.ok((await frame.locator("#left-note").textContent()).includes("Actual representative record"));
  assert.equal((await page.request.get(first.src.replace("/view", "/result"))).status(), 410);

  // Rebuild a real species using the fifth method and the other NJ backend.
  const familyIndex = initial.taxa.indexOf(taxon);
  const genusIndex = taxon.children[0];
  const genus = initial.taxa[genusIndex];
  const speciesIndex = genus.children[0];
  const species = initial.taxa[speciesIndex];
  assert.equal(genus.parent, familyIndex);
  await page.fill("#clade-search", species.label);
  await page.locator("#clade-results button").filter({hasText: clade}).first().click();
  await selectMethods(["frechet"]);
  await page.selectOption("#backend", "biopython");
  const third = await run(["frechet"], species.records);
  assert.equal(third.data.computation.backend, "biopython");
  assert.equal(third.data.computation.path.length, 4);
  assert.equal(await frame.locator("#selected-label").textContent(), species.label);

  // Browser validation errors are explicit and never leave old trees visible.
  await page.fill("#max-children", "999");
  await page.click("#run");
  await page.waitForFunction(() => document.getElementById("job-status").textContent.includes(
    "between 2 and 512"));
  assert.equal(await page.locator("#result").isVisible(), false);
  await page.fill("#max-children", "512");
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.emulateMedia({reducedMotion: "reduce"});
  assert.equal(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches), true);
  await page.setViewportSize({width: 1440, height: 1100});

  if (refresh) {
    await page.click("#refresh");
    await page.waitForFunction(() => document.getElementById("job-status").textContent.startsWith(
      "Azure data refreshed and verified"), null, {timeout: 120000});
    const current = await (await page.request.get("/api/source")).json();
    assert.notEqual(current.generation, initial.generation);
    assert.notEqual(current.source.loadedUtc, initial.source.loadedUtc);
    assert.equal(current.records, records);
    assert.equal(await page.locator("#result").isVisible(), false);
    assert.equal(await page.locator("#scope").textContent(), `Complete cohort · ${records.toLocaleString()} records`);
  }
  assert.deepEqual(errors, []);
  return {passed: true, records, liveRuns: results, submissions: submissions.length,
    refreshVerified: refresh, errors};
};

if (require.main === module) {
  const fs = require("node:fs"), path = require("node:path");
  const artifacts = path.join(__dirname, `.live-browser-${process.pid}`);
  fs.mkdirSync(artifacts);
  process.env.TMPDIR = artifacts;
  (async () => {
    let browser;
    try {
      const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
      browser = await chromium.launch({
        headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE || undefined,
        downloadsPath: artifacts,
      });
      const context = await browser.newContext({
        viewport: {width: 1440, height: 1100}, baseURL: process.argv[2],
        acceptDownloads: false,
      });
      const page = await context.newPage();
      await page.goto(process.argv[2], {waitUntil: "networkidle"});
      const real = process.argv.includes("--real");
      console.log(JSON.stringify(await module.exports(page,
        real ? {records: 5000, clade: "Papilionidae", refresh: true} : {})));
    } finally {
      if (browser) await browser.close();
      fs.rmSync(artifacts, {recursive: true, force: true});
    }
  })().catch(error => { console.error(error); process.exitCode = 1; });
}
