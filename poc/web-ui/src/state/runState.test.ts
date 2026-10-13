import { describe, expect, it } from "vitest";
import type { RunEvent } from "../api/types";
import { emptyRun, liveUsage, reduce, reduceAll, signals } from "./runState";

let seq = 0;
const ev = (
  agent_id: string,
  type: string,
  at: string,
  data: Record<string, unknown> = {},
  parent_id: string | null = null,
): RunEvent => ({
  seq: ++seq,
  ts: `2026-10-07T06:00:${at}Z`,
  run_id: "20261007T060000Z-abcd",
  agent_id,
  parent_id,
  type,
  data,
});

describe("reduce", () => {
  const events = [
    ev("lead", "classification_started", "00"),
    ev("lead", "request_classified", "01", {
      id: "performance",
      mode: "playbook",
      usage: { input_tokens: 800, output_tokens: 50 },
    }),
    ev("lead", "agent_started", "02", {
      provider: "local",
      model: "gpt-oss:20b",
      max_tool_calls: 32,
    }),
    ev("lead", "llm_call_started", "02"),
    ev("lead", "llm_call_ended", "05", {
      model: "gpt-oss:20b",
      usage: { input_tokens: 1000, output_tokens: 200, reasoning_tokens: 40 },
    }),
    ev("T01-logs-srv-pay-01", "agent_spawned", "05", { objective: "Erreurs" }, "lead"),
    ev("T01-logs-srv-pay-01", "agent_started", "06", { max_tool_calls: 4 }),
    ev("T01-logs-srv-pay-01", "tool_call_started", "06", {
      tool: "search",
      ref: "subagents/T01/calls/0001.json",
      arguments: { q: 1 },
    }),
    ev("T01-logs-srv-pay-01", "tool_call_ended", "08", {
      tool: "search",
      ref: "subagents/T01/calls/0001.json",
      is_error: true,
    }),
    ev("T01-logs-srv-pay-01", "agent_ended", "09", { status: "completed" }),
  ];

  it("rebuilds agents, segments and usage from events only", () => {
    const s = reduceAll(events);
    expect(s.order).toEqual(["lead", "T01-logs-srv-pay-01"]);
    const lead = s.agents.lead!;
    expect(lead.role).toBe("principal");
    expect(lead.llm).toBe("local / gpt-oss:20b");
    expect(lead.segments.map((x) => [x.kind, x.label])).toEqual([
      ["llm", "classification : performance"],
      ["llm", "modèle gpt-oss:20b"],
    ]);
    const sub = s.agents["T01-logs-srv-pay-01"]!;
    expect(sub).toMatchObject({
      role: "logs",
      parent: "lead",
      objective: "Erreurs",
      status: "completed",
      toolCalls: 1,
      errorStreak: 1,
    });
    expect(sub.segments[0]).toMatchObject({
      kind: "err",
      label: "search",
      ref: "subagents/T01/calls/0001.json",
    });
    expect(liveUsage(s)).toEqual({
      tokensIn: 1800,
      tokensOut: 250,
      tokensReasoning: 40,
      tokens: 2050,
    });
    expect(s.summaryVersion).toBe(1);
  });

  it("ignores an event already applied (reconnexion du flux)", () => {
    const s = reduceAll(events);
    expect(reduce(s, events[4]!)).toBe(s);
  });

  it("never mutates the previous state", () => {
    const before = reduceAll(events.slice(0, 7));
    const snapshot = JSON.stringify(before);
    reduce(before, events[7]!);
    expect(JSON.stringify(before)).toBe(snapshot);
  });

  it("marks running agents as stopping when the whole run is stopped", () => {
    const s = reduceAll([...events.slice(0, 7), ev("lead", "stop_requested", "10", { scope: "run" })]);
    expect(s.agents.lead!.status).toBe("stopping");
    expect(s.agents["T01-logs-srv-pay-01"]!.status).toBe("stopping");
  });

  it("ends the run on a clarification request", () => {
    const s = reduceAll([
      ev("lead", "classification_started", "00"),
      ev("lead", "request_classified", "01", {
        id: "indisponibilite",
        mode: "clarify",
      }),
    ]);
    expect(s.agents.lead!.status).toBe("needs_clarification");
  });
});

