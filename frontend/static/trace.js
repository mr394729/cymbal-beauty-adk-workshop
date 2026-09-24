/* Execution spans are supplied by ADK. No progress, branches or durations are inferred. */
const traceState = {spans: new Map(), question: "", receiving: false, failed: false, rootInvocationId: null};
const traceDialog = document.querySelector("#trace-dialog");
let traceOpener = null, traceFrame = null;
const traceEscape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const traceNumber = value => typeof value === "number" && Number.isFinite(value);
const traceDuration = value => !traceNumber(value) ? "—" : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(value < 10000 ? 2 : 1)} s`;

function beginTrace(question, append = false) {
  if (!append) { traceState.spans.clear(); traceState.rootInvocationId = null; }
  traceState.question = question || traceState.question;
  traceState.receiving = true; traceState.failed = false; scheduleTrace();
}
function finishTrace(failed = traceState.failed) {
  traceState.receiving = false; traceState.failed = failed; scheduleTrace();
}
function resetTrace() {
  traceState.spans.clear(); traceState.question = ""; traceState.receiving = false; traceState.failed = false; traceState.rootInvocationId = null;
  if (traceDialog.open) traceDialog.close();
  scheduleTrace();
}
function receiveTrace(event) {
  const root = event.root_invocation_id || event.spans?.find(s => s?.root_invocation_id)?.root_invocation_id;
  if (root && traceState.rootInvocationId && root !== traceState.rootInvocationId) return;
  if (root) traceState.rootInvocationId = root;
  for (const span of event.spans || []) {
    if (!span || typeof span.id !== "string" || !["agent", "tool", "model"].includes(span.kind)) continue;
    if (span.root_invocation_id && traceState.rootInvocationId && span.root_invocation_id !== traceState.rootInvocationId) continue;
    traceState.spans.set(span.id, {...traceState.spans.get(span.id), ...span});
  }
  scheduleTrace();
}
function scheduleTrace() {
  if (traceFrame !== null) return;
  traceFrame = requestAnimationFrame(() => { traceFrame = null; if (traceDialog.open) renderTrace(); });
}
function traceRows() {
  const list = [...traceState.spans.values()];
  const children = new Map(), roots = [];
  const sort = (a, b) => (a.start_ms || 0) - (b.start_ms || 0) || a.id.localeCompare(b.id);
  for (const span of list) {
    if (span.parent_id && span.parent_id !== span.id && traceState.spans.has(span.parent_id)) {
      if (!children.has(span.parent_id)) children.set(span.parent_id, []);
      children.get(span.parent_id).push(span);
    } else roots.push(span);
  }
  const rows = [], seen = new Set();
  const visit = (span, depth) => {
    if (seen.has(span.id)) return;
    seen.add(span.id); rows.push({span, depth});
    for (const child of (children.get(span.id) || []).sort(sort)) visit(child, depth + 1);
  };
  roots.sort(sort).forEach(span => visit(span, 0));
  list.sort(sort).forEach(span => visit(span, 0)); // Retain malformed-cycle/orphan records without inventing parents.
  return rows;
}
function renderTrace() {
  const container = document.querySelector("#trace-spans");
  const opened = new Set([...container.querySelectorAll("details[open]")].map(e => e.dataset.span));
  const focused = document.activeElement?.closest("details[data-span]")?.dataset.span;
  const rows = traceRows(), timed = rows.map(r => r.span).filter(s => traceNumber(s.start_ms));
  const start = timed.length ? Math.min(...timed.map(s => s.start_ms)) : 0;
  const end = timed.length ? Math.max(...timed.map(s => s.start_ms + (traceNumber(s.duration_ms) ? Math.max(0, s.duration_ms) : 0))) : start;
  const windowMs = Math.max(end - start, 1);
  document.querySelector("#trace-question").textContent = traceState.question || "No conversation yet.";
  const status = document.querySelector("#trace-status");
  status.textContent = !rows.length ? (traceState.receiving ? "Waiting for recorded execution spans…" : traceState.question ? "No execution spans were returned for this turn." : "Send a message to record a turn.") : `${rows.length} recorded spans${timed.length ? ` · Recorded window ${traceDuration(end - start)}` : ""}${traceState.receiving ? " · Receiving updates…" : traceState.failed ? " · Request interrupted" : ""}`;
  container.replaceChildren();
  for (const {span, depth} of rows) {
    const details = document.createElement("details"); details.className = "trace-span"; details.dataset.span = span.id;
    details.open = opened.has(span.id);
    const offset = traceNumber(span.start_ms) ? span.start_ms - start : null;
    const duration = traceNumber(span.duration_ms) ? Math.max(span.duration_ms, 0) : null;
    const left = offset === null ? 0 : Math.min(100, Math.max(0, offset / windowMs * 100));
    const width = duration === null ? 0 : Math.min(100 - left, duration / windowMs * 100);
    const statusLabel = span.status || "Status unavailable";
    const label = `${span.name || span.agent || span.id} · ${span.kind} · ${statusLabel}`;
    const title = offset === null ? "Start time unavailable" : `Started +${traceDuration(offset)}${duration === null ? "; duration not yet recorded" : `; duration ${traceDuration(duration)}`}`;
    const bar = offset === null ? "" : `<i class="trace-bar trace-${traceEscape(span.kind)}" style="left:${left}%;width:${width}%;min-width:${duration === null ? 2 : 3}px"></i>`;
    details.innerHTML = `<summary aria-label="${traceEscape(label)}"><span class="trace-operation" style="padding-left:${Math.min(depth, 8) * 16}px"><span class="trace-kind">${traceEscape(span.kind)}</span><strong>${traceEscape(span.name || span.agent || span.id)}</strong><small>${traceEscape(statusLabel)}</small></span><span class="trace-track" title="${traceEscape(title)}">${bar}</span><span class="trace-duration">${duration === null ? (span.status === "running" ? "Running" : "—") : traceDuration(duration)}</span></summary><div class="trace-detail"><dl><dt>Agent</dt><dd>${traceEscape(span.agent || "—")}</dd><dt>Timing</dt><dd>${traceEscape(title)}</dd><dt>Invocation</dt><dd>${traceEscape(span.invocation_id || "—")}</dd><dt>Span</dt><dd>${traceEscape(span.id)}</dd>${span.parent_id ? `<dt>Parent</dt><dd>${traceEscape(span.parent_id)}</dd>` : ""}</dl></div>`;
    const detail = details.querySelector(".trace-detail");
    for (const key of ["input", "output"]) {
      if (span[key] === undefined || span[key] === null) continue;
      const heading = document.createElement("h3"); heading.textContent = key === "input" ? "Input" : "Output";
      const pre = document.createElement("pre"); pre.textContent = typeof span[key] === "string" ? span[key] : JSON.stringify(span[key], null, 2);
      detail.append(heading, pre);
    }
    container.appendChild(details);
  }
  if (focused) [...container.children].find(e => e.dataset.span === focused)?.querySelector("summary").focus({preventScroll: true});
}
document.querySelector("#view-trace").onclick = () => {
  traceOpener = document.activeElement; renderTrace(); traceDialog.showModal(); document.querySelector("#trace-close").focus();
};
document.querySelector("#trace-close").onclick = () => traceDialog.close();
traceDialog.addEventListener("close", () => { if (traceOpener?.isConnected) traceOpener.focus({preventScroll: true}); });
traceDialog.addEventListener("click", event => { if (event.target === traceDialog) {
  const r = traceDialog.getBoundingClientRect();
  if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) traceDialog.close();
} });
