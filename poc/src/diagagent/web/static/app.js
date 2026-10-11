// Écran de suivi : l'état des agents est reconstruit uniquement à partir des événements de runs/.
"use strict";

const SIGNALS = { stuckSeconds: 120, loopRepeats: 3, errorStreak: 3, budgetRatio: 0.8 };
const $ = (id) => document.getElementById(id);
let me = null;
const can = (permission) => me?.permissions.includes(permission);
let categories = [];
let runsCache = [];
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
  $("ref-time").hidden = !me.reference_time;
  if (me.reference_time) $("ref-time").textContent = `Heure de référence figée : ${fmtDate(me.reference_time)} (UTC ${me.reference_time})`;
  $("ask-form").hidden = !me.permissions.includes("ask");
  $("open-admin").hidden = !["review", "view_indicators", "view_costs", "view_access_log", "view_config", "manage_users"].some(can);
  categories = await api("/api/categories");
  const options = categories.map((c) => `<option value="${esc(c.id)}" title="${esc(c.description)}">${esc(c.id)}</option>`).join("");
  $("runs-filter").innerHTML = '<option value="">Toutes catégories</option>' + options;
  $("cat-select").innerHTML = options;
  $("ask-category").innerHTML = '<option value="">automatique</option>' + options;
  await loadChoices();
  route();
}

// ---- Navigation : #  accueil · #admin  administration · #<run_id>  détail d'une investigation

window.addEventListener("hashchange", route);

function route() {
  if (!me) return;
  const target = location.hash.slice(1);
  if (target === "admin") openAdmin();
  else if (target) { if (current?.runId !== target) openRun(target); }
  else openHome();
}

function showView(name) {
  for (const v of ["home", "run", "admin"]) $(v).hidden = v !== name;
  $("drawer").hidden = true;
  window.scrollTo(0, 0);
}

// ---- Choix du modèle et des données : défaut du serveur, puis dernier choix de ce navigateur

const stored = {
  get(key) { try { return localStorage.getItem(`diagagent.${key}`); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(`diagagent.${key}`, value); } catch { /* stockage indisponible */ } },
};
let profiles = [];   // [{ profile, roles, ok, detail }] une fois /api/status reçu

async function loadChoices() {
  const [models, sources] = await Promise.all([api("/api/models"), api("/api/sources")]);
  profiles = models.profiles.map((p) => ({ profile: p }));
  fillSelect("ask-models", models.profiles.map((p) => ({ value: p, label: p, available: true })),
             stored.get("models"), models.default);
  fillSelect("ask-sources", sources.choices, stored.get("sources"), sources.default);
  renderHint();
}

// Une option indisponible reste visible, grisée, avec la raison.
function fillSelect(id, choices, wanted, fallback) {
  const usable = (v) => choices.some((c) => c.value === v && c.available);
  const value = usable(wanted) ? wanted : usable(fallback) ? fallback : choices.find((c) => c.available)?.value;
  $(id).innerHTML = choices.map((c) => `<option value="${esc(c.value)}"${c.value === value ? " selected" : ""}
    ${c.available ? "" : "disabled"} title="${esc(c.reason || "")}">${esc(c.label)}${c.available ? "" : " — indisponible"}</option>`).join("");
}

function renderHint() {
  const p = profiles.find((x) => x.profile === $("ask-models").value);
  const roles = p?.roles ? Object.entries(p.roles).map(([r, m]) => `${r} ${m}`).join(" · ") : "";
  const src = $("ask-sources").selectedOptions[0]?.title;
  $("ask-hint").textContent = [roles, p && p.ok === false ? `⚠ ${p.detail}` : "", src].filter(Boolean).join(" — ");
}

for (const id of ["ask-models", "ask-sources"]) {
  $(id).addEventListener("change", () => { stored.set(id.slice(4), $(id).value); renderHint(); });
}

// ---- Page d'accueil

let homeTimer = null;
let runsShown = 15;

async function openHome() {
  closeStream(); current = null;
  showView("home");
  loadStatus();
  await Promise.all([loadRuns(), loadStats()]);
  clearInterval(homeTimer);
  // Rafraîchit la liste tant que l'accueil est affiché (investigations en cours, nouvelles investigations).
  homeTimer = setInterval(() => { if (!$("home").hidden) loadRuns(); else clearInterval(homeTimer); }, 5000);
}

async function loadStatus(refresh = false) {
  try {
    const s = await api(`/api/status${refresh ? "?refresh=true" : ""}`);
    profiles = s.models;
    const chosen = $("ask-models").value;
    fillSelect("ask-models", s.models.map((m) => ({ value: m.profile, label: m.profile, available: m.ok, reason: m.detail })),
               chosen || stored.get("models"), s.default_models);
    renderHint();
    $("status").innerHTML = s.models.map((m) => statusItem(m.ok, `Modèles ${m.profile}${m.default ? " (défaut)" : ""}`,
        `${Object.values(m.roles).filter((v, i, a) => a.indexOf(v) === i).join(", ")} · ${m.detail}`)).join("")
      + s.sources.map((x) => statusItem(x.ok, x.name, x.detail, x.configured === false)).join("");
    $("alerts-box").hidden = !s.alerts.length;
    $("alerts").innerHTML = s.alerts.map((a) => `<li>
        <span class="sev ${esc(a.severity)}">${esc(a.severity || "?")}</span>
        <span><strong>${esc(a.alertname)}</strong> ${a.host ? "· " + esc(a.host) : ""}
          <span class="muted">${esc(a.summary || "")} · depuis ${esc(fmtDate(a.starts_at))}</span></span>
        ${can("ask") ? `<button class="link investigate" data-alert="${esc(JSON.stringify(a))}">Investiguer</button>` : ""}
      </li>`).join("");
  } catch (err) {
    $("status").innerHTML = `<li class="error">${esc(err.message)}</li>`;
  }
}

