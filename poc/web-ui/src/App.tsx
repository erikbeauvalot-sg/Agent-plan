// Démarrage : session (/api/me), puis la vue demandée par le fragment d'URL.
import { useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api/client";
import type { Me } from "./api/types";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TopBar } from "./components/TopBar";
import { useRoute } from "./lib/route";
import { Admin } from "./views/Admin";
import { Home } from "./views/Home";
import { Login } from "./views/Login";
import { Run } from "./views/Run";

type Session = { state: "loading" } | { state: "anonymous" } | { state: "signed-in"; me: Me };

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const route = useRoute();

  useEffect(() => {
    setUnauthorizedHandler(() => setSession({ state: "anonymous" }));
    api<Me>("/api/me")
      .then((me) => setSession({ state: "signed-in", me }))
      .catch(() => setSession({ state: "anonymous" }));
  }, []);

  // Changer de vue ramène en haut de page, comme un changement de page.
  useEffect(() => {
    window.scrollTo(0, 0); // Chromium récent renvoie une promesse : ne pas la rendre comme nettoyage
  }, [route]);

  if (session.state === "loading") return <div className="login" aria-busy="true" />;
  if (session.state === "anonymous") return <Login />;
  const { me } = session;
  return (
    <>
      <TopBar me={me} />
      <main className="main" id="main">
        <ErrorBoundary resetKey={location.hash}>
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
