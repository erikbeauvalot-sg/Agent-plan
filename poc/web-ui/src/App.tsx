// Démarrage : session (/api/me), puis la vue demandée par le fragment d'URL ; palette de commandes et
// raccourcis clavier communs à toutes les vues.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, setUnauthorizedHandler } from "./api/client";
import type { Me } from "./api/types";
import { CommandPalette, focusQuestion } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ADMIN_PERMISSIONS, TopBar } from "./components/TopBar";
import { useRoute } from "./lib/route";
import { applyTheme, loadTheme, type ThemeChoice } from "./lib/theme";
import { Activation } from "./views/Activation";
import { Admin } from "./views/Admin";
import { Home } from "./views/Home";
import { Login } from "./views/Login";
import { Run } from "./views/Run";

type Session = { state: "loading" } | { state: "anonymous" } | { state: "signed-in"; me: Me };

/** Les raccourcis à une touche ne s'activent jamais pendant une saisie. */
const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [theme, setTheme] = useState<ThemeChoice>(loadTheme);
  const [palette, setPalette] = useState(false);
  const route = useRoute();
  const pendingG = useRef(0);

  const loadSession = useCallback(() => {
    api<Me>("/api/me")
      .then((me) => setSession({ state: "signed-in", me }))
      .catch(() => setSession({ state: "anonymous" }));
  }, []);
  useEffect(() => {
    setUnauthorizedHandler(() => setSession({ state: "anonymous" }));
    loadSession();
  }, [loadSession]);

  // Changer de vue ramène en haut de page, comme un changement de page (pas un changement de filtre).
  const viewKey = route.view === "run" || route.view === "rerun" ? `${route.view}/${route.runId}` : route.view;
  useEffect(() => {
    window.scrollTo(0, 0); // Chromium récent renvoie une promesse : ne pas la rendre comme nettoyage
  }, [viewKey]);

  const onTheme = useCallback((t: ThemeChoice) => {
    applyTheme(t);
    setTheme(t);
  }, []);

  const signedIn = session.state === "signed-in";
  useEffect(() => {
    if (!signedIn) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || document.querySelector("dialog[open]")) return;
      if (e.key === "/") {
        e.preventDefault();
        const search = document.getElementById("history-search");
        if (!document.getElementById("ask-question") && search) search.focus();
        else focusQuestion();
      } else if (e.key === "?") {
        setPalette(true);
      } else if (e.key === "g") {
        pendingG.current = Date.now();
        return;
      } else if (Date.now() - pendingG.current < 1200 && (e.key === "h" || e.key === "a")) {
        location.hash = e.key === "h" ? "" : "admin";
      }
      pendingG.current = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [signedIn]);

  // Le lien d'activation s'ouvre sans session (ou avec celle d'un autre compte, sur un poste partagé).
  if (route.view === "activation")
    return (
      <Activation
        token={route.token}
        onActivated={() => {
          location.replace("#"); // remplace l'entrée d'historique : le jeton n'y reste pas
          loadSession();
        }}
      />
    );
  if (session.state === "loading") return <div className="login" aria-busy="true" />;
  if (session.state === "anonymous") return <Login />;
  const { me } = session;
  const canAdmin = ADMIN_PERMISSIONS.some((p) => me.permissions.includes(p));
  return (
    <>
      <TopBar me={me} theme={theme} onTheme={onTheme} onPalette={() => setPalette(true)} />
      <CommandPalette
        me={me}
        open={palette}
        route={route}
        canAdmin={canAdmin}
        theme={theme}
        onTheme={onTheme}
        onClose={() => setPalette(false)}
      />
      <main className="main" id="main">
        <ErrorBoundary resetKey={viewKey}>
          {route.view === "run" ? (
            <Run key={route.runId} me={me} runId={route.runId} />
          ) : route.view === "admin" ? (
            <Admin me={me} />
          ) : (
            <Home me={me} rerunOf={route.view === "rerun" ? route.runId : null} />
          )}
        </ErrorBoundary>
      </main>
    </>
  );
}
