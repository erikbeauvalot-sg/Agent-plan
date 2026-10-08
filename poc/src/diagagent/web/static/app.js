// Écran de suivi : l'état des agents est reconstruit uniquement à partir des événements de runs/.
"use strict";

const SIGNALS = { stuckSeconds: 120, loopRepeats: 3, errorStreak: 3, budgetRatio: 0.8 };
const $ = (id) => document.getElementById(id);
let me = null;
let current = null;   // { runId, agents, order, firstTs, lastTs, ended, source, canStop, status }
let clock = null;

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", "X-Diagagent": "1", ...(options.headers || {}) },
  });
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Session expirée"); }
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.detail || `Erreur ${res.status}`);
  return body;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Markdown minimal : titres, listes, gras, code ; les preuves [lead/calls/0001.json] deviennent cliquables.
function md(text) {
  const lines = esc(text || "").split("\n");
  let html = "", inList = false, inCode = false;
  for (const raw of lines) {
    if (raw.startsWith("```")) { html += inCode ? "</pre>" : "<pre>"; inCode = !inCode; continue; }
    if (inCode) { html += raw + "\n"; continue; }
    let line = raw
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[((?:lead|subagents\/[^\]\/]+)\/calls\/\d{4}\.json)\]/g, '<a class="ref" data-ref="$1">[$1]</a>');
    const item = line.match(/^\s*[-*•]\s+(.*)/) || line.match(/^\s*\d+\.\s+(.*)/);
    if (item) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${item[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) html += `<h3>${h[2]}</h3>`;
    else if (line.trim()) html += `<p>${line}</p>`;
  }
  if (inList) html += "</ul>";
  if (inCode) html += "</pre>";
  return html;
}

// ---- Connexion

function showLogin() {
  $("app").hidden = true; $("login").hidden = false;
}

async function boot() {
  try { me = await api("/api/me"); } catch { showLogin(); return; }
  $("login").hidden = true; $("app").hidden = false;
  $("who").textContent = `${me.display_name} · ${me.roles.join(", ")}`;
  $("ask-form").hidden = !me.permissions.includes("ask");
  await loadRuns();
  const fromHash = location.hash.slice(1);
  if (fromHash) openRun(fromHash);
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("login-error").hidden = true;
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ login: f.get("login"), password: f.get("password") }) });
    e.target.reset();
    boot();
  } catch (err) { $("login-error").textContent = err.message; $("login-error").hidden = false; }
});

$("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  closeStream(); showLogin();
});

// ---- Investigations

async function loadRuns() {
  const runs = await api("/api/runs");
  $("runs").innerHTML = runs.map((r) => `
    <li data-id="${esc(r.run_id)}" class="${current?.runId === r.run_id ? "active" : ""}">
      <span class="q">${esc(r.question)}</span>
      <span class="meta"><span class="dot ${esc(r.status)}"></span>${esc(fmtDate(r.started_at))}
        ${me.permissions.includes("view_all") ? "· " + esc(r.user) : ""}</span>
    </li>`).join("") || '<li class="muted">Aucune investigation</li>';
}

$("runs").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) openRun(li.dataset.id);
});

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target, btn = form.querySelector("button");
  btn.disabled = true; $("ask-error").hidden = true;
  try {
    const { run_id } = await api("/api/runs", { method: "POST", body: JSON.stringify({ question: form.question.value }) });
    form.reset();
    await loadRuns();
    openRun(run_id);
  } catch (err) { $("ask-error").textContent = err.message; $("ask-error").hidden = false; }
  finally { btn.disabled = false; }
});

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
}

async function openRun(runId) {
  closeStream();
  location.hash = runId;
  const data = await api(`/api/runs/${runId}`);
  current = { runId, agents: {}, order: [], firstTs: null, lastTs: null, ended: false,
              canStop: data.can_stop, status: data.manifest.status };
  $("empty").hidden = true; $("run").hidden = false; $("drawer").hidden = true;
  $("run-question").textContent = data.manifest.question;
  $("run-meta").textContent = `${fmtDate(data.manifest.started_at)} · ${data.manifest.user} · ${runId}`;
  renderSummary(data);
  document.querySelectorAll("#runs li").forEach((li) => li.classList.toggle("active", li.dataset.id === runId));
  const source = new EventSource(`/api/runs/${runId}/events`);
  current.source = source;
  source.addEventListener("agent", (msg) => { apply(JSON.parse(msg.data)); scheduleRender(); });
  source.addEventListener("end", async () => {
    closeStream();
    current.ended = true;
    renderSummary(await api(`/api/runs/${runId}`));
    render(); loadRuns();
  });
  clock = setInterval(render, 1000);
}

function closeStream() {
  if (current?.source) current.source.close();
  if (clock) clearInterval(clock);
  clock = null;
}

