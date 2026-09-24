/* Conversation history and versioned ADK report artifacts. */
const artifactCards = new Map();
function resetArtifacts() {
  artifactCards.clear();
  $("#artifact-dialog").close();
  $("#artifact-frame").src = "about:blank";
}
function artifactURL(item, download = false) {
  return `/api/sessions/${encodeURIComponent(session)}/artifacts/${encodeURIComponent(item.filename)}?version=${item.version}&persona=${encodeURIComponent($("#role").value)}&download=${download}`;
}
function receiveArtifact(item) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,149}\.pdf$/.test(item.filename) || !Number.isInteger(item.version)) return;
  const key = `${item.filename}:${item.version}`;
  if (artifactCards.has(key)) return;
  const card = document.createElement("div"); card.className = "artifact-card";
  const title = document.createElement("strong"); title.textContent = "End-of-day report";
  const detail = document.createElement("span"); detail.textContent = `PDF · Version ${item.version + 1}`;
  const preview = document.createElement("button"); preview.type = "button"; preview.textContent = "View report";
  // Capture the session URL now so an old card cannot point to a new conversation.
  const url = artifactURL(item);
  preview.onclick = () => {
    $("#artifact-frame").src = url;
    $("#artifact-dialog").showModal();
  };
  card.append(title, detail, preview); log.appendChild(card); artifactCards.set(key, card);
}
async function refreshHistory() {
  const persona = $("#role").value;
  const response = await fetch(`/api/sessions?persona=${encodeURIComponent(persona)}`);
  if (!response.ok) throw new Error("Conversation history could not be loaded.");
  const data = await response.json();
  if (persona !== $("#role").value) return;
  const box = $("#history"); box.replaceChildren();
  for (const item of data.sessions || []) {
    const button = document.createElement("button"); button.type = "button";
    button.textContent = item.title; button.className = "history-item";
    button.onclick = () => restoreConversation(item.session_id, persona).catch(reportError);
    box.appendChild(button);
  }
}
async function restoreConversation(id, persona) {
  if (busy || persona !== $("#role").value) return;
  setBusy(true);
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(id)}?persona=${encodeURIComponent(persona)}`);
    if (!response.ok) throw new Error("Conversation could not be loaded.");
    const data = await response.json();
    resetConversation(); session = id; hasConversation = true; log.replaceChildren();
    for (const event of data.events) {
      if (["user", "observation"].includes(event.type)) {
        add(event.type === "user" ? "user" : "session", event.type === "user" ? "You" : "Store event", event.text);
        newTurn(event.text); beginTrace(event.text);
      }
      else if (event.type === "error") step("Previous request", "", "code", `<p>${esc(event.message)}</p>`);
      else handle(event);
    }
    sessionState = data.state; renderState();
    nextActions = data.state["ui:next_actions"] || []; drawPrompts();
    $("#conversation-title").textContent = data.state["ui:conversation_title"] || "Store assistant";
    finishTrace();
  } finally { setBusy(false); }
}
document.addEventListener("DOMContentLoaded", () => {
  $("#artifact-close").onclick = () => $("#artifact-dialog").close();
  $("#artifact-dialog").addEventListener("close", () => { $("#artifact-frame").src = "about:blank"; });
});

let notificationsEnabled = false, notificationTimer = null, eventRequest = null;
function configureWorkspace(capabilities) {
  notificationsEnabled = Boolean(capabilities.notifications);
  clearTimeout(notificationTimer);
}
function notificationError(error) {
  $("#notifications-status").textContent = "Alerts could not be refreshed. Open alerts to try again.";
}
async function refreshNotifications() {
  clearTimeout(notificationTimer);
  const persona = $("#role").value;
  $("#notifications-open").hidden = !notificationsEnabled || persona !== "manager";
  if (!notificationsEnabled || persona !== "manager") {
    $("#notifications-list").replaceChildren();
    $("#notifications-dialog").close();
    return;
  }
  const response = await fetch(`/api/notifications?persona=${encodeURIComponent(persona)}`);
  if (!response.ok) throw new Error("Alerts could not be loaded.");
  const data = await response.json();
  if (persona !== $("#role").value) return;
  const items = data.notifications || [], unread = items.filter(n => n.status === "completed" && !n.read_at).length;
  $("#notification-count").textContent = unread; $("#notification-count").hidden = unread === 0;
  $("#notifications-open").setAttribute("aria-label", `Store alerts${unread ? `, ${unread} unread` : ""}`);
  const list = $("#notifications-list"); list.replaceChildren();
  for (const item of items) {
    const card = document.createElement("article"); card.className = "notification-card";
    const title = document.createElement("strong"); title.textContent = item.title;
    const detail = document.createElement("p");
    detail.textContent = item.status === "completed" ? item.summary : item.status === "failed" ? "The check could not finish. Run a new pickup check to retry." : "Checking pickup priorities…";
    card.append(title, detail);
    if (item.status === "completed" && item.analysis_session_id) {
      const open = document.createElement("button"); open.type = "button"; open.textContent = "Open conversation";
      open.onclick = async () => {
        if (busy) return;
        try {
          await restoreConversation(item.analysis_session_id, persona);
          await api(`/api/notifications/${encodeURIComponent(item.job_id)}/read?persona=${encodeURIComponent(persona)}`, {});
          $("#notifications-dialog").close(); await refreshNotifications(); await refreshHistory();
        } catch (error) { notificationError(error); }
      };
      card.appendChild(open);
    }
    list.appendChild(card);
  }
  if (!items.length) $("#notifications-status").textContent = "No alerts yet.";
  else $("#notifications-status").textContent = "";
  const pending = items.some(n => ["queued", "processing"].includes(n.status));
  notificationTimer = setTimeout(() => refreshNotifications().catch(notificationError), pending ? 4000 : 30000);
}
async function triggerPickupEvent() {
  if (busy) return;
  setBusy(true); $("#notifications-status").textContent = "Starting pickup check…";
  try {
    if (!session) await newSession("Pickup check");
    // A retry of the same uncertain submission reuses its idempotency key.
    if (!eventRequest || eventRequest.session !== session) eventRequest = {id: crypto.randomUUID(), session};
    await api("/api/events", {session_id: session, persona: $("#role").value, request_id: eventRequest.id});
    eventRequest = null;
    await refreshNotifications();
  } catch (error) { $("#notifications-status").textContent = "The pickup check could not be started. Try again."; }
  finally { setBusy(false); }
}
document.addEventListener("DOMContentLoaded", () => {
  $("#notifications-open").onclick = () => { $("#notifications-dialog").showModal(); refreshNotifications().catch(notificationError); };
  $("#notifications-close").onclick = () => $("#notifications-dialog").close();
  $("#trigger-event").onclick = triggerPickupEvent;
});
