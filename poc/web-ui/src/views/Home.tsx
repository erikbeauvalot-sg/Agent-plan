// Accueil « poser, suivre, reprendre » : la question en héros, les investigations en cours en cartes
// vivantes, l'historique filtrable à gauche, l'état des sources, les alertes et les chiffres du jour à
// droite ; statistiques et évaluations repliées. Un Lecteur ne voit que les investigations partagées.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Category,
  HomeResponse,
  Me,
  ModelsResponse,
  RunFacets,
  RunRow,
  SourcesResponse,
  StatusResponse,
} from "../api/types";
import { ChevronDown, Lightbulb } from "../components/icons";
import { filtersFromHash, filtersToHash, hasFilters, apiQuery, type HistoryFilters } from "../lib/history";
import { alertQuestion, requestPrefill } from "../lib/prefill";
import { stored } from "../lib/storage";
import { EvalsCard, StatsCard, TodayCard } from "./home/ActivityCards";
import { AskForm } from "./home/AskForm";
import { HistoryList, LiveRuns } from "./home/RunLists";
import { AlertsCard, StatusCard } from "./home/StatusCards";

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const PAGE = 20;

export function Home({ me, rerunOf }: { me: Me; rerunOf: string | null }) {
  const canAsk = me.permissions.includes("ask");
  const showUser = me.permissions.includes("view_all");
  const [categories, setCategories] = useState<Category[]>([]);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [sources, setSources] = useState<SourcesResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(true); // première vérification en cours
  const [live, setLive] = useState<RunRow[]>([]);
  const [history, setHistory] = useState<RunRow[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [facets, setFacets] = useState<RunFacets | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [filters, setFilters] = useState<HistoryFilters>(() => filtersFromHash(location.hash));
  const [shown, setShown] = useState(PAGE);
  const [home, setHome] = useState<HomeResponse | null>(null);
  const [days, setDays] = useState(7);
  const [withEval, setWithEval] = useState(false);
  const [statsOpen, setStatsOpen] = useState(() => stored.get("stats-open") === "1");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    api<Category[]>("/api/categories")
      .then(setCategories)
      .catch(() => setCategories([]));
    api<ModelsResponse>("/api/models")
      .then(setModels)
      .catch(() => {});
    api<SourcesResponse>("/api/sources")
      .then(setSources)
      .catch(() => {});
    api<RunFacets>("/api/runs/facets")
      .then(setFacets)
      .catch(() => {});
    if (canAsk)
      api<RunRow[]>(`/api/runs?limit=12&user=${encodeURIComponent(me.login)}`)
        .then((rows) => setRecent([...new Set(rows.map((r) => r.question))]))
        .catch(() => {});
  }, [canAsk, me.login]);

  const fetchStatus = useCallback(
    (refresh: boolean) =>
      api<StatusResponse>(`/api/status${refresh ? "?refresh=true" : ""}`)
        .then((s) => {
          setStatus(s);
          setStatusError(null);
        })
        .catch((e) => setStatusError(errorText(e)))
        .finally(() => setRefreshing(false)),
    [],
  );
  useEffect(() => {
    fetchStatus(false);
  }, [fetchStatus]);
  const refreshStatus = () => {
    setRefreshing(true);
    fetchStatus(true);
  };

  // Investigations en cours : relues toutes les 3 s (état des agents, ligne de statut).
  useEffect(() => {
    const load = () =>
      api<RunRow[]>("/api/runs?status=running&limit=20")
        .then((rows) => {
          setLive(rows);
          setNow(Date.now());
        })
        .catch(() => {});
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  // Historique : rechargé à chaque changement de filtre, puis toutes les 10 s (nouvelles investigations
  // terminées). Une ligne de plus que la page dit s'il en reste.
  const query = apiQuery(filters).toString();
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api<RunRow[]>(`/api/runs?limit=${shown + 1}${query ? `&${query}` : ""}`)
        .then((rows) => {
          if (cancelled) return;
          setHistory(rows);
          setHistoryError(null);
        })
        .catch((e) => !cancelled && setHistoryError(errorText(e)));
    load();
    const timer = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [query, shown]);

  // Les filtres vivent dans l'adresse (partageable) sans créer une entrée d'historique par clic.
  const onFilters = useCallback((f: HistoryFilters) => {
    setFilters(f);
    setShown(PAGE);
    if (location.hash.startsWith("#relance/")) return;
    const hash = filtersToHash(f);
    window.history.replaceState(null, "", hash === "#" ? location.pathname + location.search : hash);
  }, []);

  useEffect(() => {
    api<HomeResponse>(`/api/home?days=${days}&include_eval=${withEval}`)
      .then(setHome)
      .catch(() => setHome(null));
  }, [days, withEval]);

  const rows = (history ?? []).filter((r) => filters.status.length || r.status !== "running");
  const firstLaunch = history !== null && !history.length && !hasFilters(filters) && !live.length;
  const examples = categories
    .map((c) => c.examples?.[0])
    .filter((q): q is string => !!q)
    .slice(0, 3);

  const side = (
    <div className="col">
      <StatusCard status={status} error={statusError} refreshing={refreshing} onRefresh={refreshStatus} />
      <AlertsCard
        alerts={status?.alerts ?? []}
        canAsk={canAsk}
        onInvestigate={(a) => requestPrefill({ question: alertQuestion(a), sources: "maison" })}
      />
      <TodayCard data={home} withEval={withEval} />
    </div>
  );

  return (
    <>
      {canAsk && (
        <AskForm
          categories={categories}
          models={models}
          modelStates={status?.models ?? null}
          sources={sources}
          rerunOf={rerunOf}
          alerts={status?.alerts ?? []}
          recent={recent}
        />
      )}
      <LiveRuns runs={live} showUser={showUser} now={now} />
      {firstLaunch ? (
        <div className="home-grid">
          <section className="card welcome" aria-labelledby="welcome-title">
            <h2 id="welcome-title">{canAsk ? "Bienvenue" : "Aucune investigation partagée"}</h2>
            {canAsk ? (
              <>
                <p className="muted">
                  Pose une question sur la production : l'agent classe la demande, interroge les sources (CMDB,
                  métriques, logs, alertes, changements) avec des sous-agents en parallèle, puis rend une synthèse avec
                  ses preuves. Il propose des actions sans jamais les exécuter.
                </p>
                <ul className="suggestions">
                  {examples.map((q) => (
                    <li key={q}>
                      <button type="button" className="suggestion" onClick={() => requestPrefill({ question: q })}>
                        <Lightbulb size={13} aria-hidden="true" />
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="faint">Vérifie à droite que les modèles et les sources sont disponibles.</p>
              </>
            ) : (
              <p className="muted">
                Les investigations que leurs auteurs partagent apparaîtront ici. Ton rôle permet de les lire, pas d'en
                lancer.
              </p>
            )}
          </section>
          {side}
        </div>
      ) : (
        <div className="home-grid">
          <HistoryList
            runs={history === null ? null : rows.slice(0, shown)}
            error={historyError}
            more={(history?.length ?? 0) > shown}
            onMore={() => setShown((n) => n + PAGE * 2)}
            filters={filters}
            onFilters={onFilters}
            facets={facets}
            categories={categories}
            showUser={showUser}
            me={me.login}
            now={now}
            title={canAsk ? "Historique" : "Investigations partagées"}
          />
          {side}
        </div>
      )}
      <details
        className="fold"
        open={statsOpen}
        onToggle={(e) => {
          const open = (e.currentTarget as HTMLDetailsElement).open;
          setStatsOpen(open);
          stored.set("stats-open", open ? "1" : "0");
        }}
      >
        <summary>
          <ChevronDown size={15} aria-hidden="true" />
          Statistiques et évaluations
          <span className="faint">pilotage : réussite par catégorie, agent et modèle</span>
        </summary>
        {statsOpen && (
          <div className="fold-body">
            <EvalsCard data={home} />
            <StatsCard data={home} days={days} withEval={withEval} onDays={setDays} onWithEval={setWithEval} />
          </div>
        )}
      </details>
    </>
  );
}