function renderSummary(data) {
  current.canStop = data.can_stop; current.status = data.manifest.status;
  $("run-status").textContent = statusLabel(data.manifest.status);
  $("run-status").className = `pill ${data.manifest.status}`;
  $("stop-run").hidden = !data.can_stop;
  $("answer").innerHTML = data.analysis ? md(data.analysis) : "L'analyse s'affichera ici à la fin de l'investigation.";
  $("answer").classList.toggle("muted", !data.analysis);
  $("plan-box").hidden = !data.plan;
  $("plan").innerHTML = md(data.plan || "");
}

function statusLabel(s) {
  return { running: "en cours", completed: "terminée", partial: "partielle", stopped: "arrêtée", failed: "en échec",
           stopping: "arrêt demandé" }[s] || s;
}

// ---- Réduction des événements en état d'agents

function apply(e) {
  const ts = Date.parse(e.ts);
  current.firstTs ??= ts;
  current.lastTs = ts;
  let a = current.agents[e.agent_id];
  if (!a) {
    a = current.agents[e.agent_id] = { id: e.agent_id, parent: e.parent_id, role: e.agent_id === "lead" ? "principal" : e.agent_id.split("-")[1],
      objective: "", status: "running", start: ts, end: null, last: ts, segs: [], open: {}, toolCalls: 0, maxTools: null,
      errorStreak: 0, repeats: {}, maxRepeat: 0, model: null, tokens: 0 };
    current.order.push(e.agent_id);
  }
  a.last = ts;
  const d = e.data || {};
  switch (e.type) {
    case "agent_spawned": a.objective = d.objective; a.parent = "lead"; break;
    case "agent_started": a.maxTools = d.max_tool_calls; a.start = Math.min(a.start, ts); break;
    case "llm_call_started": a.open.llm = ts; break;
    case "llm_call_ended":
      a.segs.push({ kind: d.error ? "err" : "llm", start: a.open.llm ?? ts, end: ts, label: d.error ? `modèle : ${d.error}` : "modèle" });
      if (d.error) a.model = d.error;
      if (d.usage) a.tokens += (d.usage.input_tokens || 0) + (d.usage.output_tokens || 0);
      break;
    case "tool_call_started": {
      a.open[d.ref] = ts;
      const key = d.tool + JSON.stringify(d.arguments || {});
      a.repeats[key] = (a.repeats[key] || 0) + 1;
      a.maxRepeat = Math.max(a.maxRepeat, a.repeats[key]);
      break;
    }
    case "tool_call_ended":
      a.toolCalls += 1;
      a.errorStreak = d.is_error ? a.errorStreak + 1 : 0;
      a.segs.push({ kind: d.is_error ? "err" : "tool", start: a.open[d.ref] ?? ts, end: ts, label: d.tool, ref: d.ref });
      break;
    case "stop_requested":
      if (d.scope === "agent") a.status = "stopping";
      else Object.values(current.agents).forEach((x) => { if (x.status === "running") x.status = "stopping"; });
      break;
    case "report_submitted": a.report = d.status; break;
    case "agent_ended": a.status = d.status; a.end = ts; break;
    case "run_failed": a.status = "failed"; a.end = ts; break;
  }
}

function signals(a, now) {
  const out = [];
  if (a.status !== "running" && a.status !== "stopping") return out;
  const idle = (now - a.last) / 1000;
  if (idle > SIGNALS.stuckSeconds) out.push({ key: "stuck", text: `bloqué ${Math.round(idle)} s` });
  if (a.maxRepeat >= SIGNALS.loopRepeats) out.push({ key: "loop", text: "boucle" });
  if (a.errorStreak >= SIGNALS.errorStreak) out.push({ key: "errors", text: `${a.errorStreak} erreurs`, bad: true });
  if (a.maxTools && a.toolCalls / a.maxTools > SIGNALS.budgetRatio) out.push({ key: "budget", text: "budget" });
  if (a.model) out.push({ key: "model", text: `modèle : ${a.model}`, bad: true });
  return out;
}

// ---- Rendu

let pending = false;
function scheduleRender() {
  if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; render(); }); }
}

function render() {
  if (!current) return;
  const now = current.ended ? current.lastTs : Math.max(Date.now(), current.lastTs || 0);
  const lead = current.agents.lead;
  const children = current.order.filter((id) => id !== "lead").map((id) => current.agents[id]);
  $("graph").innerHTML = lead
    ? node(lead, now) + (children.length ? `<div class="children">${children.map((c) => node(c, now)).join("")}</div>` : "")
    : '<p class="muted">En attente du premier événement…</p>';
  renderTimeline(now);
}

