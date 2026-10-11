import asyncio
import json

from diagagent import checks, cli
from diagagent.llm.scripted import ScriptedProvider
from test_actions_eval import ACTION
from test_agent import _load_with_runs
from test_orchestrator import answer, by_role, call, tools

REF = "subagents/T04-system-xdocker/calls/0003.json"
WS = "lead/calls/0007.json"
PEAKS = {"radarr": {"mb": 1020.3, "ref": REF, "working_set_mb": 1020.3, "working_set_ref": WS},
         "jellyfin": {"mb": 803.7, "ref": REF, "working_set_mb": 650.0, "working_set_ref": WS},
         "seerr": {"mb": 440.3, "ref": REF, "working_set_mb": 440.3, "working_set_ref": WS},
         "qbittorrent": {"mb": 8534.9, "ref": REF}}


def _call(path, tool, output):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tool": tool, "output": output}))


def test_measured_peaks_separate_working_set_from_cache(tmp_path):
    _call(tmp_path / "subagents" / "T01-system-x" / "calls" / "0001.json", "container_memory",
          {"containers": [{"container": "radarr", "mem_mb": 569.7, "peak_mb": 1020.3},
                          {"container": "seerr", "mem_mb": 291.6, "peak_mb": None}]})
    _call(tmp_path / "lead" / "calls" / "0002.json", "container_metrics",
          {"metric": "container.mem_mb", "containers": [{"container": "radarr", "summary": {"max": 539.0}},
                                                         {"container": "seerr", "summary": {"max": 310.0}}]})
    _call(tmp_path / "lead" / "calls" / "0003.json", "container_metrics",
          {"metric": "container.swap_mb", "containers": [{"container": "seerr", "summary": {"max": 9999}}]})
    peaks = checks.measured_peaks(tmp_path)
    assert peaks == {
        "radarr": {"mb": 1020.3, "ref": "subagents/T01-system-x/calls/0001.json",
                   "working_set_mb": 539.0, "working_set_ref": "lead/calls/0002.json"},
        "seerr": {"mb": 310.0, "ref": "lead/calls/0002.json",
                  "working_set_mb": 310.0, "working_set_ref": "lead/calls/0002.json"}}


def test_memory_limit_below_measured_peak_is_refused():
    action = {"title": "Limiter la mémoire de jellyfin et radarr", "target": "xdocker",
              "procedure": "Set memory limits for jellyfin and radarr containers to 1.0 GB each, adding "
                           "`--memory=1g --memory-swap=1g` to the compose file."}
    error = checks.check_memory_limit(action, PEAKS, 1.2)
    assert "radarr : limite 1024 Mo, pic de mémoire de travail 1020 Mo [lead/calls/0007.json]" in error
    assert "minimum 1224 Mo" in error and "jellyfin" not in error and error.count("radarr :") == 1
    assert checks.check_memory_limit({**action, "procedure": "docker update --memory=2g radarr"}, PEAKS, 1.2) is None


def test_memory_limit_applies_to_the_container_named_with_it():
    procedure = "services:\n  radarr:\n    mem_limit: 1500m\n  seerr:\n    mem_limit: 600m\n"
    assert checks.check_memory_limit({"title": "Limites", "target": "xdocker", "procedure": procedure},
                                     PEAKS, 1.2) is None
    error = checks.check_memory_limit({"title": "Limites", "target": "xdocker",
                                       "procedure": procedure.replace("600m", "400m")}, PEAKS, 1.2)
    assert error.startswith("Limite mémoire sous le pic") and "seerr : limite 400 Mo" in error and "radarr" not in error


def test_memory_limit_needs_a_working_set_measure():
    # peak_mb de qbittorrent (8,5 Go) est surtout du cache de fichiers : il ne justifie aucune limite.
    action = {"title": "Limiter qbittorrent", "target": "xdocker", "procedure": "docker update --memory=11500m qbittorrent"}
    error = checks.check_memory_limit(action, PEAKS, 1.2)
    assert "sans pic de mémoire de travail mesuré pour qbittorrent" in error and "container_metrics" in error
    assert "le conteneur visé" in checks.check_memory_limit(
        {**action, "procedure": "deploy.resources.limits.memory: 2G"}, {}, 1.2)
    assert checks.check_memory_limit({**action, "procedure": "Redémarrer radarr"}, {}, 1.2) is None


class FakeProm:
    def __init__(self, series, rules):
        self.series, self.rules = series, rules

    def instant(self, promql):
        if promql.rstrip().endswith("<"):
            raise ValueError('http://prom a répondu 400 : {"error":"parse error: unexpected end of input"}')
        if promql.startswith("count({__name__="):
            return [{"value": 1}] if promql.split('"')[1] in self.series else []
        return []

    def get(self, path, params):
        return {"groups": [{"rules": [{"name": n, "query": q} for n, q in self.rules.items()]}]}


CURRENT = "(node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / node_memory_SwapTotal_bytes * 100 > 50"
PROM = FakeProm({"node_memory_SwapTotal_bytes", "node_memory_SwapFree_bytes", "node_vmstat_pswpin"},
                {"SwapUsageHigh": CURRENT})


def test_proposed_rules_are_read_from_yaml_or_lines():
    procedure = ("Modifier la règle :\n```yaml\n- alert: SwapUsageHigh\n  expr: rate(node_vmstat_pswpin[5m]) > 100\n"
                 "  for: 15m\n```\nPuis recharger Prometheus.")
    assert checks.proposed_rules(procedure) == [{"alert": "SwapUsageHigh", "expr": "rate(node_vmstat_pswpin[5m]) > 100"}]
    assert checks.proposed_rules("alert: Foo, expr: `up == 0`") == [{"alert": "Foo", "expr": "up == 0"}]
    assert checks.proposed_rules("Redémarrer le conteneur") == []


