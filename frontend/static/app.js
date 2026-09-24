
const $ = (s) => document.querySelector(s);
const log = $("#log"), stream = $("#stream"), stateEl = $("#state");
let session = null, userId = "guest", sessionState = {}, scenarios = [], active = null, turn = null;

/* What each tool is, in the room's words. Titles only: the tables below are built from whatever the tool
   actually returned, so the agent is never changed to feed this page. */
const TOOL_TITLES = {
  get_end_of_day_metrics: "Completed-day performance", create_end_of_day_dashboard: "Create end-of-day report",
  remember_work_preference: "Save preference", recall_work_preferences: "Saved preferences",
  describe_store_data: "Available store data", query_store_data: "Query store records",
  get_store_inventory_summary: "Whole-store inventory", list_store_inventory: "Browse inventory",
  get_pickup_workload: "Pickup workload and deadlines", get_inventory_context: "Stock and pickup context",
  report_my_task_blocker: "Report a task blocker", get_loss_reconciliation: "Loss and inventory reconciliation",
  get_my_work: "My assigned work", complete_my_task: "Complete my task", get_stock_location: "Stock locations",
  get_coverage_requirements: "Coverage requirements and breaks", get_merchandising_work: "Merchandising directives",
  get_loss_controls: "Loss-control checks", get_coaching_context: "Dated picking activity",
  get_learning_options: "Learning options", get_guest_product_options: "Guest product options",
  identify_demo_user: "Who is signed in", workshop_clock: "The store clock",
  get_osa_exceptions: "On-shelf exceptions", check_store_stock: "Stock at this store",
  find_nearby_stock: "Stock nearby", get_bopis_demand: "Pickup orders waiting",
  get_replenishment_status: "Replenishment", get_task_status: "Open tasks",
  get_shift_roster: "Who is on shift", get_traffic_and_backlog: "Traffic and backlog",
  get_shrink_signals: "Shrink signals", get_sales_pattern: "Sales pattern",
  get_task_history: "Task history", get_guest_feedback: "Guest feedback",
  get_coaching_signals: "Coaching signals", create_store_task: "Create a task",
  delegate_task: "Delegate a task", search_products: "Products", get_product_details: "Product detail",
  daily_briefing: "The start-of-day briefing", inventory_excellence: "Inventory consultant",
  associate_orchestration: "Coverage consultant", loss_prevention: "Loss prevention consultant",
  store_tasks: "The task agent", policy_lookup: "Store procedures",
};
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let busy = false, activityCount = 0, waitingEl = null, nextActions = [];
let hasConversation = false;
let starterPrompts = [];