function node(a, now) {
  const sigs = signals(a, now);
  const pct = a.maxTools ? Math.min(100, Math.round((100 * a.toolCalls) / a.maxTools)) : 0;
  const gauge = pct >= 100 ? "max" : pct > 80 ? "hi" : "";
  const dur = Math.round(((a.end || now) - a.start) / 1000);
  return `<button class="node ${a.status} ${sigs.map((s) => "sig-" + s.key).join(" ")}" data-agent="${esc(a.id)}">
    <span class="name">${esc(a.id === "lead" ? "Agent principal" : a.id)}</span>
    ${a.objective ? `<span class="obj">${esc(a.objective)}</span>` : ""}
    <span class="stats"><span>${esc(statusLabel(a.status))}</span><span>${a.toolCalls}${a.maxTools ? "/" + a.maxTools : ""} outils · ${dur} s</span></span>
    <span class="gauge ${gauge}"><div style="width:${pct}%"></div></span>
    ${sigs.length ? `<span class="badges">${sigs.map((s) => `<span class="badge ${s.bad ? "bad" : ""}">${esc(s.text)}</span>`).join("")}</span>` : ""}
  </button>`;
}

function renderTimeline(now) {
  const t0 = current.firstTs, span = Math.max(1, (current.ended ? current.lastTs : now) - t0);
  const pos = (t) => `${(100 * (t - t0)) / span}%`;
  const width = (a, b) => `${Math.max(0.3, (100 * (b - a)) / span)}%`;
  $("timeline").innerHTML = current.order.map((id) => {
    const a = current.agents[id];
    const segs = a.segs.map((s) => `<span class="seg ${s.kind}" title="${esc(s.label)} · ${((s.end - s.start) / 1000).toFixed(1)} s"
      style="left:${pos(s.start)};width:${width(s.start, s.end)}"></span>`).join("");
    const open = a.status === "running" && a.open.llm && !a.segs.some((s) => s.start === a.open.llm)
      ? `<span class="seg llm" style="left:${pos(a.open.llm)};width:${width(a.open.llm, now)};opacity:.5"></span>` : "";
    return `<div class="tl-row" data-agent="${esc(id)}"><span class="label">${esc(id === "lead" ? "principal" : id)}</span>
      <span class="tl-track"><span class="life" style="left:${pos(a.start)};width:${width(a.start, a.end || now)}"></span>${segs}${open}</span></div>`;
  }).join("");
}

// ---- Détail d'un agent

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-agent]");
  if (el && current) openAgent(el.dataset.agent);
  const ref = e.target.closest("a.ref");
  if (ref) openAgent(ref.dataset.ref.startsWith("lead") ? "lead" : ref.dataset.ref.split("/")[1], ref.dataset.ref);
});

$("d-close").addEventListener("click", () => { $("drawer").hidden = true; });

async function openAgent(agentId, focusRef) {
  const d = await api(`/api/runs/${current.runId}/agents/${agentId}`);
  const a = current.agents[agentId];
  $("d-title").textContent = agentId === "lead" ? "Agent principal" : agentId;
  const canStop = current.canStop && a && (a.status === "running");
  $("d-stop").hidden = !canStop;
  $("d-stop").onclick = () => stopAgent(agentId);
  const report = d.report ? `<section><h2>Rapport</h2><pre>${esc(JSON.stringify(d.report, null, 2))}</pre></section>` : "";
  const prompt = d.prompt || d.system_prompt;
  $("d-body").innerHTML = `
    ${prompt ? `<section><h2>${d.prompt ? "Prompt reçu" : "Prompt système"}</h2><div class="md">${md(prompt)}</div></section>` : ""}
    ${report}
    <section><h2>Appels d'outils (${d.calls.length})</h2>
      ${d.calls.map((c) => `<details class="call ${c.is_error ? "error" : ""}" ${c.ref === focusRef ? "open" : ""} id="call-${esc(c.ref)}">
        <summary><span>${esc(c.tool)} ${c.is_error ? "· erreur" : ""}</span><span class="muted">${c.duration_s} s · ${esc(c.ref)}</span></summary>
        <pre>${esc(JSON.stringify(c.input, null, 2))}</pre><pre>${esc(c.output)}</pre></details>`).join("") || '<p class="muted">Aucun</p>'}
    </section>
    <section><h2>Réponses du modèle (${d.responses.length})</h2>
      ${d.responses.map((r) => `<div class="call"><div class="muted">${esc(fmtDate(r.ts))} · ${esc(r.stop_reason)}
        ${r.tool_calls.length ? "· " + esc(r.tool_calls.join(", ")) : ""}</div>${r.text ? `<div class="md">${md(r.text)}</div>` : ""}</div>`).join("")}
    </section>`;
  $("drawer").hidden = false;
  if (focusRef) document.getElementById(`call-${focusRef}`)?.scrollIntoView({ block: "center" });
}

async function stopAgent(agentId) {
  const label = agentId === "lead" ? "toute l'investigation" : `l'agent ${agentId}`;
  if (!confirm(`Arrêter ${label} ? Les résultats déjà obtenus sont conservés.`)) return;
  try {
    await api(`/api/runs/${current.runId}/agents/${agentId}/stop`, { method: "POST" });
    $("d-stop").hidden = true;
  } catch (err) { alert(err.message); }
}

$("stop-run").addEventListener("click", () => stopAgent("lead"));

boot();