function statusItem(ok, name, detail, off = false) {
  return `<li><span class="dot ${off ? "" : ok ? "completed" : "failed"}"></span><strong>${esc(name)}</strong>
    <span class="muted">${esc(detail)}</span></li>`;
}

$("status-refresh").addEventListener("click", () => loadStatus(true));

// « Investiguer » préremplit la question et choisit les données maison.
$("alerts").addEventListener("click", (e) => {
  const btn = e.target.closest("button.investigate");
  if (!btn) return;
  const a = JSON.parse(btn.dataset.alert);
  $("ask-form").question.value = `Analyse l'alerte ${a.alertname}${a.host ? " sur " + a.host : ""}`
    + `${a.summary ? " (" + a.summary + ")" : ""} : cause probable et actions possibles.`;
  if ([...$("ask-sources").options].some((o) => o.value === "maison" && !o.disabled)) $("ask-sources").value = "maison";
  renderHint();
  $("ask-form").question.focus();
  window.scrollTo(0, 0);
});

const fmtDuration = (s) => (s === null || s === undefined ? "" : s < 60 ? `${Math.round(s)} s`
  : s < 3600 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")}` : `${(s / 3600).toFixed(1)} h`);

async function loadStats() {
  const days = $("stats-days").value, withEval = $("stats-eval").checked;
  const { activity: a, evals } = await api(`/api/home?days=${days}&include_eval=${withEval}`);
  const t = a.today;
  const byModel = Object.entries(t.by_model).map(([m, n]) => `${esc(m)} ${n}`).join(" · ");
  $("today").innerHTML = `
    <div><strong>${t.runs}</strong><span>investigation(s)</span></div>
    <div><strong>${pct(t.success_rate)}</strong><span>terminées avec succès</span></div>
    <div><strong>${fmtTokens(t.tokens)}</strong><span>tokens</span></div>
    <div><strong>${fmtDuration(t.avg_duration_s) || "–"}</strong><span>durée moyenne</span></div>
    ${byModel ? `<p class="muted">${byModel}</p>` : ""}
    ${withEval ? "" : '<p class="muted">hors évaluations</p>'}`;
  $("evals").innerHTML = evals.length ? `<table><thead><tr><th>Modèles</th><th>Réussis</th><th>Durée</th><th>Tokens</th><th>Date</th></tr></thead>
    <tbody>${evals.map((e) => `<tr title="${esc(e.cases_file)} · ${esc(e.file)}"><td>${esc(e.label)}</td>
      <td>${e.passed}/${e.cases}${e.repeat > 1 ? ` <span class="muted">(×${e.repeat})</span>` : ""}</td>
      <td>${fmtDuration(e.duration_s)}</td><td>${fmtTokens(e.tokens)}</td><td>${esc(fmtDate(e.date))}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Aucun rapport. Lancer <code>diagagent --models &lt;profil&gt; eval</code>.</p>';
  const p = a.period;
  $("stats-summary").textContent = `${p.runs} investigation(s) terminée(s) · ${pct(p.success_rate)} avec succès · `
    + `${fmtTokens(p.tokens)} tokens${withEval ? "" : " · hors évaluations"}`;
  // Réussite = terminée « completed » ; partiel = partielle, arrêtée ou précision demandée ; échec = « failed ».
  const statusCells = (s) => `<td>${(s.partial || 0) + (s.stopped || 0) + (s.needs_clarification || 0)}</td><td>${s.failed || 0}</td>`;
  const head = (first, extra = "") => `<thead><tr><th>${first}</th><th>Total</th><th>Réussite</th>
    <th title="partielles, arrêtées ou en attente de précision">Part.</th><th title="échecs">Éch.</th>${extra}</tr></thead>`;
  const empty = '<p class="muted">Aucune investigation sur la période.</p>';
  const name = (n) => (n === "?" ? '<span class="muted">sans catégorie</span>' : esc(n));
  $("stats-categories").innerHTML = a.categories.length ? `<table>${head("Catégorie", "<th>Durée</th>")}<tbody>
    ${a.categories.map((c) => `<tr><td>${name(c.name)}</td><td>${c.runs}</td><td>${rateBar(c.success_rate)}</td>${statusCells(c.statuses)}
      <td>${fmtDuration(c.avg_duration_s)}</td></tr>`).join("")}</tbody></table>` : empty;
  $("stats-agents").innerHTML = a.agents.length ? `<table>${head("Agent")}<tbody>
    ${a.agents.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.runs}</td><td>${rateBar(c.success_rate)}</td>${statusCells(c.statuses)}</tr>`).join("")}
    </tbody></table>` : empty;
  $("stats-models").innerHTML = a.models.length ? `<table>${head("Modèles", "<th>Durée</th><th>Tokens</th>")}<tbody>
    ${a.models.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.runs}</td><td>${rateBar(c.success_rate)}</td>${statusCells(c.statuses)}
      <td>${fmtDuration(c.avg_duration_s)}</td><td>${fmtTokens(c.tokens)}</td></tr>`).join("")}</tbody></table>` : empty;
}

function rateBar(rate) {
  if (rate === null || rate === undefined) return "–";
  const cls = rate >= 0.8 ? "" : rate >= 0.5 ? " hi" : " max";
  return `<span class="rate"><span class="gauge${cls}"><div style="width:${Math.round(rate * 100)}%"></div></span>${pct(rate)}</span>`;
}

$("stats-days").addEventListener("change", loadStats);
$("stats-eval").addEventListener("change", loadStats);

// La connexion est un vrai envoi de formulaire (POST /login puis redirection) : Entrée fonctionne partout et
// le gestionnaire de mots de passe reconnaît la connexion. On garde seulement la page visée (#run_id, #admin).
$("login-form").addEventListener("submit", (e) => {
  e.target.next.value = location.hash.slice(1);
});

