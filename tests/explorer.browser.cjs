module.exports = async (page) => {
  // Run against the synthetic page from tests.test_explorer.synthetic_dataset.
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.waitForLoadState("networkidle");
  check((await page.locator("#selected-label").textContent()) === "Lepidoptera", "initial order");
  check((await page.locator("#tip-table tr").count()) === 4, "all four family representatives");
  check((await page.locator("#cohort").textContent()).includes("48"), "full synthetic cohort");
  for (const method of ["centroid", "medoid", "weighted", "wasserstein", "frechet"]) {
    await page.selectOption("#left-method", method);
    await page.selectOption("#right-method", method);
    check((await page.locator("#comparison-score").textContent()).includes("unrooted RF 0"),
      "same-method RF for " + method);
    check(await page.locator("#specimens path.edge").count() > 0, "actual connector branches");
    check((await page.locator("#left-note .representative-readout").textContent()).includes(
      method === "wasserstein" ? "covariance trace" :
      method === "medoid" ? "Actual representative record" : "Cosine deviation"),
      "actual representative summary for " + method);
  }
  await page.selectOption("#left-method", "centroid");
  await page.selectOption("#right-method", "wasserstein");
  await page.selectOption("#view-mode", "length");
  check((await page.locator("#view-notice").textContent()).includes("Independent horizontal"),
    "independent branch scales");
  check((await page.locator("#specimens").textContent()).includes("W2 in raw vector units"),
    "actual W2 scale label");
  await page.selectOption("#frontier", "4");
  check(await page.locator("#tip-table tr").count() === 24, "all species frontier");
  await page.fill("#search", "Family B");
  await page.locator("#search-results button").first().click();
  check((await page.locator("#selected-label").textContent()) === "Family B", "search navigation");
  check(await page.locator("#tip-table tr").count() === 2, "genus representatives");
  await page.locator("#tip-table button").first().click();
  check((await page.locator("#rank-label").textContent()).startsWith("genus"), "genus drill-down");
  await page.locator("#tip-table button").first().click();
  check((await page.locator("#rank-label").textContent()).startsWith("species"), "species drill-down");
  check((await page.locator("#selected-summary").textContent()).includes("2 direct record vectors"),
    "records clearly distinguished from representatives");
  await page.locator("#tip-table button").first().click();
  check(await page.locator("#empty-view").isVisible(), "honest record endpoint");
  check(!(await page.locator("#specimens").isVisible()), "record endpoint hides old tree");
  await page.click("#up");
  check((await page.locator("#rank-label").textContent()).startsWith("species"), "upward step");
  await page.locator("#breadcrumbs button").filter({hasText: "Lepidoptera"}).click();
  check((await page.locator("#selected-label").textContent()) === "Lepidoptera", "breadcrumb");
  await page.fill("#search", "no-such-taxon");
  check((await page.locator("#search-results").textContent()).includes("No matching"), "empty search");
  await page.locator("#search").press("Escape");
  await page.fill("#search", "Family C");
  await page.locator("#search").press("ArrowDown");
  await page.keyboard.press("Enter");
  check((await page.locator("#selected-label").textContent()) === "Family C", "keyboard search");
  await page.selectOption("#export-method", "medoid");
  const selectedDownload = page.waitForEvent("download");
  await page.click("#download-selected");
  check((await selectedDownload).suggestedFilename().startsWith("medoid-taxon-"), "selected export");
  const fullDownload = page.waitForEvent("download");
  await page.click("#download-full");
  check((await fullDownload).suggestedFilename() === "medoid-full-48.nwk", "full export");
  const provenanceDownload = page.waitForEvent("download");
  await page.click("#download-provenance");
  check((await provenanceDownload).suggestedFilename() === "merging-provenance.json", "ledger export");
  await page.setViewportSize({width: 390, height: 844});
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    "no page-level overflow at mobile width");
  await page.emulateMedia({reducedMotion: "reduce"});
  check(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches),
    "reduced-motion mode");
  await page.setViewportSize({width: 1440, height: 1100});
  await page.locator("#breadcrumbs button").filter({hasText: "Lepidoptera"}).click();
  await page.selectOption("#view-mode", "topology");
  check(errors.length === 0, "no browser errors: " + errors.join("; "));
  return {passed: true, methods: 5, assertions: "navigation, keyboard, search, scales, three downloads, mobile, reduced motion", errors};
};

if (require.main === module) {
  const fs = require("node:fs"), path = require("node:path");
  const artifacts = path.join(__dirname, `.explorer-browser-${process.pid}`);
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
      const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
      if (!process.argv[2]) throw new Error("Pass the URL of the served synthetic explorer fixture");
      await page.goto(process.argv[2], {waitUntil: "networkidle"});
      console.log(JSON.stringify(await module.exports(page)));
    } finally {
      if (browser) await browser.close();
      fs.rmSync(artifacts, {recursive: true, force: true});
    }
  })().catch(error => { console.error(error); process.exitCode = 1; });
}