def test_quoted_current_rule_is_not_checked_as_the_proposal():
    # Procédure réelle de gpt-oss : la règle actuelle citée, puis la nouvelle.
    procedure = (f"Modify the 'SwapUsageHigh' rule:\n- Current:\n```\n- expr: {CURRENT}\n- for: 10m\n```\n"
                 "- Proposed:\n```\n- alert: SwapUsageHigh\n  expr: (\n    (node_memory_SwapTotal_bytes - "
                 "node_memory_SwapFree_bytes) / node_memory_SwapTotal_bytes * 100 > 50)\n    and rate(node_vmstat_pswpin[5m]) > 100\n"
                 "  for: 15m\n```\n")
    rule = checks.proposed_rule(procedure)
    assert rule["alert"] == "SwapUsageHigh" and rule["expr"].endswith("rate(node_vmstat_pswpin[5m]) > 100")
    assert checks.check_rule(rule, PROM) is None
    assert checks.proposed_rule("Redémarrer le conteneur") is None


def test_metric_names_skip_functions_labels_and_keywords():
    expr = 'sum by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) / on(instance) count(up) > 0.8 and foo offset 5m'
    assert checks.metric_names(expr) == ["node_cpu_seconds_total", "up", "foo"]


def test_rule_checks_against_prometheus():
    assert checks.check_rule({"alert": "SwapIn", "expr": "rate(node_vmstat_pswpin[5m]) > 100"}, PROM) is None
    assert "Prometheus refuse" in checks.check_rule({"alert": "X", "expr": "node_memory_SwapFree_bytes <"}, PROM)
    assert "node_memory_swap_in_total" in checks.check_rule(
        {"alert": "X", "expr": "rate(node_memory_swap_in_total[5m]) > 0"}, PROM)
    assert "identique à la règle actuelle" in checks.check_rule({"alert": "SwapUsageHigh", "expr": CURRENT}, PROM)
    assert "identique à la règle actuelle" in checks.check_rule({"alert": None, "expr": CURRENT}, PROM)
    assert "existe déjà dans la règle SwapUsageHigh" in checks.check_rule(
        {"alert": "SwapHigh", "expr": CURRENT.replace(" ", "")}, PROM)


def test_claims_contrary_to_measures_are_found():
    text = ("En direct, les conteneurs *jellyfin* et *radarr* dépassent souvent 1 GB.\n"
            "| 19:31 | radarr et jellyfin consomment > 0,5 GB | container_memory |\n"
            "seerr reste sous 500 Mo. radarr dépasse 900 Mo.")
    claims = checks.unsupported_claims(text, PEAKS)
    assert len(claims) == 1 and "dépassent souvent 1 GB" in claims[0] and "radarr 1020 Mo" in claims[0]


def test_orchestrator_refuses_bad_limit_and_wrong_sizes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    monkeypatch.setattr(checks, "measured_peaks", lambda run_dir: PEAKS)
    low = {**ACTION, "title": "Limiter radarr", "target": "xdocker", "procedure": "docker update --memory=1g radarr"}
    lead = ScriptedProvider([
        tools(call("propose_action", low, "low")),
        tools(call("propose_action", {**low, "procedure": "docker update --memory=1500m radarr"}, "ok")),
        answer("## Synthèse\nradarr dépasse 1,5 Go en pic."),
        answer("## Synthèse\nradarr monte à 1020 Mo en pic [subagents/T04-system-xdocker/calls/0003.json]."),
    ])
    log, status, text = asyncio.run(cli.ask("Pourquoi ?", providers=by_role(lead=lead)))
    assert status == "completed" and "1020 Mo" in text
    rejected = json.loads((log.dir / "lead" / "calls" / "0001.json").read_text())
    assert rejected["is_error"] and "Action non enregistrée" in rejected["output"] and "minimum 1224 Mo" in rejected["output"]
    actions = json.loads((log.dir / "actions.json").read_text())
    assert [a["procedure"] for a in actions] == ["docker update --memory=1500m radarr"]
    events = [json.loads(line) for line in (log.dir / "events.jsonl").read_text().splitlines()]
    assert [e["type"] for e in events if e["type"] in ("action_rejected", "facts_unsupported")] == \
        ["action_rejected", "facts_unsupported"]


def test_change_found_but_left_out_of_the_answer_is_recalled(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([
        tools(call("changes_around", {"entity": "srv-pay-01", "time_to": "2026-10-06T22:10:00Z"})),
        answer("## Synthèse\nPool de connexions saturé sur srv-pay-01, cause inconnue."),
        answer("## Synthèse\nCHG0034567 a réduit max_connections sur db-pay-02, 25 min avant le symptôme."),
    ])
    log, status, text = asyncio.run(cli.ask("Pourquoi ?", providers=by_role(lead=lead)))
    assert status == "completed" and "CHG0034567" in text
    recall = lead.requests[2].messages[-1].content
    assert "CHG0034567 sur db-pay-02 (dépendance de niveau 1" in recall and "25 min avant" in recall
    events = [json.loads(line) for line in (log.dir / "events.jsonl").read_text().splitlines()]
    assert [e["data"] for e in events if e["type"] == "changes_unmentioned"] == [{"changes": ["CHG0034567"]}]