function selectStarterPrompts(scenario, random = Math.random) {
  const sample = (complexity, count) => {
    const pool = (scenario?.prompts || []).filter(prompt => prompt.complexity === complexity);
    for (let index = 0; index < Math.min(count, pool.length); index++) {
      const chosen = index + Math.floor(random() * (pool.length - index));
      [pool[index], pool[chosen]] = [pool[chosen], pool[index]];
    }
    return pool.slice(0, count);
  };
  return [...sample("standard", 2), ...sample("complex", 1)];
}
const AGENTS = new Set(["daily_briefing", "inventory_excellence", "associate_orchestration", "loss_prevention", "store_tasks", "associate_development"]);
const friendlyAgent = name => ({store_manager_agent: "Store coordinator", associate_development: "Associate development", inventory_excellence: "Inventory excellence", associate_orchestration: "Team coverage", loss_prevention: "Loss prevention", store_tasks: "Task management"}[name] || name.replaceAll("_", " "));
const localTime = new Intl.DateTimeFormat("en-US", {timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"});
function readableText(value) {
  return String(value).replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})\b/g,
    stamp => { const date = new Date(stamp); return Number.isNaN(date.getTime()) ? stamp : localTime.format(date); });
}
function readableValue(value) {
  if (Array.isArray(value)) return value.map(readableValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, readableValue(item)]));
  return typeof value === "string" ? readableText(value) : value;
}
const displayValue = value => typeof value === "object" ? JSON.stringify(readableValue(value)) : readableText(value);
const userKey = "cymbal-browser-user";
userId = sessionStorage.getItem(userKey) || crypto.randomUUID();
sessionStorage.setItem(userKey, userId);
async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { const err = new Error(await r.text()); err.status = r.status; throw err; }
  return r;
}
function markdown(text) {
  text = readableText(text);
  const inline = t => esc(t).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*([^*]+)\*/g, "<em>$1</em>");
  let html = "", list = "";
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const match = line.match(/^\s*(?:([-*])|\d+[.)])\s+(.+)/);
    const type = match ? (match[1] ? "ul" : "ol") : "";
    if (list && list !== type) { html += `</${list}>`; list = ""; }
    if (match) { if (!list) { list = type; html += `<${list}>`; } html += `<li>${inline(match[2])}</li>`; }
    else if (line.trim() && !/^---+$/.test(line)) html += `<p>${inline(line.replace(/^#{1,6}\s+/, ""))}</p>`;
  }
  return html + (list ? `</${list}>` : "");
}
function add(kind, who, text) {
  log.querySelector(".welcome")?.remove();
  const d = document.createElement("div"); d.className = "msg " + kind;
  d.innerHTML = `<div class="who">${esc(who)}</div><div class="message-body">${kind === "user" ? esc(text) : markdown(text)}</div>`;
  log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
}
function renderState() {
  const visible = Object.fromEntries(Object.entries(sessionState).filter(([key]) => !key.startsWith("ui:")));
  stateEl.textContent = JSON.stringify(visible, null, 2);
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll("#send, #new-session, #role, .scenario, #guide button, #trigger-event, .confirm button").forEach(b => b.disabled = value || b.dataset.locked === "true");
  $("#text").disabled = value;
  $("#connection").textContent = value ? "Working…" : "";
}
function reportError(err) {
  nextActions = []; drawPrompts();
  finishTrace(true);
  const message = err.status === 401 ? "Your session has expired. Refresh to sign in again." : "The request could not be completed. Check the conversation before trying again.";
  $("#request-error").textContent = message; $("#request-error").hidden = false;
  step("Request error", "", "code", `<div class="err">${esc(err.message)}</div>`);
}
/* ---- "How it worked": one card per question, one expandable row per thing the agent did ---- */
function newTurn(question) {
  const d = document.createElement("div"); d.className = "turn";
  d.innerHTML = `<div class="head"><span class="q"></span></div>`;
  d.querySelector(".q").textContent = question;
  stream.prepend(d); turn = d; return d;
}
function step(name, by, kind, bodyHtml) {
  if (!turn) newTurn("(before the first question)");
  const d = document.createElement("details"); d.className = "step";
  d.innerHTML = `<summary><span class="kind ${kind}">${esc(kind)}</span>`
    + `<span class="name">${esc(name)}</span><span class="by">${esc(by ? friendlyAgent(by) : "")}</span></summary>`
    + `<div class="body">${bodyHtml}</div>`;
  turn.appendChild(d); $("#activity-count").textContent = ++activityCount; return d;
}

/* A result is rendered from its own shape: a list of records becomes a table, a flat record becomes a
   definition list, anything else falls back to the raw JSON. Nothing here knows a tool's fields. */
