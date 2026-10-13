"""Démonstration en direct sans modèle : rejoue une investigation enregistrée comme si elle tournait.

    uv run python tools/demo_live.py 20261011T172623Z-5a7a --speed 4

Copie l'investigation sous un nouvel identifiant (manifest `running`), puis réécrit ses événements au rythme
des horodatages d'origine, accéléré par --speed. Les signaux de l'orchestrateur (bloqué, boucle, erreurs,
budget, modèle, source lente) sont recalculés pendant le rejeu, comme pendant une vraie investigation. Ouvrir
l'adresse affichée dans le navigateur (serveur lancé par ailleurs sur le même dossier runs/). À la fin, le
manifest reprend le statut d'origine ; l'investigation de démonstration n'est pas ajoutée à index.jsonl.
Ctrl+C arrête le rejeu et marque l'investigation « stopped ».
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from diagagent import catalog  # noqa: E402
from diagagent.runlog import _dump, _ts  # noqa: E402
from diagagent.signals import SignalMonitor, Thresholds  # noqa: E402


def runs_dir() -> Path:
    import yaml

    poc = yaml.safe_load((catalog.home() / "config" / "poc.yaml").read_text(encoding="utf-8"))
    return catalog.runs_dir(poc)


def find(base: Path, run_id: str) -> Path:
    path = base / run_id[:4] / run_id[4:6] / run_id[6:8] / run_id
    if not (path / "events.jsonl").exists():
        raise SystemExit(f"Investigation introuvable : {path}")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_id")
    p.add_argument("--speed", type=float, default=1.0, help="accélération (2 = deux fois plus vite)")
    p.add_argument("--max-gap", type=float, default=8.0, help="attente maximale entre deux événements, en s")
    args = p.parse_args()

    base = runs_dir()
    src = find(base, args.run_id)
    now = datetime.now(timezone.utc)
    new_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)
    dst = base / now.strftime("%Y/%m/%d") / new_id
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("events.jsonl"))
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    final = {k: manifest.get(k) for k in ("status", "ended_at", "usage")}
    manifest.update(run_id=new_id, status="running", started_at=_ts(), signals="orchestrator",
                    demo_of=args.run_id)
    for k in ("ended_at",):
        manifest.pop(k, None)
    _dump(dst / "manifest.json", manifest)
    analysis = dst / "analysis.md"
    answer = analysis.read_text(encoding="utf-8") if analysis.exists() else None
    analysis.unlink(missing_ok=True)  # la réponse apparaît à la fin, comme en vrai

    events = [json.loads(line) for line in (src / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip() and not json.loads(line)["type"].startswith("signal_")]
    out = (dst / "events.jsonl").open("a", encoding="utf-8")
    seq = 0
    trace_t = [0.0]  # horloge de la trace (s depuis le premier événement), pour les seuils des signaux

    def write(agent_id: str, type_: str, data: dict, parent_id: str | None) -> None:
        nonlocal seq
        seq += 1
        out.write(json.dumps({"seq": seq, "ts": _ts(), "run_id": new_id, "agent_id": agent_id,
                              "parent_id": parent_id, "type": type_, "data": data}, ensure_ascii=False) + "\n")
        out.flush()

    monitor = SignalMonitor(write, Thresholds(), clock=lambda: trace_t[0])
    # Trace antérieure à la diffusion : la réponse finale est réécrite par morceaux juste avant la fin du
    # dernier appel au modèle de l'agent principal, pour voir la réponse arriver au fil de l'eau.
    streamed = any(e["type"] == "answer_delta" for e in events)
    final_call = max((i for i, e in enumerate(events) if e["agent_id"] == "lead" and e["type"] == "llm_call_ended"
                      and (e.get("data") or {}).get("stop_reason") == "end"), default=None)
    print(f"Rejeu de {args.run_id} sous {new_id} (×{args.speed:g}) : http://127.0.0.1:8080/#{new_id}", flush=True)
    status = final["status"] or "completed"
    try:
        t0 = datetime.fromisoformat(events[0]["ts"].replace("Z", "+00:00")) if events else now
        for i, e in enumerate(events):
            if i == final_call and answer and not streamed:
                for k in range(0, len(answer), 48):
                    write("lead", "answer_delta", {"text": answer[k:k + 48]}, None)
                    time.sleep(0.05 / max(args.speed, 0.1))
            at = (datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) - t0).total_seconds()
            gap = min(args.max_gap, max(0.0, (at - trace_t[0]) / args.speed))
            # Pendant l'attente, l'horloge de la trace avance : les signaux liés au temps se lèvent.
            end = time.monotonic() + gap
            while (left := end - time.monotonic()) > 0:
                time.sleep(min(1.0, left))
                trace_t[0] = at - left * args.speed
                monitor.tick()
            trace_t[0] = at
            write(e["agent_id"], e["type"], e.get("data") or {}, e.get("parent_id"))
            monitor.observe(e["agent_id"], e["type"], e.get("data") or {}, e.get("parent_id"))
    except KeyboardInterrupt:
        status = "stopped"
        print("\nRejeu interrompu.")
    finally:
        out.close()
        if answer is not None:
            analysis.write_text(answer, encoding="utf-8")
        manifest.update(status=status, ended_at=_ts(), usage=final["usage"])
        _dump(dst / "manifest.json", manifest)
    print(f"Terminé : {new_id} ({status})")


if __name__ == "__main__":
    main()
