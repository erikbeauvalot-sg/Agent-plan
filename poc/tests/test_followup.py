"""Contexte d'une question de suivi : question, synthèse et rapports de l'investigation d'origine, plafonnés."""

import json

from diagagent import followup


def make_run(runs, run_id, question, analysis, reports=(), follow_up_of=None):
    path = followup.run_dir(runs, run_id)
    path.mkdir(parents=True)
    manifest = {"run_id": run_id, "question": question, "status": "completed", "started_at": "2026-10-07T06:00:00Z"}
    if follow_up_of:
        manifest["follow_up_of"] = follow_up_of
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "analysis.md").write_text(analysis, encoding="utf-8")
    for task_id, report in reports:
        (path / "subagents" / task_id).mkdir(parents=True)
        (path / "subagents" / task_id / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return path


def test_context_has_question_answer_reports_and_chain(tmp_path):
    make_run(tmp_path, "20261007T060000Z-aaaa", "Pourquoi srv-pay-01 est lent ?", "## Synthèse\nCHG0034567")
    make_run(tmp_path, "20261007T061000Z-bbbb", "Et db-pay-02 ?", "## Synthèse\n" + "x" * 9000,
             [("T01-metrics-db-pay-02", {"status": "completed", "summary": "cpu à 95 %",
                                         "findings": [{"fact": "pic à 21:50"}]})],
             follow_up_of="20261007T060000Z-aaaa")
    ctx = followup.context(tmp_path, "20261007T061000Z-bbbb")
    lead = ctx["lead"]
    assert ctx["previous"] == "Et db-pay-02 ?"
    assert "Questions précédentes du fil : « Pourquoi srv-pay-01 est lent ? »" in lead
    assert "T01-metrics-db-pay-02 (completed) : cpu à 95 % Faits : pic à 21:50" in lead
    assert "[… tronqué]" in lead and len(lead) < 9000  # synthèse plafonnée
    assert [m["run_id"] for m in followup.chain(tmp_path, "20261007T061000Z-bbbb")] == [
        "20261007T060000Z-aaaa", "20261007T061000Z-bbbb"]
