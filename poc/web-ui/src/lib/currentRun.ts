// Investigation affichée, pour la barre du haut (titre court et état) : publiée par la vue d'investigation,
// effacée quand on la quitte.
import { useSyncExternalStore } from "react";

export interface CurrentRun {
  question: string;
  status: string;
}

let current: CurrentRun | null = null;
const listeners = new Set<() => void>();

export function setCurrentRun(run: CurrentRun | null): void {
  if (current?.question === run?.question && current?.status === run?.status) return;
  current = run;
  listeners.forEach((l) => l());
}

export function useCurrentRun(): CurrentRun | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}