describe("signals", () => {
  it("raises stuck, loop, errors, budget and model signals", () => {
    let s = emptyRun();
    s = reduce(s, ev("T02-metrics-x", "agent_started", "00", { max_tool_calls: 4 }));
    for (let i = 0; i < 4; i++) {
      s = reduce(
        s,
        ev("T02-metrics-x", "tool_call_started", `0${i}`, {
          tool: "query_metric",
          ref: `r${i}`,
          arguments: { m: "cpu" },
        }),
      );
      s = reduce(
        s,
        ev("T02-metrics-x", "tool_call_ended", `0${i}`, {
          tool: "query_metric",
          ref: `r${i}`,
          is_error: true,
        }),
      );
    }
    s = reduce(s, ev("T02-metrics-x", "llm_call_ended", "05", { error: "quota" }));
    const a = s.agents["T02-metrics-x"]!;
    const keys = signals(a, a.last + 121_000).map((x) => x.key);
    expect(keys).toEqual(["stuck", "loop", "errors", "budget", "model"]);
    expect(signals({ ...a, status: "completed" }, a.last + 121_000)).toEqual([]);
  });
});

describe("signaux de l'orchestrateur et activité", () => {
  const events = [
    ev("lead", "agent_started", "00", { max_tool_calls: 10 }),
    ev("T01-metrics-srv-pay-01", "agent_spawned", "01", { role: "metrics", objective: "latence" }, "lead"),
    ev("T01-metrics-srv-pay-01", "agent_started", "02", {}, "lead"),
    ev(
      "T01-metrics-srv-pay-01",
      "tool_call_started",
      "03",
      {
        tool: "query_metric",
        ref: "subagents/T01-metrics-srv-pay-01/calls/0001.json",
        arguments: { host: "srv-pay-01", metric: "cpu.usage" },
      },
      "lead",
    ),
    ev(
      "T01-metrics-srv-pay-01",
      "signal_raised",
      "20",
      {
        kind: "slow:subagents/T01-metrics-srv-pay-01/calls/0001.json",
        text: "source lente",
        ref: "subagents/T01-metrics-srv-pay-01/calls/0001.json",
      },
      "lead",
    ),
    ev("T01-metrics-srv-pay-01", "signal_raised", "21", { kind: "loop", text: "boucle", level: "warn" }, "lead"),
  ];
  const run = reduceAll(events);
  const t01 = run.agents["T01-metrics-srv-pay-01"]!;

  it("décrit ce que fait l'agent en ce moment", () => {
    expect(t01.current).toBe("interroge les métriques : cpu.usage de srv-pay-01");
    expect(run.feed.map((f) => f.text)).toEqual([
      "T01 lancé : latence",
      "T01 interroge les métriques : cpu.usage de srv-pay-01",
      "T01 — source lente",
      "T01 — boucle",
    ]);
  });

  it("affiche les signaux du serveur sans les recalculer", () => {
    expect(run.serverSignals).toBe(true);
    const now = Date.parse("2026-10-07T06:00:30Z");
    expect(signals(t01, now, true).map((s) => s.text)).toEqual(["boucle", "source lente"]);
    expect(t01.slowRefs).toEqual(["subagents/T01-metrics-srv-pay-01/calls/0001.json"]);
    // Un signal ne compte pas comme activité de l'agent.
    expect(t01.last).toBe(Date.parse("2026-10-07T06:00:03Z"));
    const cleared = reduce(run, ev("T01-metrics-srv-pay-01", "signal_cleared", "22", { kind: "loop" }, "lead"));
    expect(signals(cleared.agents["T01-metrics-srv-pay-01"]!, now, true).map((s) => s.key)).toEqual(["slow"]);
  });
});

describe("réponse au fil de l'eau", () => {
  it("garde la réponse, jette un préambule et marque une révision", () => {
    let run = reduceAll([
      ev("lead", "agent_started", "00"),
      ev("lead", "llm_call_started", "01"),
      ev("lead", "answer_delta", "02", { text: "Je regarde " }),
      ev("lead", "llm_call_ended", "03", { stop_reason: "tool_call" }),
    ]);
    expect(run.draft).toBeNull(); // préambule suivi d'appels d'outils
    run = reduceAll(
      [
        ev("lead", "llm_call_started", "04"),
        ev("lead", "answer_delta", "05", { text: "## Synthèse\n" }),
        ev("lead", "answer_delta", "06", { text: "CHG0034567" }),
        ev("lead", "llm_call_ended", "07", { stop_reason: "end" }),
        ev("lead", "final_answer_rechecked", "08", { reason: "vagues" }),
      ],
      run,
    );
    expect(run.draft).toMatchObject({ text: "## Synthèse\nCHG0034567", revising: true, done: false });
    run = reduceAll(
      [
        ev("lead", "llm_call_started", "09"),
        ev("lead", "answer_delta", "10", { text: "## Synthèse\nv2" }),
        ev("lead", "agent_ended", "11", { status: "completed" }),
      ],
      run,
    );
    expect(run.draft).toMatchObject({ text: "## Synthèse\nv2", revising: false, done: true });
  });
});
