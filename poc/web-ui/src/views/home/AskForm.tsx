// Question en héros (Entrée lance, Maj+Entrée passe à la ligne), options en puces (modèle, données,
// catégorie), suggestions quand le champ est vide ; relance avec les choix d'une investigation d'origine.
import { useEffect, useMemo, useState } from "react";
import { api, post } from "../../api/client";
import type { Alert, AskBody, Category, Choice, ModelState, RunDetail, SourcesResponse } from "../../api/types";
import { ArrowUp, History, Lightbulb, LoaderCircle, TriangleAlert } from "../../components/icons";
import { ChipSelect } from "../../components/Popover";
import { alertQuestion, consumedPrefill, markPrefillConsumed, usePrefill } from "../../lib/prefill";
import { runHref } from "../../lib/route";
import { stored } from "../../lib/storage";

interface Suggestion {
  kind: "alert" | "recent" | "example";
  text: string;
  question: string;
  sources?: string;
}

interface Props {
  categories: Category[];
  models: { profiles: string[]; default: string } | null;
  modelStates: ModelState[] | null;
  sources: SourcesResponse | null;
  rerunOf: string | null;
  alerts: Alert[];
  recent: string[];
}

// Pas de focus automatique sur écran tactile : le clavier virtuel masquerait l'accueil.
const autoFocus = typeof matchMedia !== "undefined" && matchMedia("(pointer: fine)").matches;

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

export function AskForm({ categories, models, modelStates, sources, rerunOf, alerts, recent }: Props) {
  const prefill = usePrefill();
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
  const [appliedPrefill, setAppliedPrefill] = useState<number | null>(consumedPrefill);
  if (prefill && prefill.nonce !== appliedPrefill) {
    setAppliedPrefill(prefill.nonce);
    markPrefillConsumed(prefill.nonce);
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
  const modelHint = state
    ? [
        Object.entries(state.roles)
          .map(([r, m]) => `${r} ${m}`)
          .join(" · "),
        state.ok ? "" : `⚠ ${state.detail}`,
      ]
        .filter(Boolean)
        .join(" — ")
    : "";
  const sourceReason = sourceChoices.find((s) => s.value === sourceValue)?.reason ?? "";

  const cancelRerun = () => {
    setQuestion("");
    setCategory("");
    setError(null);
    location.hash = "";
  };

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (busy || !question.trim()) return;
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
      location.hash = run_id;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  // Suggestions quand le champ est vide : alertes en cours, dernières questions, exemples des playbooks.
  const suggestions: Suggestion[] = [
    ...alerts.slice(0, 2).map((a) => ({
      kind: "alert" as const,
      text: `${a.alertname}${a.host ? ` · ${a.host}` : ""}`,
      question: alertQuestion(a),
      sources: "maison",
    })),
    ...recent.slice(0, 2).map((q) => ({ kind: "recent" as const, text: q, question: q })),
    ...categories
      .map((c) => c.examples?.[0])
      .filter((q): q is string => !!q && !recent.includes(q))
      .slice(0, 3)
      .map((q) => ({ kind: "example" as const, text: q, question: q })),
  ];
  const applySuggestion = (s: Suggestion) => {
    setQuestion(s.question);
    if (s.sources && sourceChoices.some((c) => c.value === s.sources && c.available)) setSource(s.sources);
    document.getElementById("ask-question")?.focus();
  };

  const categoryOptions = [
    { value: "", label: "automatique", hint: "l'agent classe la demande" },
    ...categories.map((c) => ({ value: c.id, label: c.id, hint: c.description })),
  ];

  return (
    <form className="ask-hero" onSubmit={submit} aria-labelledby="ask-title">
      <h1 id="ask-title">Que se passe-t-il en production&nbsp;?</h1>
      {rerunOf && (
        <p className="banner">
          <span>
            Relance de{" "}
            <a href={runHref(rerunOf)} className="mono">
              {rerunOf}
            </a>{" "}
            : modifie la question ou les options, puis lance.
          </span>
          <button type="button" className="link" onClick={cancelRerun}>
            Annuler la relance
          </button>
        </p>
      )}
      <div className="ask-field">
        <textarea
          id="ask-question"
          name="question"
          rows={2}
          placeholder={
            "Pose une question\u00a0: «\u00a0pourquoi le service Paiement est lent depuis hier soir\u00a0?\u00a0»"
          }
          aria-label="Question"
          aria-describedby="ask-keys"
          required
          autoFocus={autoFocus}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <button
          type="submit"
          className="btn primary ask-go"
          disabled={busy || !question.trim()}
          aria-label="Lancer l'investigation"
        >
          {busy ? (
            <LoaderCircle size={16} className="spin" aria-hidden="true" />
          ) : (
            <ArrowUp size={16} aria-hidden="true" />
          )}
          <span className="label-long">{busy ? "Lancement…" : "Lancer"}</span>
        </button>
      </div>
      <div className="ask-options">
        <ChipSelect
          label="Modèle"
          display={modelValue}
          options={modelChoices.map((c) => ({
            value: c.value,
            label: c.label,
            disabled: !c.available,
            hint: c.available ? null : (c.reason ?? "indisponible"),
          }))}
          selected={[modelValue]}
          onSelect={(v) => {
            setModel(v);
            stored.set("models", v);
          }}
        />
        <ChipSelect
          label="Données"
          display={sourceChoices.find((c) => c.value === sourceValue)?.label ?? sourceValue}
          options={sourceChoices.map((c) => ({
            value: c.value,
            label: c.label,
            disabled: !c.available,
            hint: c.available ? null : (c.reason ?? "indisponible"),
          }))}
          selected={[sourceValue]}
          onSelect={(v) => {
            setSource(v);
            stored.set("sources", v);
          }}
        />
        <ChipSelect
          label="Catégorie"
          display={category || "automatique"}
          active={!!category}
          onClear={() => setCategory("")}
          options={categoryOptions}
          selected={[category]}
          onSelect={setCategory}
        />
        <span id="ask-keys" className="faint ask-keys">
          <kbd>Entrée</kbd> lance · <kbd>Maj</kbd>+<kbd>Entrée</kbd> nouvelle ligne
        </span>
      </div>
      {(modelHint || sourceReason) && (
        <p className="hint muted">{[modelHint, sourceReason].filter(Boolean).join(" — ")}</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!question.trim() && suggestions.length > 0 && (
        <ul className="suggestions" aria-label="Suggestions">
          {suggestions.map((s) => (
            <li key={`${s.kind}-${s.question}`}>
              <button type="button" className="suggestion" data-kind={s.kind} onClick={() => applySuggestion(s)}>
                {s.kind === "alert" ? (
                  <TriangleAlert size={13} aria-hidden="true" />
                ) : s.kind === "recent" ? (
                  <History size={13} aria-hidden="true" />
                ) : (
                  <Lightbulb size={13} aria-hidden="true" />
                )}
                <span className="visually-hidden">
                  {s.kind === "alert"
                    ? "Alerte en cours : "
                    : s.kind === "recent"
                      ? "Question récente : "
                      : "Exemple : "}
                </span>
                {s.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
