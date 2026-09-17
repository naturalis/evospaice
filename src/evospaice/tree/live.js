"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let source = null, selected = 0, active = null, pending = false;
  let polling = false, pollFailures = 0;
  const controls = ["clade-search", "backend", "max-children"];
  const methodInputs = () => [...$("method-options").querySelectorAll("input")];
  const selectedMethods = () => methodInputs().filter(input => input.checked).map(input => input.value);

  function message(text, style = "") {
    $("job-status").textContent = text;
    $("job-status").className = style;
    $("job-status").setAttribute("role", style === "error" ? "alert" : "status");
  }
  function lock() {
    const busy = Boolean(active || pending);
    controls.forEach(id => { $(id).disabled = busy || !source?.ready; });
    methodInputs().forEach(input => { input.disabled = busy || !source?.ready; });
    ["select-all", "clear-methods"].forEach(id => { $(id).disabled = busy || !source?.ready; });
    const count = selectedMethods().length;
    $("method-count").textContent = count ? `${count} of ${methodInputs().length} selected` :
      "Select at least one method to run.";
    $("run").disabled = busy || !source?.ready || !count;
    $("refresh").disabled = busy || !source;
    $("cancel").disabled = !active;
    $("run").textContent = busy ? "Working…" : "Run merges";
  }
  function clearResult() {
    $("result").hidden = true;
    $("result").removeAttribute("src");
    $("empty").hidden = false;
    $("empty").textContent = "Selection changed. Press Run merges to rebuild these descendants.";
  }
  async function api(path, body) {
    const options = {cache: "no-store", signal: AbortSignal.timeout(15000)};
    if (body !== undefined) Object.assign(options, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Live-Token": source.csrfToken},
      body: JSON.stringify(body),
    });
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
    return result;
  }
  function path(id) {
    const parts = [];
    for (let index = id; index > 0; index = source.taxa[index].parent) {
      parts.unshift(source.taxa[index].label);
    }
    return parts;
  }
  function choose(id) {
    selected = id;
    const taxon = source.taxa[id];
    $("scope").textContent = `${path(id).join(" / ") || "Complete cohort"} · ${taxon.records.toLocaleString()} records`;
    $("clade-search").value = taxon.label;
    $("clade-results").replaceChildren();
    $("clade-search").setAttribute("aria-expanded", "false");
    clearResult();
  }
  function search() {
    const query = $("clade-search").value.trim().toLocaleLowerCase();
    const results = $("clade-results");
    results.replaceChildren();
    const matches = source.taxa.map((taxon, id) => ({taxon, id})).filter(({taxon, id}) =>
      taxon.rank !== "record" && (!query || path(id).join(" / ").toLocaleLowerCase().includes(query) ||
      taxon.label.toLocaleLowerCase().includes(query)));
    const note = document.createElement("p");
    note.textContent = matches.length ? `${matches.length} matches${matches.length > 40 ? " · first 40; refine your search" : ""}` :
      "No matching clade. Try a shorter label.";
    results.append(note);
    for (const {taxon, id} of matches.slice(0, 40)) {
      const button = document.createElement("button");
      button.textContent = `${path(id).join(" / ") || taxon.label} · ${taxon.rank} · ${taxon.records.toLocaleString()} records`;
      button.onclick = () => choose(id);
      results.append(button);
    }
    $("clade-search").setAttribute("aria-expanded", "true");
  }
  async function loadSource() {
    const previous = source?.generation;
    source = await api("/api/source");
    if (!methodInputs().length) {
      for (const [key, method] of Object.entries(source.methods)) {
        const label = document.createElement("label");
        label.className = "method-option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.id = `method-${key}`;
        input.value = key;
        input.checked = true;
        input.onchange = () => { clearResult(); lock(); };
        const copy = document.createElement("span");
        copy.className = "method-copy";
        const title = document.createElement("strong");
        title.textContent = method.label;
        const units = document.createElement("span");
        units.textContent = method.units;
        units.id = `${input.id}-units`;
        input.setAttribute("aria-describedby", units.id);
        copy.append(title, units);
        label.append(input, copy);
        $("method-options").append(label);
      }
    }
    $("source-ledger").textContent = JSON.stringify(source.source, null, 2);
    $("source-title").textContent = source.ready ?
      `${source.records.toLocaleString()} records × ${source.dimensions} dimensions · verified` :
      "Azure data not loaded";
    $("source-loaded").textContent = source.ready ?
      `Last loaded ${source.source.loadedUtc || "from synthetic test fixture"} · memory only` :
      "Refresh Azure data to authenticate and verify the configured cohort.";
    if (source.ready && previous !== source.generation) choose(0);
    lock();
    return source.activeJob;
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      while (active) {
        const job = await api(`/api/jobs/${active}`);
        pollFailures = 0;
        message(job.progress, "busy");
        if (job.status !== "running") {
          active = null;
          await loadSource();
          if (job.status === "succeeded" && job.kind === "compute") {
            $("result").src = job.viewUrl;
            $("result").hidden = false;
            $("empty").hidden = true;
            message(`Newly computed · ${job.records.toLocaleString()} records · ${job.seconds.toFixed(2)} s · not cached`);
          } else if (job.status === "succeeded") {
            message(`Azure data refreshed and verified · ${job.records.toLocaleString()} records. Choose methods and Run merges.`);
          } else {
            message(job.error, job.status === "failed" ? "error" : "");
          }
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 400));
      }
    } catch (error) {
      if (++pollFailures <= 5 && active) {
        message(`${error.message}. Reconnecting to the job; it is still bounded by the server timeout.`, "error");
        setTimeout(poll, 2000);
      } else {
        active = null;
        if (source) source.ready = false;
        message(`${error.message}. Could not reconnect. Reload this page when the local service is available.`, "error");
      }
    } finally {
      polling = false;
      lock();
    }
  }
  async function start(kind) {
    if (active || pending) return;
    pending = true;
    lock();
    clearResult();
    try {
      let body = {};
      if (kind === "compute") {
        const methods = selectedMethods();
        body = {generation: source.generation, path: path(selected), methods,
          backend: $("backend").value, maxChildren: Number($("max-children").value)};
      }
      const job = await api(kind === "refresh" ? "/api/refresh" : "/api/jobs", body);
      active = job.id;
      if (kind === "refresh") {
        source.ready = false;
        $("source-title").textContent = "Reloading and verifying Azure data";
        $("source-loaded").textContent = "Previous snapshot invalidated; waiting for a verified replacement.";
      }
      message(job.progress, "busy");
    } catch (error) {
      message(error.message, "error");
      // A timed-out POST may have been accepted. Reattach rather than enqueue a duplicate.
      try { active = await loadSource(); } catch { /* Keep the original actionable error. */ }
    } finally {
      pending = false;
      lock();
    }
    if (active) void poll();
  }
  $("run").onclick = () => start("compute");
  $("select-all").onclick = () => {
    methodInputs().forEach(input => { input.checked = true; });
    clearResult();
    lock();
  };
  $("clear-methods").onclick = () => {
    methodInputs().forEach(input => { input.checked = false; });
    clearResult();
    lock();
  };
  $("refresh").onclick = () => start("refresh");
  $("cancel").onclick = async () => {
    try {
      if (active) await api(`/api/jobs/${active}/cancel`, {});
    } catch (error) { message(error.message, "error"); }
  };
  controls.forEach(id => { $(id).onchange = clearResult; });
  $("clade-search").oninput = search;
  $("clade-search").onfocus = () => { if (source?.ready) search(); };
  $("clade-search").onkeydown = event => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      $("clade-results").querySelector("button")?.focus();
    }
    if (event.key === "Escape") {
      $("clade-results").replaceChildren();
      $("clade-search").setAttribute("aria-expanded", "false");
    }
  };
  document.addEventListener("click", event => {
    if (!event.target.closest(".search")) {
      $("clade-results").replaceChildren();
      $("clade-search").setAttribute("aria-expanded", "false");
    }
  });
  $("result").onload = () => {
    const frame = $("result");
    if (!frame.hidden && frame.contentDocument) {
      frame.style.height = `${frame.contentDocument.documentElement.scrollHeight + 30}px`;
    }
  };
  lock();
  loadSource().then(id => {
    active = id;
    lock();
    if (id) void poll();
    else message(source.ready ? "Verified Azure data is ready. Choose methods and Run merges." :
      "Refresh Azure data to begin.");
  }).catch(error => message(`${error.message}. Reload this page when the local service is running.`, "error"));
})();