// Retour d'un échec de connexion : message, puis adresse nettoyée (la page visée reste dans le #).
if (new URLSearchParams(location.search).has("echec")) {
  $("login-error").textContent = "Identifiant ou mot de passe incorrect (compte verrouillé après 5 échecs)";
  $("login-error").hidden = false;
  history.replaceState(null, "", "/" + location.hash);
}

$("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  closeStream();
  location.replace("/");  // page rechargée : formulaire de connexion vide, aucun état de la session précédente
});

// ---- Investigations

async function loadRuns() {
  runsCache = await api("/api/runs?limit=300");
  renderRuns();
}

function runItem(r) {
  const elapsed = r.status === "running" ? (Date.now() - Date.parse(r.started_at)) / 1000 : r.duration_s;
  return `<li data-id="${esc(r.run_id)}">
      <span class="q">${esc(r.question)}</span>
      <span class="meta"><span class="dot ${esc(r.status)}"></span>${esc(fmtDate(r.started_at))}
        ${r.category ? `<span class="tag">${esc(r.category)}</span>` : ""}
        ${r.label && r.label !== "?" ? `<span class="tag model">${esc(r.label)}</span>` : ""}
        ${elapsed !== null && elapsed !== undefined ? `· ${fmtDuration(elapsed)}` : ""}
        ${r.tokens ? `· ${fmtTokens(r.tokens)} tokens` : ""}
        ${can("view_all") ? "· " + esc(r.user) : ""}</span>
    </li>`;
}

function renderRuns() {
  const live = runsCache.filter((r) => r.status === "running");
  $("live-box").hidden = !live.length;
  $("live").innerHTML = live.map(runItem).join("");
  const filter = $("runs-filter").value, search = $("runs-search").value.trim().toLowerCase();
  const runs = runsCache.filter((r) => r.status !== "running" && (!filter || r.category === filter)
    && (!search || r.question.toLowerCase().includes(search)));
  $("runs").innerHTML = runs.slice(0, runsShown).map(runItem).join("") || '<li class="muted">Aucune investigation</li>';
  $("runs-more").hidden = runs.length <= runsShown;
}

$("runs-filter").addEventListener("change", renderRuns);
$("runs-search").addEventListener("input", renderRuns);
$("runs-more").addEventListener("click", () => { runsShown += 30; renderRuns(); });

for (const id of ["runs", "live"]) {
  $(id).addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) location.hash = li.dataset.id;
  });
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target, btn = form.querySelector("button");
  btn.disabled = true; $("ask-error").hidden = true;
  try {
    await startRun({ question: form.question.value, models: form.models.value || null,
                     sources: form.sources.value || null, category: form.category.value || null,
                     rerun_of: rerunOf });
    form.question.value = "";
    clearRerun();
  } catch (err) { $("ask-error").textContent = err.message; $("ask-error").hidden = false; }
  finally { btn.disabled = false; }
});

// « Relancer… » : nouvelle demande préremplie avec la question et les choix de l'investigation d'origine
// (modèle, données, catégorie imposée ou corrigée), lancée seulement quand l'utilisateur valide.
let rerunOf = null;

function prepareRerun(manifest) {
  const form = $("ask-form"), c = manifest.category || {};
  form.question.value = manifest.question;
  const pick = (id, value) => {
    const ok = [...$(id).options].some((o) => o.value === value && !o.disabled);
    if (ok) $(id).value = value;
    return ok || !value;
  };
  const kept = [pick("ask-models", manifest.models_profile || ""),
                pick("ask-sources", (manifest.sources || []).join(",")),
                pick("ask-category", c.correction?.category || (["user", "requalify"].includes(c.source) ? c.id : ""))];
  rerunOf = manifest.run_id;
  $("ask-rerun-link").textContent = manifest.run_id;
  $("ask-rerun-link").href = `#${manifest.run_id}`;
  $("ask-rerun").hidden = false;
  $("ask-error").hidden = kept.every(Boolean);
  $("ask-error").textContent = "Un choix d'origine n'est plus disponible : l'option par défaut est sélectionnée.";
  renderHint();
  location.hash = "";
  form.question.focus();
  window.scrollTo(0, 0);
}

function clearRerun() {
  rerunOf = null;
  $("ask-rerun").hidden = true;
  $("ask-category").value = "";
}

$("ask-rerun-cancel").addEventListener("click", () => { clearRerun(); $("ask-form").question.value = ""; });

async function startRun(body) {
  const { run_id } = await api("/api/runs", { method: "POST", body: JSON.stringify(body) });
  location.hash = run_id;
}

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
}

async function openRun(runId) {
  closeStream();
  current = { runId };  // évite une seconde ouverture pendant le chargement (hashchange)
  let data;
  try { data = await api(`/api/runs/${runId}`); } catch (err) { alert(err.message); location.hash = ""; return; }
  current = { runId, agents: {}, order: [], firstTs: null, lastTs: null, ended: false,
              canStop: data.can_stop, status: data.manifest.status, modelsProfile: data.manifest.models_profile,
              sources: data.manifest.sources ? data.manifest.sources.join(",") : null };
  showView("run");
  $("run-question").textContent = data.manifest.question;
  // L'heure de référence fixe la période des recherches (« depuis hier soir », 24 h par défaut) : on l'affiche
  // quand elle diffère du lancement, par exemple sur le scénario de démonstration.
  const ref = data.manifest.reference_time, started = data.manifest.started_at;
  const shifted = ref && Math.abs(Date.parse(ref) - Date.parse(started)) > 60_000;
  const sourcesLabel = (data.manifest.sources || []).map((s) => (s === "demo" ? "démo" : s)).join(" + ");
  $("run-meta").textContent = `${fmtDate(started)} · ${data.manifest.user} · ${runId}`
    + (sourcesLabel ? ` · données ${sourcesLabel}` : "")
    + (shifted ? ` · heure de référence ${fmtDate(ref)}` : "");
  if (data.manifest.rerun_of) {
    const link = document.createElement("a");
    link.href = `#${data.manifest.rerun_of}`;
    link.textContent = data.manifest.rerun_of;
    $("run-meta").append(" · relance de ", link);
  }
  renderSummary(data);
  const source = new EventSource(`/api/runs/${runId}/events`);
  current.source = source;
  source.addEventListener("agent", (msg) => { apply(JSON.parse(msg.data)); scheduleRender(); });
  source.addEventListener("end", async () => {
    closeStream();
    current.ended = true;
    renderSummary(await api(`/api/runs/${runId}`));
    render();
  });
  clock = setInterval(render, 1000);
}

