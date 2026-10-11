// Question et options (modèle, données, catégorie), relance avec les choix d'une investigation d'origine.
import { useEffect, useMemo, useState } from "react";
import { api, post } from "../../api/client";
import type { AskBody, Category, Choice, ModelState, RunDetail, SourcesResponse } from "../../api/types";
import { legacyRunHref } from "../../lib/route";
import { stored } from "../../lib/storage";

export interface Prefill {
  question: string;
  sources?: string;
  nonce: number;
}

interface Props {
  categories: Category[];
  models: { profiles: string[]; default: string } | null;
  modelStates: ModelState[] | null;
  sources: SourcesResponse | null;
  rerunOf: string | null;
  prefill: Prefill | null;
}

/** Valeur gardée si elle est disponible, sinon le défaut, sinon la première option disponible. */
export function pick(
  choices: Choice[],
  wanted: string | null | undefined,
  fallback: string | null | undefined,
): string {
  const usable = (v: string | null | undefined) => !!v && choices.some((c) => c.value === v && c.available);
  if (usable(wanted)) return wanted!;
  if (usable(fallback)) return fallback!;
  return choices.find((c) => c.available)?.value ?? "";
}

export function AskForm({ categories, models, modelStates, sources, rerunOf, prefill }: Props) {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Une option indisponible reste visible, grisée, avec la raison.
  const modelChoices: Choice[] = useMemo(() => {
    if (modelStates)
      return modelStates.map((m) => ({
        value: m.profile,
        label: m.profile,
        available: m.ok,
        reason: m.ok ? null : m.detail,
      }));
    return (models?.profiles ?? []).map((p) => ({
      value: p,
      label: p,
      available: true,
    }));
  }, [models, modelStates]);
  const sourceChoices = sources?.choices ?? [];
  const modelValue = pick(modelChoices, model ?? stored.get("models"), models?.default);
  const sourceValue = pick(sourceChoices, source ?? stored.get("sources"), sources?.default);

  // Relance : question et choix d'origine (catégorie imposée ou corrigée), lancée quand l'utilisateur valide.
  useEffect(() => {
    if (!rerunOf) return;
    let cancelled = false;
    api<RunDetail>(`/api/runs/${rerunOf}`)
      .then(({ manifest }) => {
        if (cancelled) return;
        const c = manifest.category;
        const wantedCategory =
          c?.correction?.category ?? (c && ["user", "requalify"].includes(c.source ?? "") ? c.id : "");
        setQuestion(manifest.question);
        const wantedModel = manifest.models_profile ?? "";
        const wantedSources = (manifest.sources ?? []).join(",");
        const missing =
          (wantedModel && !modelChoices.some((m) => m.value === wantedModel && m.available)) ||
          (wantedSources && !sourceChoices.some((s) => s.value === wantedSources && s.available)) ||
          (wantedCategory && !categories.some((x) => x.id === wantedCategory));
        if (wantedModel) setModel(wantedModel);
        if (wantedSources) setSource(wantedSources);
        setCategory(categories.some((x) => x.id === wantedCategory) ? wantedCategory : "");
        setError(missing ? "Un choix d'origine n'est plus disponible : l'option par défaut est sélectionnée." : null);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
    // Les listes de choix arrivent après le premier rendu : on relit l'origine quand elles sont prêtes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerunOf, categories.length, modelChoices.length, sourceChoices.length]);

  // « Investiguer » une alerte : question préremplie, données maison si disponibles. L'état se met à jour
  // pendant le rendu quand un nouveau préremplissage arrive (pas d'effet en cascade) ; le focus, lui, est
  // un effet sur le DOM.
  const [appliedPrefill, setAppliedPrefill] = useState<number | null>(null);
  if (prefill && prefill.nonce !== appliedPrefill) {
    setAppliedPrefill(prefill.nonce);
    setQuestion(prefill.question);
    if (prefill.sources && sourceChoices.some((s) => s.value === prefill.sources && s.available))
      setSource(prefill.sources);
  }
  useEffect(() => {
    if (!prefill) return;
    document.getElementById("ask-question")?.focus();
    window.scrollTo(0, 0);
  }, [prefill]);

  const state = modelStates?.find((m) => m.profile === modelValue);
  const hint = [
    state
      ? Object.entries(state.roles)
          .map(([r, m]) => `${r} ${m}`)
          .join(" · ")
      : "",
    state && !state.ok ? `⚠ ${state.detail}` : "",
    sourceChoices.find((s) => s.value === sourceValue)?.reason ?? "",
  ]
    .filter(Boolean)
    .join(" — ");

  const cancelRerun = () => {
    setQuestion("");
    setCategory("");
    setError(null);
    location.hash = "";
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: AskBody = {
      question,
      models: modelValue || null,
      sources: sourceValue || null,
      category: category || null,
      rerun_of: rerunOf,
    };
    try {
      const { run_id } = await post<{ run_id: string }>("/api/runs", body);
      location.href = legacyRunHref(run_id); // lot 0a : l'investigation s'ouvre dans l'interface actuelle
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <form className="card ask" onSubmit={submit} aria-labelledby="ask-title">
      <h2 id="ask-title" className="visually-hidden">
        Poser une question
      </h2>
      {rerunOf && (
        <p className="banner">
          <span>
            Relance de{" "}
            <a href={legacyRunHref(rerunOf)} className="mono">
              {rerunOf}
            </a>{" "}
            : modifie la question ou les options, puis lance.
          </span>
          <button type="button" className="link" onClick={cancelRerun}>
            Annuler la relance
          </button>
        </p>
      )}
      <textarea
        id="ask-question"
        name="question"
        rows={3}
        placeholder="Pose une question sur la production…"
        aria-label="Question"
        required
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <div className="ask-row">
        <label>
          Modèle
          <select
            value={modelValue}
            onChange={(e) => {
              setModel(e.target.value);
              stored.set("models", e.target.value);
            }}
          >
            {modelChoices.map((c) => (
              <option key={c.value} value={c.value} disabled={!c.available} title={c.reason ?? ""}>
                {c.label}
                {c.available ? "" : " — indisponible"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Données
          <select
            value={sourceValue}
            onChange={(e) => {
              setSource(e.target.value);
              stored.set("sources", e.target.value);
            }}
          >
            {sourceChoices.map((c) => (
              <option key={c.value} value={c.value} disabled={!c.available} title={c.reason ?? ""}>
                {c.label}
                {c.available ? "" : " — indisponible"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Catégorie
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">automatique</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id} title={c.description}>
                {c.id}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn primary" disabled={busy || !question.trim()}>
          {busy ? "Lancement…" : "Lancer l'investigation"}
        </button>
      </div>
      {hint && <p className="hint muted">{hint}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
