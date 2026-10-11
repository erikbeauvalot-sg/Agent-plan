// Démarrage : session (/api/me), puis la vue demandée par le fragment d'URL.
import { useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api/client";
import type { Me } from "./api/types";
import { TopBar } from "./components/TopBar";
import { legacyAdminHref, legacyRunHref, useRoute } from "./lib/route";
import { Home } from "./views/Home";
import { Login } from "./views/Login";

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

  // Lot 0a : investigation et administration restent dans l'interface actuelle.
  useEffect(() => {
    if (session.state !== "signed-in") return;
    if (route.view === "run") location.replace(legacyRunHref(route.runId));
    else if (route.view === "admin") location.replace(legacyAdminHref);
  }, [route, session.state]);

  if (session.state === "loading") return <div className="login" aria-busy="true" />;
  if (session.state === "anonymous") return <Login />;
  const { me } = session;
  return (
    <>
      <TopBar me={me} />
      <main className="main" id="main">
        {route.view === "home" || route.view === "rerun" ? (
          <Home me={me} rerunOf={route.view === "rerun" ? route.runId : null} />
        ) : (
          <p className="muted">Ouverture dans l'interface actuelle…</p>
        )}
      </main>
    </>
  );
}