function closeStream() {
  if (current?.source) current.source.close();
  if (clock) clearInterval(clock);
  clock = null;
}

function renderSummary(data) {
  current.canStop = data.can_stop; current.status = data.manifest.status; current.canDetails = data.can_details;
  current.models = data.manifest.models; current.usage = data.manifest.usage;
  renderLlm();
  $("run-shared").hidden = !data.manifest.shared;
  $("share-run").hidden = !data.can_share;
  $("share-run").textContent = data.manifest.shared ? "Ne plus partager" : "Partager";
  $("share-run").onclick = async () => {
    await api(`/api/runs/${current.runId}/share`, { method: "POST", body: JSON.stringify({ shared: !data.manifest.shared }) });
    renderSummary(await api(`/api/runs/${current.runId}`));
  };
  $("run-status").textContent = statusLabel(data.manifest.status);
  $("run-status").className = `pill ${data.manifest.status}`;
  $("stop-run").hidden = !data.can_stop;
  $("rerun-run").hidden = !me.permissions.includes("ask");
  $("rerun-run").onclick = () => prepareRerun(data.manifest);
  $("answer").innerHTML = data.analysis ? md(data.analysis) : "L'analyse s'affichera ici à la fin de l'investigation.";
  $("answer").classList.toggle("muted", !data.analysis);
  renderActions(data.actions || [], ENDED.includes(data.manifest.status));
  $("plan-box").hidden = !data.plan;
  $("plan").innerHTML = md(data.plan || "");
  $("precision-form").hidden = !(data.manifest.status === "needs_clarification" && me.permissions.includes("ask"));
  renderCategory(data.manifest);
  renderFeedback(data.manifest);
}

// ---- Avis sur le diagnostic et cas confirmé

const ENDED = ["completed", "partial", "stopped", "failed"];

function renderFeedback(manifest) {
  const f = manifest.feedback;
  const canGive = manifest.user === me.login || me.permissions.includes("stop_all");
  $("feedback-form").hidden = !!f || !canGive || !ENDED.includes(manifest.status);
  $("feedback-done").hidden = !f;
  if (f) $("feedback-done").textContent = `Avis de ${f.by} : ${f.verdict}${f.cause ? " · cause réelle : " + f.cause : ""}`;
}

$("feedback-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { verdict: f.get("verdict"), cause: f.get("cause") || "", create_case: f.get("create_case") === "on" };
  try {
    await api(`/api/runs/${current.runId}/feedback`, { method: "POST", body: JSON.stringify(body) });
    e.target.reset();
    renderSummary(await api(`/api/runs/${current.runId}`));
  } catch (err) { alert(err.message); }
});

// ---- Amélioration continue : indicateurs et propositions

const pct = (x) => (x === null || x === undefined ? "–" : `${Math.round(x * 100)} %`);

async function openAdmin() {
  closeStream(); current = null;
  showView("admin");
  $("review-box").hidden = !can("review");
  if (can("review")) {
    const actions = (await api("/api/actions")).filter((a) => a.status === "proposed");
    $("review").innerHTML = actions.map((a) => actionHtml(a, true)).join("") || '<p class="muted">Aucune action en attente.</p>';
  }
  $("costs-box").hidden = !can("view_costs");
  if (can("view_costs")) {
    const c = await api("/api/costs");
    $("costs").innerHTML = `<p class="muted">Total : ${c.total.runs} investigation(s) · ${c.total.input_tokens} tokens en entrée ·
      ${c.total.output_tokens} en sortie${reasoningNote(c.total.reasoning_tokens)}</p><table><thead><tr><th>Jour</th><th>Utilisateur</th><th>Modèle</th><th>Investigations</th>
      <th>Tokens entrée</th><th>Tokens sortie</th></tr></thead><tbody>${c.rows.map((r) => `<tr><td>${esc(r.day)}</td><td>${esc(r.user)}</td>
      <td>${esc(r.model)}</td><td>${r.runs}</td><td>${r.input_tokens}</td><td>${r.output_tokens}</td></tr>`).join("")}</tbody></table>`;
  }
  $("log-box").hidden = !can("view_access_log");
  if (can("view_access_log")) {
    const log = await api("/api/access-log");
    $("access-log").innerHTML = `<table><thead><tr><th>Date</th><th>Utilisateur</th><th>Action</th><th>Détail</th></tr></thead><tbody>
      ${log.map((e) => { const { ts, user, action, ...rest } = e;
        return `<tr><td>${esc(fmtDate(ts))}</td><td>${esc(user)}</td><td>${esc(action)}</td><td>${esc(JSON.stringify(rest))}</td></tr>`; }).join("")}
      </tbody></table>`;
  }
  $("indicators-box").hidden = !can("view_indicators");
  if (can("view_indicators")) {
    const ind = await api("/api/indicators");
    $("indicators-box").hidden = false;
    const drafts = Object.entries(ind.draft_matches).map(([k, n]) => `${esc(k)} : ${n}`).join(", ");
    $("indicators").innerHTML = `<p class="muted">${ind.runs} investigation(s) hors évaluation · classées autre : ${pct(ind.autre_share)}
      ${drafts ? " · catégories en observation : " + drafts : ""}</p>
      <table><thead><tr><th>Catégorie</th><th>Demandes</th><th>Part</th><th>Corrigées</th><th>Diagnostics justes</th>
      <th>Durée moy.</th><th>Appels d'outils moy.</th></tr></thead><tbody>
      ${ind.categories.map((c) => `<tr><td>${esc(c.category)}</td><td>${c.runs}</td><td>${pct(c.share)}</td>
        <td>${pct(c.corrected_share)}</td><td>${pct(c.useful_share)} <span class="muted">(${c.feedback} avis)</span></td>
        <td>${c.avg_duration_s} s</td><td>${c.avg_tool_calls}</td></tr>`).join("")}</tbody></table>`;
  }
  $("proposals-box").hidden = !(can("review") || can("view_indicators"));
  if (!$("proposals-box").hidden) renderProposals(await api("/api/proposals"));
  $("config-box").hidden = !can("view_config");
  if (can("view_config")) loadConfigList();
  $("users-box").hidden = !can("manage_users");
  if (can("manage_users")) loadUsers();
}

