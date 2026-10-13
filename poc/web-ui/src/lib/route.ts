// Routage par fragment, comme l'interface actuelle : # accueil, #<run_id> investigation, #admin,
// #relance/<run_id> accueil prérempli avec les choix d'une investigation (bouton « Relancer… »).
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

export type Route =
  { view: "home" } | { view: "rerun"; runId: string } | { view: "run"; runId: string } | { view: "admin" };

const RUN_ID = /^\d{8}T\d{6}Z-[0-9a-f]{4}$/;

export function parseRoute(hash: string): Route {
  const target = decodeURIComponent(hash.replace(/^#/, ""));
  if (target === "admin") return { view: "admin" };
  if (target.startsWith("relance/") && RUN_ID.test(target.slice(8))) return { view: "rerun", runId: target.slice(8) };
  if (RUN_ID.test(target)) return { view: "run", runId: target };
  return { view: "home" };
}

/** Changement de vue animé (View Transitions) quand le navigateur le permet et que le mouvement n'est pas
 * réduit : la question de l'accueil se transforme en titre de l'investigation. Sinon, changement immédiat. */
function transition(update: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  if (!doc.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) return update();
  doc.startViewTransition(() => flushSync(update));
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  const shown = useRef(route);
  useEffect(() => {
    shown.current = route;
  }, [route]);
  useEffect(() => {
    const onChange = () => {
      const next = parseRoute(location.hash);
      const prev = shown.current;
      // Seuls l'ouverture et la fermeture d'une investigation sont animées (pas un filtre, pas une relance).
      const runChanged = (next.view === "run" ? next.runId : null) !== (prev.view === "run" ? prev.runId : null);
      if (runChanged) transition(() => setRoute(next));
      else setRoute(next);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const runHref = (runId: string): string => `#${runId}`;
export const adminHref = "#admin";
