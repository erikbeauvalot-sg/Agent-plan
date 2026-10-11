// Routage par fragment, comme l'interface actuelle : # accueil, #<run_id> investigation, #admin,
// #relance/<run_id> accueil prérempli avec les choix d'une investigation (bouton « Relancer… »).
import { useEffect, useState } from "react";

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

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const runHref = (runId: string): string => `#${runId}`;
export const adminHref = "#admin";