// ---- Configuration : un éditeur par fichier, validé côté passerelle, versionné et tracé

let configFile = null;   // { path, version, content, editable, isNew }

async function loadConfigList() {
  const { files, creatable } = await api("/api/config");
  const groups = {};
  for (const f of files) (groups[f.group] ||= []).push(f);
  $("config-files").innerHTML = Object.entries(groups).map(([g, list]) => `<h3>${esc(g)}</h3><ul>${list.map((f) =>
    `<li><a href="#admin" data-path="${esc(f.path)}" class="${configFile?.path === f.path ? "active" : ""}">${esc(f.path)}</a>
      ${f.editable ? "" : '<span class="muted">lecture</span>'}</li>`).join("")}</ul>`).join("");
  $("config-new").hidden = !creatable.length;
  $("config-create-dir").innerHTML = creatable.map((c) => `<option value="${esc(c.pattern)}">${esc(c.pattern)}</option>`).join("");
}

function configDirty() {
  return configFile && configFile.editable && $("config-text").value !== configFile.content;
}

async function openConfig(path) {
  if (configDirty() && !confirm("Abandonner les modifications non enregistrées ?")) return;
  const f = await api(`/api/config/file?path=${encodeURIComponent(path)}`);
  configFile = { ...f, isNew: false };
  showConfigEditor();
  loadConfigList();
}

function showConfigEditor() {
  const f = configFile;
  $("config-editor").hidden = false;
  $("config-path").textContent = f.isNew ? "Nouveau fichier" : f.path;
  $("config-mode").textContent = f.editable ? "modifiable" : "lecture seule";
  $("config-create").hidden = !f.isNew;
  $("config-text").value = f.content;
  $("config-text").readOnly = !f.editable;
  for (const id of ["config-comment", "config-check", "config-save", "config-reset"]) $(id).hidden = !f.editable;
  $("config-comment").value = "";
  $("config-msg").textContent = "";
  $("config-diff").hidden = true;
  $("config-history-box").hidden = f.isNew;
  if (!f.isNew) loadConfigHistory();
}

async function loadConfigHistory() {
  const list = await api(`/api/config/history?path=${encodeURIComponent(configFile.path)}`);
  $("config-history").innerHTML = list.map((v) => `<li data-id="${esc(v.id)}">
    <span>${esc(fmtDate(v.id.replace(/^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)\d*Z$/, "$1-$2-$3T$4:$5:$6Z")))}</span>
    <strong>${esc(v.author || "origine")}</strong> <span>${esc(v.comment)}</span>
    <button type="button" class="link" data-diff="1">Écart avec l'actuel</button>
    ${configFile.editable ? '<button type="button" class="link" data-restore="1">Reprendre cette version</button>' : ""}
  </li>`).join("") || '<li class="muted">Jamais modifié depuis l\'interface.</li>';
}

function configTarget() {
  if (!configFile.isNew) return configFile.path;
  const dir = $("config-create-dir").value.replace(/\/[^/]*$/, "");
  return `${dir}/${$("config-create-name").value.trim()}`;
}

function configMessage(text, error = false) {
  $("config-msg").textContent = text;
  $("config-msg").className = error ? "error" : "muted";
}

$("config-files").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-path]");
  if (!a) return;
  e.preventDefault();
  openConfig(a.dataset.path).catch((err) => alert(err.message));
});
$("config-new").addEventListener("click", () => {
  if (configDirty() && !confirm("Abandonner les modifications non enregistrées ?")) return;
  configFile = { path: "", version: null, content: "", editable: true, isNew: true };
  showConfigEditor();
  $("config-create-name").focus();
});
$("config-reset").addEventListener("click", () => { $("config-text").value = configFile.content; configMessage(""); });
$("config-check").addEventListener("click", async () => {
  try {
    const r = await api("/api/config/validate", { method: "POST",
      body: JSON.stringify({ path: configTarget(), content: $("config-text").value }) });
    configMessage(r.ok ? "Fichier valide." : r.error, !r.ok);
  } catch (err) { configMessage(err.message, true); }
});
$("config-save").addEventListener("click", async () => {
  try {
    const path = configTarget();
    const saved = await api("/api/config/file", { method: "POST", body: JSON.stringify({ path,
      content: $("config-text").value, version: configFile.version, comment: $("config-comment").value }) });
    configFile = { ...configFile, path, isNew: false, version: saved.version, content: $("config-text").value };
    showConfigEditor();
    configMessage("Enregistré. Les prochaines investigations utiliseront cette version.");
    loadConfigList();
  } catch (err) { configMessage(err.message, true); }
});
$("config-history").addEventListener("click", async (e) => {
  const li = e.target.closest("li[data-id]");
  if (!li) return;
  try {
    const v = await api(`/api/config/version?path=${encodeURIComponent(configFile.path)}&id=${encodeURIComponent(li.dataset.id)}`);
    if (e.target.dataset.diff) {
      $("config-diff").hidden = false;
      $("config-diff").textContent = v.diff || "Identique au fichier actuel.";
    } else if (e.target.dataset.restore) {
      $("config-text").value = v.content;
      $("config-comment").value = `Retour à la version du ${li.querySelector("span").textContent}`;
      configMessage("Version reprise dans l'éditeur : vérifie puis enregistre pour la rétablir.");
    }
  } catch (err) { configMessage(err.message, true); }
});
window.addEventListener("beforeunload", (e) => { if (configDirty()) e.preventDefault(); });

