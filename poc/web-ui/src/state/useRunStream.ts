// Flux temps réel d'une investigation (SSE /api/runs/{id}/events) réduit en état d'agents. Les événements
// reçus dans une même image sont appliqués ensemble ; la reprise après coupure est native (Last-Event-ID)
// et reduce() ignore un événement déjà vu.
import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "../api/types";
import { emptyRun, reduceAll, type RunState } from "./runState";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "ended";

export function useRunStream(runId: string, onEnd: () => void): { state: RunState; status: StreamStatus } {
  const [state, setState] = useState<RunState>(emptyRun);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const endRef = useRef(onEnd);
  useEffect(() => {
    endRef.current = onEnd;
  }, [onEnd]);

  useEffect(() => {
    const source = new EventSource(`/api/runs/${runId}/events`);
    let queue: RunEvent[] = [];
    let frame = 0;
    const flush = () => {
      frame = 0;
      const batch = queue;
      queue = [];
      setState((s) => reduceAll(batch, s));
    };
    source.addEventListener("open", () => setStatus("live"));
    source.addEventListener("agent", (msg) => {
      queue.push(JSON.parse((msg as MessageEvent<string>).data) as RunEvent);
      frame ||= requestAnimationFrame(flush);
    });
    source.addEventListener("end", () => {
      source.close();
      if (frame) cancelAnimationFrame(frame);
      flush();
      setStatus("ended");
      endRef.current();
    });
    source.addEventListener("error", () => {
      if (source.readyState !== EventSource.CLOSED) setStatus("reconnecting");
    });
    return () => {
      source.close();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [runId]);

  return { state, status };
}
