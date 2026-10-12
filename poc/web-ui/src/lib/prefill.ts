// Question préremplie depuis un autre endroit que le champ (alerte « Investiguer », palette de commandes) :
// un petit magasin partagé, lu par le formulaire de l'accueil, qui peut ne pas être affiché au moment de
// la demande.
import { useSyncExternalStore } from "react";

export interface Prefill {
  question: string;
  sources?: string;
  nonce: number;
}

let current: Prefill | null = null;
const listeners = new Set<() => void>();

export function requestPrefill(p: Omit<Prefill, "nonce">): void {
  current = { ...p, nonce: Date.now() + Math.random() };
  listeners.forEach((l) => l());
  if (location.hash.replace(/^#/, "") && !location.hash.startsWith("#?")) location.hash = "";
}

export function usePrefill(): Prefill | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}

/** Question proposée pour une alerte en cours. */
export function alertQuestion(a: { alertname: string; host?: string | null; summary?: string | null }): string {
  return (
    `Analyse l'alerte ${a.alertname}${a.host ? " sur " + a.host : ""}` +
    `${a.summary ? " (" + a.summary + ")" : ""} : cause probable et actions possibles.`
  );
}

// Un préremplissage ne s'applique qu'une fois : revenir sur l'accueil plus tard ne le remet pas.
let consumed: number | null = null;
export const consumedPrefill = (): number | null => consumed;
export const markPrefillConsumed = (nonce: number): void => {
  consumed = nonce;
};