// ---- Comptes

const ROLE_NAMES = ["lecteur", "operateur", "superviseur", "administrateur", "auditeur"];

function roleBoxes(selected = []) {
  return ROLE_NAMES.map((r) => `<label class="check"><input type="checkbox" value="${r}" ${selected.includes(r) ? "checked" : ""}> ${r}</label>`).join(" ");
}

async function loadUsers() {
  const list = await api("/api/users");
  $("user-new-roles").innerHTML = roleBoxes(["operateur"]);
  $("users").innerHTML = `<table><thead><tr><th>Identifiant</th><th>Nom</th><th>Rôles</th><th>État</th><th></th></tr></thead><tbody>
    ${list.map((u) => `<tr data-id="${esc(u.id)}"><td>${esc(u.login)}</td><td>${esc(u.display_name)}</td>
      <td class="roles">${roleBoxes(u.roles)} <button type="button" class="link" data-roles="1">Enregistrer les rôles</button></td>
      <td>${u.status === "active" ? "actif" : "désactivé"}${u.locked_until ? ` <span class="muted">(verrouillé jusqu'à ${esc(fmtDate(u.locked_until))})</span>` : ""}</td>
      <td><button type="button" class="link" data-status="${u.status === "active" ? "disabled" : "active"}">${u.status === "active" ? "Désactiver" : "Réactiver"}</button>
        <button type="button" class="link" data-password="1">Nouveau mot de passe…</button></td></tr>`).join("")}</tbody></table>`;
}

function usersMessage(text, error = false) {
  $("users-msg").textContent = text;
  $("users-msg").className = error ? "error" : "muted";
}

$("users").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  const row = e.target.closest("tr[data-id]");
  if (!btn || !row) return;
  let body = null;
  if (btn.dataset.roles) body = { roles: [...row.querySelectorAll(".roles input:checked")].map((i) => i.value) };
  else if (btn.dataset.status) body = { status: btn.dataset.status };
  else if (btn.dataset.password) {
    const password = prompt("Nouveau mot de passe (12 caractères minimum) :");
    if (!password) return;
    body = { password };
  }
  try {
    await api(`/api/users/${row.dataset.id}`, { method: "POST", body: JSON.stringify(body) });
    usersMessage("Compte mis à jour.");
    loadUsers();
  } catch (err) { usersMessage(err.message, true); }
});
$("user-new").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await api("/api/users", { method: "POST", body: JSON.stringify({ login: form.login.value, display_name: form.display_name.value || null,
      roles: [...$("user-new-roles").querySelectorAll("input:checked")].map((i) => i.value), password: form.password.value }) });
    form.reset();
    usersMessage("Compte créé.");
    loadUsers();
  } catch (err) { usersMessage(err.message, true); }
});

const KINDS = { add_examples: "ajout d'exemples", add_hypotheses: "ajout d'hypothèses", update_description: "nouvelle description",
                new_category: "nouvelle catégorie (en observation)", activate: "activation d'une catégorie" };

function renderProposals(list) {
  const canReview = me.permissions.includes("review");
  $("proposals").innerHTML = list.map((p) => {
    const r = p.replay;
    const replay = r ? `rejeu de la catégorisation : ${r.before} → ${r.after} / ${r.cases} ${r.ok ? "" : "(dégradation, écartée)"}` : "non rejouée";
    const decision = p.decision ? `· ${esc(p.status)} par ${esc(p.decision.by)}${p.decision.comment ? " : " + esc(p.decision.comment) : ""}` : "";
    return `<article class="action">
      <header><strong>${esc(KINDS[p.kind] || p.kind)} · ${esc(p.target)}</strong><span class="pill ${esc(p.status)}">${esc(p.status)}</span></header>
      <p>${esc(p.rationale)}</p>
      <p class="muted">${esc(replay)} ${decision} · preuves : ${(p.evidence || []).map(esc).join(", ") || "–"}</p>
      <details><summary>Changement proposé</summary><pre>${esc(JSON.stringify(p.change, null, 2))}</pre></details>
      ${canReview && p.status === "pending" ? `<div class="decide" data-id="${esc(p.id)}">
        <input placeholder="Commentaire (facultatif)"><button data-accept="1" class="primary">Accepter</button>
        <button data-accept="0">Rejeter</button></div>` : ""}
    </article>`;
  }).join("") || '<p class="muted">Aucune proposition. Lancer <code>diagagent learn</code> pour en produire.</p>';
}

$("proposals").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-accept]");
  if (!btn) return;
  const box = btn.closest(".decide");
  try {
    await api(`/api/proposals/${box.dataset.id}/decision`, { method: "POST",
      body: JSON.stringify({ accept: btn.dataset.accept === "1", comment: box.querySelector("input").value }) });
    openAdmin();
  } catch (err) { alert(err.message); }
});


// ---- Catégorie de la demande : affichée, corrigeable, relançable