function renderResult(data) {
  if (data == null) return `<div class="empty">nothing returned</div>`;
  data = readableValue(data);
  if (data.status === "ERROR" || data.error) return `<div class="err">${esc(data.error || data.message || "the tool reported an error")}</div>`;
  const rows = Object.entries(data).find(([, v]) => Array.isArray(v) && v.length && typeof v[0] === "object");
  const scalars = Object.entries(data).filter(([, v]) => v === null || typeof v !== "object");
  let html = "";
  if (scalars.length) {
    html += `<dl class="res">` + scalars.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v === null ? "—" : v)}</dd>`).join("") + `</dl>`;
  }
  if (rows) {
    const [key, list] = rows;
    const cols = [...new Set(list.flatMap(r => Object.keys(r)))].slice(0, 6);
    html += `<table class="res"><caption class="empty" style="text-align:left;padding:6px 0">${esc(key)} · ${list.length}</caption><tr>`
      + cols.map(c => `<th>${esc(c)}</th>`).join("") + `</tr>`
      + list.slice(0, 8).map(r => `<tr>` + cols.map(c => `<td>${esc(r[c] === undefined || r[c] === null ? "" : (typeof r[c] === "object" ? JSON.stringify(r[c]) : r[c]))}</td>`).join("") + `</tr>`).join("")
      + `</table>`;
    if (list.length > 8) html += `<div class="empty">${list.length - 8} more…</div>`;
  }
  const others = Object.entries(data).filter(([k, v]) => v && typeof v === "object" && (!rows || k !== rows[0]));
  if (others.length) html += `<div class="raw">${esc(JSON.stringify(Object.fromEntries(others), null, 1))}</div>`;
  return html || `<div class="raw">${esc(JSON.stringify(data, null, 1))}</div>`;
}

function welcome() {
  const d = document.createElement("div"); d.className = "welcome";
  d.innerHTML = `<span class="eyebrow">Naperville</span><h2>${esc(active?.title || "What needs your attention?")}</h2><p>${esc(active?.situation || "Review your store’s priorities, plan coverage, or check a product.")}</p>`;
  log.appendChild(d);
}
function resetConversation() {
  resetTrace();
  resetReports();
  resetArtifacts();
  session = null; sessionState = {}; nextActions = []; hasConversation = false; pending.clear(); renderState();
  starterPrompts = selectStarterPrompts(active);
  log.replaceChildren(); stream.replaceChildren(); turn = null; activityCount = 0;
  $("#activity-count").textContent = "0"; $("#request-error").hidden = true;
  $("#text").value = ""; $("#text").style.height = "auto";
  $("#conversation-title").textContent = active?.title || "Store assistant";
  welcome(); drawPrompts();
}
async function newSession(title = "Store conversation") {
  const r = await api("/api/sessions", {title, demo_identity: $("#role").value});
  const j = await r.json(); session = j.session_id; sessionState = {...j.state}; renderState();
}
async function consume(resp) {
  const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "", complete = false;
  try {
    while (true) {
      const {value, done} = await reader.read();
      buf += done ? dec.decode() : dec.decode(value, {stream: true});
      let m;
      while ((m = /\r?\n\r?\n/.exec(buf))) {
        const frame = buf.slice(0, m.index); buf = buf.slice(m.index + m[0].length);
        const payload = frame.split(/\r?\n/).filter(l => l.startsWith("data:")).map(l => l.slice(5).trimStart()).join("\n");
        if (!payload) continue;
        const event = JSON.parse(payload);
        if (event.type === "done") complete = true;
        handle(event);
      }
      if (done) break;
    }
    if (!complete) throw new Error("The response stream ended before completion.");
  } finally { reader.releaseLock(); }
}
const pending = new Map();
function updateWaiting() {
  if (!waitingEl) return;
  const names = [...pending.values()].map(p => p.name);
  const status = {daily_briefing: "Preparing opening priorities…", inventory_excellence: "Checking stock and pickup demand…",
    associate_orchestration: "Checking team coverage…", loss_prevention: "Reviewing loss signals…",
    get_coaching_signals: "Checking coaching signals…", get_coaching_context: "Reviewing recent picking activity…",
    get_my_work: "Checking your assigned work…", get_learning_options: "Checking learning options…",
    store_tasks: "Reviewing the task…"};
  const name = names.find(n => status[n]);
  waitingEl.querySelector("span").textContent = name ? status[name] : names.length ? `Checking ${String(TOOL_TITLES[names[0]] || names[0]).toLowerCase()}…` : "Preparing your answer…";
}
function handle(e) {
  if (e.type === "text") {
    if (e.partial) return;
    add("agent", "Store assistant", e.text);
  } else if (e.type === "agent_note") {
    if (!e.partial) step("Specialist response", e.author, "Agent", markdown(e.text));
  } else if (e.type === "tool_call") {
    const name = TOOL_TITLES[e.name] || e.name;
    const row = step(name, e.author, AGENTS.has(e.name) ? "Agent call" : "Tool call",
      `<div class="args">${esc(e.name)}(${esc(displayValue(e.args || {}))})</div><p class="call-status">Running…</p>`);
    pending.set(e.call_id || e.name, {name: e.name, args: e.args, author: e.author, row});
    updateWaiting();
  } else if (e.type === "tool_result") {
    const key = e.call_id || e.name, p = pending.get(key); pending.delete(key);
    if (p) p.row.querySelector(".call-status").outerHTML = renderResult(e.data);
    else step(TOOL_TITLES[e.name] || e.name, e.author, AGENTS.has(e.name) ? "Agent result" : "Tool result", renderResult(e.data));
    updateWaiting();
  } else if (e.type === "transfer") {
    step("Agent handoff", e.from, "Handoff", `<p>${esc(friendlyAgent(e.from))} → ${esc(friendlyAgent(e.to))}</p>`);
  } else if (e.type === "state") {
    Object.assign(sessionState, e.delta); renderState();
    if (Array.isArray(e.delta["ui:next_actions"])) { nextActions = e.delta["ui:next_actions"]; drawPrompts(); }
    if (e.delta["ui:report"]) receiveReport(e.delta["ui:report"]);
  } else if (e.type === "trace") receiveTrace(e);
  else if (e.type === "artifact") receiveArtifact(e);
  else if (e.type === "confirmation") showConfirmation(e);
  else if (e.type === "error") throw new Error(e.message);
}
function showConfirmation(e) {
  const box = document.createElement("div"); box.className = "confirm";
  const preference = e.tool === "remember_work_preference";
  box.innerHTML = `<strong>${preference ? "Review preference" : "Review task"}</strong><p>${esc(readableText(e.hint || TOOL_TITLES[e.tool] || "Review the proposed action."))}</p><dl>${Object.entries(e.args || {}).filter(([k]) => !["idempotency_key", "task_key"].includes(k)).map(([k,v]) => `<dt>${esc(k.replaceAll("_", " "))}</dt><dd>${esc(displayValue(v))}</dd>`).join("")}</dl><div class="btns"><button class="primary" type="button">Approve</button><button type="button">Cancel</button></div><p class="confirmation-status" role="status"></p>`;
  const [ok, no] = box.querySelectorAll("button");
  const answer = async confirmed => {
    if (busy) return;
    nextActions = []; drawPrompts();
    setBusy(true); $("#request-error").hidden = true;
    const decision = confirmed ? (preference ? "Save preference" : "Approve task") : "Cancel";
    newTurn(decision); beginTrace(decision);
    // Lock this decision once submitted; an interrupted stream may already have committed the write.
    ok.dataset.locked = no.dataset.locked = "true";
    box.querySelector(".confirmation-status").textContent = "Submitting decision…";
    try {
      await consume(await api("/api/confirm", {user_id: userId, session_id: session, persona: $("#role").value, invocation_id: e.invocation_id, fc_id: e.fc_id, confirmed}));
      box.querySelector(".confirmation-status").textContent = confirmed ? "Approval sent." : "Cancellation sent.";
    } catch (err) {
      box.querySelector(".confirmation-status").textContent = "The result could not be confirmed. Ask the assistant to check the task status before trying again.";
      reportError(err);
    } finally { setBusy(false); finishTrace(); }
  };
  ok.onclick = () => answer(true); no.onclick = () => answer(false);
  log.appendChild(box); log.scrollTop = log.scrollHeight;
}
function waiting() {
  const d = document.createElement("div"); d.className = "thinking"; d.setAttribute("role", "status");
  d.innerHTML = '<i></i><i></i><i></i><span>Working…</span>';
  log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
}
async function send(text) {
  if (busy || !text.trim()) return false;
  setBusy(true); $("#request-error").hidden = true; pending.clear();
  hasConversation = true; nextActions = []; drawPrompts();
  beginTrace(text);
  add("user", "You", text); newTurn(text); waitingEl = waiting();
  try {
    if (!session) await newSession(text);
    await consume(await api("/api/chat", {user_id: userId, session_id: session, persona: $("#role").value, text}));
    return true;
  } catch (err) { reportError(err); return false; }
  finally { refreshHistory().catch(reportError); waitingEl.remove(); waitingEl = null; setBusy(false); finishTrace(); log.scrollTop = log.scrollHeight; }
}
function drawScenarios() {
  const box = $("#scenarios"); box.replaceChildren();
  scenarios.filter(s => s.sign_in === $("#role").value && s.group !== "Guardrails").forEach(s => {
    const b = document.createElement("button"); b.type = "button"; b.className = "scenario";
    b.classList.toggle("on", active === s); b.setAttribute("aria-pressed", String(active === s));
    b.innerHTML = `<span class="row">${esc(s.group ? (s.group === "Roles" ? "R" : "G") : s.sheet_row)}</span><span>${esc(s.title)}</span>`;
    b.onclick = () => { if (busy) return; active = s; resetConversation(); drawScenarios(); };
    box.appendChild(b);
  });
}
function drawPrompts() {
  const guide = $("#guide"); guide.replaceChildren();
  const prompts = nextActions.length ? nextActions : (hasConversation ? [] : starterPrompts);
  prompts.slice(0, 5).forEach(p => {
    const b = document.createElement("button"); b.type = "button";
    b.textContent = p.label || p.say; b.title = p.prompt || p.say; b.disabled = busy;
    b.onclick = () => send(p.prompt || p.say);
    guide.appendChild(b);
  });
}
function selectPersona() {
  active = scenarios.find(s => s.sign_in === $("#role").value && s.group !== "Guardrails") || null;
  resetConversation(); drawScenarios();
  refreshHistory().catch(reportError);
  refreshNotifications().catch(notificationError);
}
async function start() {
  const r = await fetch("/api/config"); if (!r.ok) throw new Error("Cannot load configuration.");
  const cfg = await r.json(); $("#target").textContent = JSON.stringify(cfg.target);
  const gated = cfg.password_required && !cfg.signed_in;
  $("#gate").hidden = !gated; $("#app").inert = gated;
  if (gated) { $("#gate-pw").focus(); return; }
  const response = await fetch("/api/scenarios"); if (!response.ok) throw new Error("Cannot load scenarios.");
  configureWorkspace(cfg.capabilities || {});
  scenarios = (await response.json()).scenarios || [];
  selectPersona(); $("#connection").textContent = "";
}
$("#gate-form").addEventListener("submit", async e => {
  e.preventDefault(); $("#gate-err").textContent = "";
  const button = e.currentTarget.querySelector("button"); button.disabled = true;
  try { await api("/api/login", {password: $("#gate-pw").value}); $("#gate-pw").value = ""; await start(); }
  catch (err) { $("#gate-err").textContent = err.status === 401 ? "Incorrect password. Please try again." : "Unable to connect. Please try again."; }
  finally { button.disabled = false; }
});
$("#form").addEventListener("submit", async e => {
  e.preventDefault(); const text = $("#text").value.trim(); if (!text || busy) return;
  $("#text").value = ""; $("#text").style.height = "auto";
  if (!await send(text)) $("#text").value = text;
  $("#text").focus();
});
$("#text").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#form").requestSubmit(); } });
$("#text").addEventListener("input", e => { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px"; });
$("#new-session").onclick = () => { if (!busy) resetConversation(); };
$("#role").onchange = selectPersona;
function activity(open) { $("#events").hidden = !open; $("#activity-toggle").setAttribute("aria-expanded", String(open)); }
$("#activity-toggle").onclick = () => activity($("#events").hidden);
$("#activity-close").onclick = () => activity(false);
$("#expand").onclick = () => { const on = document.body.classList.toggle("expanded"); $("#expand").textContent = on ? "Tablet view" : "Expand view"; $("#expand").setAttribute("aria-pressed", String(on)); };
start().catch(err => { $("#connection").textContent = "Unable to connect"; reportError(err); });
