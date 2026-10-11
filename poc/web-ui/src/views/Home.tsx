// Accueil : poser une question, suivre ce qui tourne, retrouver une investigation, voir l'état des sources.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Alert,
  Category,
  HomeResponse,
  Me,
  ModelsResponse,
  RunRow,
  SourcesResponse,
  StatusResponse,
} from "../api/types";
import { EvalsCard, StatsCard, TodayCard } from "./home/ActivityCards";
import { AskForm, type Prefill } from "./home/AskForm";
import { LiveRuns, RecentRuns } from "./home/RunLists";
import { AlertsCard, StatusCard } from "./home/StatusCards";

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function Home({ me, rerunOf }: { me: Me; rerunOf: string | null }) {
  const canAsk = me.permissions.includes("ask");
  const [categories, setCategories] = useState<Category[]>([]);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [sources, setSources] = useState<SourcesResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(true); // première vérification en cours
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [home, setHome] = useState<HomeResponse | null>(null);
  const [days, setDays] = useState(7);
  const [withEval, setWithEval] = useState(false);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
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
  }, []);

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

  // La liste se rafraîchit tant que l'accueil est affiché (investigations en cours, nouvelles investigations).
  useEffect(() => {
    const load = () =>
      api<RunRow[]>("/api/runs?limit=300")
        .then((r) => {
          setRuns(r);
          setRunsError(null);
          setNow(Date.now());
        })
        .catch((e) => setRunsError(errorText(e)));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    api<HomeResponse>(`/api/home?days=${days}&include_eval=${withEval}`)
      .then(setHome)
      .catch(() => setHome(null));
  }, [days, withEval]);

  const investigate = (a: Alert) =>
    setPrefill({
      question:
        `Analyse l'alerte ${a.alertname}${a.host ? " sur " + a.host : ""}` +
        `${a.summary ? " (" + a.summary + ")" : ""} : cause probable et actions possibles.`,
      sources: "maison",
      nonce: Date.now(),
    });

  const showUser = me.permissions.includes("view_all");
  return (
    <>
      {canAsk && (
        <AskForm
          categories={categories}
          models={models}
          modelStates={status?.models ?? null}
          sources={sources}
          rerunOf={rerunOf}
          prefill={prefill}
        />
      )}
      <div className="home-grid">
        <div className="col">
          <LiveRuns runs={runs} showUser={showUser} now={now} />
          <RecentRuns runs={runs} error={runsError} categories={categories} showUser={showUser} now={now} />
        </div>
        <div className="col">
          <StatusCard status={status} error={statusError} refreshing={refreshing} onRefresh={refreshStatus} />
          <AlertsCard alerts={status?.alerts ?? []} canAsk={canAsk} onInvestigate={investigate} />
          <TodayCard data={home} withEval={withEval} />
          <EvalsCard data={home} />
        </div>
      </div>
      <StatsCard data={home} days={days} withEval={withEval} onDays={setDays} onWithEval={setWithEval} />
    </>
  );
}