const MODES = { playbook: "playbook appliqué", combined: "deux playbooks combinés", clarify: "précision demandée",
                generic: "stratégie générique" };
const CONFIDENCE = { low: "faible", medium: "moyenne", high: "élevée" };

function renderCategory(manifest) {
  const c = manifest.category;
  $("run-category").hidden = !c;
  if (!c) return;
  const playbooks = Object.entries(c.playbooks || {}).map(([id, v]) => `${id} v${v}`).join(" + ");
  $("cat-label").innerHTML = `Catégorie <span class="tag strong">${esc(c.correction?.category || c.id)}</span>`;
  const parts = [`confiance ${CONFIDENCE[c.confidence] || c.confidence}`, MODES[c.mode] || c.mode];
  if (playbooks) parts.push(playbooks);
  if (c.source === "user") parts.push("choisie par l'utilisateur");
  if (c.history?.length) parts.push(`requalifiée depuis ${c.history.map((h) => h.from).join(", ")}`);
  if (c.correction) parts.push(`corrigée par ${c.correction.by} (classée ${c.id})`);
  if (c.error) parts.push(`classifieur : ${c.error}`);
  $("cat-detail").textContent = "· " + parts.join(" · ");
  $("cat-edit").hidden = !(manifest.user === me.login || me.permissions.includes("stop_all"));
  $("cat-rerun").hidden = !me.permissions.includes("ask");
  $("cat-select").value = c.correction?.category || c.id;
}

$("cat-edit").addEventListener("click", () => { $("cat-form").hidden = false; $("cat-edit").hidden = true; });
$("cat-cancel").addEventListener("click", () => { $("cat-form").hidden = true; $("cat-edit").hidden = false; });
$("cat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api(`/api/runs/${current.runId}/category`, { method: "POST", body: JSON.stringify({ category: $("cat-select").value }) });
    $("cat-form").hidden = true;
    renderSummary(await api(`/api/runs/${current.runId}`));
  } catch (err) { alert(err.message); }
});
$("cat-rerun").addEventListener("click", async () => {
  const category = $("cat-select").value;
  try {
    await api(`/api/runs/${current.runId}/category`, { method: "POST", body: JSON.stringify({ category }) });
    await startRun({ question: $("run-question").textContent, category, models: current.modelsProfile,
                     sources: current.sources, rerun_of: current.runId });
  } catch (err) { alert(err.message); }
});
$("precision-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const precision = e.target.precision.value.trim();
  try {
    // La relance garde les modèles et les sources de l'investigation d'origine.
    await startRun({ question: `${$("run-question").textContent}\nPrécision : ${precision}`,
                     models: current.modelsProfile, sources: current.sources, rerun_of: current.runId });
    e.target.reset();
  } catch (err) { alert(err.message); }
});

const ACTION_STATUS = { proposed: "à valider", validated: "validée, non exécutée", rejected: "rejetée" };

function actionHtml(a, reviewable) {
  const decision = a.decision ? ` · ${esc(ACTION_STATUS[a.status])} par ${esc(a.decision.by)}${a.decision.comment ? " : " + esc(a.decision.comment) : ""}` : "";
  return `
    <article class="action">
      <header><strong>${esc(a.id)} · ${esc(a.title)}</strong><span class="risk ${esc(a.risk)}">risque ${esc(a.risk)}</span></header>
      ${a.question ? `<p class="muted"><a class="run-link" data-run="${esc(a.run_id)}">${esc(a.question)}</a></p>` : ""}
      <p class="muted">${esc(ACTION_STATUS[a.status] || a.status)}${decision}</p>
      <p class="muted">${esc(a.type)} · ${esc(a.target)}${a.requires_change ? " · passe par un changement" : ""}</p>
      <div class="md">${md(a.rationale)}</div>
      <p class="refs">${(a.evidence || []).map((r) => md(`[${r}]`).replace(/<\/?p>/g, "")).join(" ")}</p>
      <details><summary>Procédure et retour arrière</summary>
        <div class="md">${md(a.procedure)}</div><h3>Retour arrière</h3><div class="md">${md(a.rollback)}</div>
        ${a.risk_explanation ? `<p class="muted">${esc(a.risk_explanation)}</p>` : ""}</details>
      ${reviewable && a.status === "proposed" ? `<div class="decide-action" data-run="${esc(a.run_id)}" data-id="${esc(a.id)}">
        <input placeholder="Commentaire (facultatif)"><button data-accept="1" class="primary">Valider</button>
        <button data-accept="0">Rejeter</button></div>` : ""}
    </article>`;
}

function renderActions(actions, ended) {
  $("actions-box").hidden = !actions.length;
  $("actions").innerHTML = actions.map((a) => actionHtml({ ...a, run_id: current.runId }, ended && can("review"))).join("");
}

document.addEventListener("click", async (e) => {
  const link = e.target.closest(".run-link");
  if (link) { location.hash = link.dataset.run; return; }
  const btn = e.target.closest(".decide-action button[data-accept]");
  if (!btn) return;
  const box = btn.closest(".decide-action");
  try {
    await api(`/api/runs/${box.dataset.run}/actions/${box.dataset.id}/decision`, { method: "POST",
      body: JSON.stringify({ accept: btn.dataset.accept === "1", comment: box.querySelector("input").value }) });
    if (!$("admin").hidden) openAdmin(); else renderSummary(await api(`/api/runs/${current.runId}`));
  } catch (err) { alert(err.message); }
});

function statusLabel(s) {
  return { running: "en cours", completed: "terminée", partial: "partielle", stopped: "arrêtée", failed: "en échec",
           stopping: "arrêt demandé", needs_clarification: "précision demandée" }[s] || s;
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
    case "agent_started":
      a.maxTools = d.max_tool_calls; a.start = Math.min(a.start, ts);
      if (d.model) a.llm = `${d.provider} / ${d.model}`;
      break;
    case "llm_call_started": a.open.llm = ts; break;
    case "llm_call_ended":
      a.segs.push({ kind: d.error ? "err" : "llm", start: a.open.llm ?? ts, end: ts, label: d.error ? `modèle : ${d.error}` : `modèle ${d.model || ""}` });
      if (d.error) a.model = d.error;
      if (d.usage) addUsage(a, d.usage);
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
    case "action_proposed": scheduleSummary(); break;
    case "agent_ended": a.status = d.status; a.end = ts; break;
    case "classification_started": a.open.cls = ts; break;
    case "request_classified":
      // La classification apparaît comme un appel au modèle de l'agent principal ; une demande de précision
      // termine l'investigation sans lancer l'agent.
      if (a.open.cls) a.segs.push({ kind: "llm", start: a.open.cls, end: ts, label: `classification : ${d.id}` });
      if (d.usage) { current.classifier = { tokensIn: 0, tokensOut: 0, tokens: 0 }; addUsage(current.classifier, d.usage); }
      if (d.mode === "clarify") { a.status = "needs_clarification"; a.end = ts; }
      scheduleSummary(); break;
    case "category_changed": scheduleSummary(); break;
    case "run_failed": a.status = "failed"; a.end = ts; break;
  }
}

function addUsage(target, usage) {
  target.tokensIn = (target.tokensIn || 0) + (usage.input_tokens || 0);
  target.tokensOut = (target.tokensOut || 0) + (usage.output_tokens || 0);
  target.tokensReasoning = (target.tokensReasoning || 0) + (usage.reasoning_tokens || 0);
  target.tokens = target.tokensIn + target.tokensOut;
}

// Le raisonnement est inclus dans la sortie : on le précise seulement quand le fournisseur le compte.
const reasoningNote = (n) => (n ? `, dont ${n.toLocaleString("fr-FR")} de raisonnement` : "");

const fmtTokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)} k` : String(n || 0));

// Fournisseur et modèle par rôle, et tokens consommés : relus du manifest, et comptés en direct à partir des
// événements pendant l'investigation.
function renderLlm() {
  if (!current) return;
  const models = current.models || {};
  const label = { lead: "principal", classifier: "classifieur" };
  const roles = Object.entries(models).map(([role, m]) => `${label[role] || role} ${m.provider} / ${m.model}`);
  const agents = Object.values(current.agents);
  const live = [...agents, current.classifier || {}];
  const tin = live.reduce((s, a) => s + (a.tokensIn || 0), 0), tout = live.reduce((s, a) => s + (a.tokensOut || 0), 0);
  const treas = live.reduce((s, a) => s + (a.tokensReasoning || 0), 0);
  const usage = current.ended && current.usage ? current.usage
    : { input_tokens: tin, output_tokens: tout, reasoning_tokens: treas };
  const total = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  $("run-llm").textContent = (roles.length ? `LLM : ${roles.join(" · ")} — ` : "")
    + `${total.toLocaleString("fr-FR")} tokens (${(usage.input_tokens || 0).toLocaleString("fr-FR")} en entrée, `
    + `${(usage.output_tokens || 0).toLocaleString("fr-FR")} en sortie${reasoningNote(usage.reasoning_tokens)})`;
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

let summaryTimer = null;
function scheduleSummary() {
  clearTimeout(summaryTimer);
  const runId = current.runId;
  summaryTimer = setTimeout(async () => {
    if (current?.runId === runId) renderSummary(await api(`/api/runs/${runId}`));
  }, 300);
}

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
  renderLlm();
}

function node(a, now) {
  const sigs = signals(a, now);
  const pct = a.maxTools ? Math.min(100, Math.round((100 * a.toolCalls) / a.maxTools)) : 0;
  const gauge = pct >= 100 ? "max" : pct > 80 ? "hi" : "";
  const dur = Math.round(((a.end || now) - a.start) / 1000);
  return `<button class="node ${a.status} ${sigs.map((s) => "sig-" + s.key).join(" ")}" data-agent="${esc(a.id)}">
    <span class="name">${esc(a.id === "lead" ? "Agent principal" : a.id)}</span>
    ${a.objective ? `<span class="obj">${esc(a.objective)}</span>` : ""}
    <span class="stats"><span>${esc(statusLabel(a.status))}</span><span>${a.toolCalls}${a.maxTools ? "/" + a.maxTools : ""} outils · ${dur} s · ${fmtTokens(a.tokens)} tokens</span></span>
    ${a.llm ? `<span class="llm-name">${esc(a.llm)}</span>` : ""}
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
  const a = current.agents[agentId];
  $("d-title").textContent = agentId === "lead" ? "Agent principal" : agentId;
  if (!current.canDetails) {
    $("d-stop").hidden = true;
    $("d-body").innerHTML = '<p class="muted">Prompts, échanges avec le modèle et appels d\'outils ne sont pas visibles pour votre rôle.</p>';
    $("drawer").hidden = false;
    return;
  }
  const d = await api(`/api/runs/${current.runId}/agents/${agentId}`);
  const canStop = current.canStop && a && (a.status === "running");
  $("d-stop").hidden = !canStop;
  $("d-stop").onclick = () => stopAgent(agentId);
  const report = d.report ? `<section><h2>Rapport</h2><pre>${esc(JSON.stringify(d.report, null, 2))}</pre></section>` : "";
  const prompt = d.prompt || d.system_prompt;
  const usage = a ? `<p class="muted">${a.llm ? esc(a.llm) + " · " : ""}${(a.tokensIn || 0).toLocaleString("fr-FR")} tokens en entrée,
    ${(a.tokensOut || 0).toLocaleString("fr-FR")} en sortie${reasoningNote(a.tokensReasoning)}</p>` : "";
  $("d-body").innerHTML = `
    ${usage}
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
