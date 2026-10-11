// Panneaux de l'investigation : catégorie (corriger, relancer avec), avis sur le diagnostic, précision.
import { useState } from "react";
import { post } from "../../api/client";
import type { Category, FullManifest } from "../../api/types";
import { ENDED } from "../../lib/format";

const MODES: Record<string, string> = {
  playbook: "playbook appliqué",
  combined: "deux playbooks combinés",
  clarify: "précision demandée",
  generic: "stratégie générique",
};
const CONFIDENCE: Record<string, string> = { low: "faible", medium: "moyenne", high: "élevée" };

interface CategoryProps {
  manifest: FullManifest;
  categories: Category[];
  canCorrect: boolean;
  canAsk: boolean;
  onChanged: () => void;
  onRerun: (category: string) => Promise<void>;
}

export function CategoryBar({ manifest, categories, canCorrect, canAsk, onChanged, onRerun }: CategoryProps) {
  const c = manifest.category;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(c?.correction?.category ?? c?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  if (!c) return null;
  const playbooks = Object.entries(c.playbooks ?? {})
    .map(([id, v]) => `${id} v${v}`)
    .join(" + ");
  const parts = [`confiance ${CONFIDENCE[c.confidence ?? ""] ?? c.confidence ?? "?"}`, MODES[c.mode ?? ""] ?? c.mode];
  if (playbooks) parts.push(playbooks);
  if (c.source === "user") parts.push("choisie par l'utilisateur");
  if (c.history?.length) parts.push(`requalifiée depuis ${c.history.map((h) => h.from).join(", ")}`);
  if (c.correction) parts.push(`corrigée par ${c.correction.by} (classée ${c.id})`);
  if (c.error) parts.push(`classifieur : ${c.error}`);

  const save = async () => {
    setError(null);
    try {
      await post(`/api/runs/${manifest.run_id}/category`, { category: value });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const rerun = async () => {
    setError(null);
    try {
      await post(`/api/runs/${manifest.run_id}/category`, { category: value });
      await onRerun(value);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="category">
      <span>
        Catégorie <span className="tag strong">{c.correction?.category ?? c.id}</span>
      </span>
      <span className="muted hint">· {parts.filter(Boolean).join(" · ")}</span>
      {canCorrect && !editing && (
        <button type="button" className="link" onClick={() => setEditing(true)}>
          Corriger
        </button>
      )}
      {editing && (
        <span className="cat-form">
          <select aria-label="Catégorie" value={value} onChange={(e) => setValue(e.target.value)}>
            {categories.map((x) => (
              <option key={x.id} value={x.id} title={x.description}>
                {x.id}
              </option>
            ))}
          </select>
          <button type="button" className="btn" onClick={save}>
            Enregistrer
          </button>
          {canAsk && (
            <button type="button" className="btn" onClick={rerun}>
              Relancer avec cette catégorie
            </button>
          )}
          <button type="button" className="link" onClick={() => setEditing(false)}>
            Annuler
          </button>
        </span>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function FeedbackForm({
  manifest,
  canGive,
  onSent,
}: {
  manifest: FullManifest;
  canGive: boolean;
  onSent: () => void;
}) {
  const [verdict, setVerdict] = useState("");
  const [cause, setCause] = useState("");
  const [createCase, setCreateCase] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = manifest.feedback;
  if (f)
    return (
      <p className="muted">
        Avis de {f.by} : {f.verdict}
        {f.cause ? ` · cause réelle : ${f.cause}` : ""}
      </p>
    );
  if (!canGive || !ENDED.includes(manifest.status)) return null;
  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await post(`/api/runs/${manifest.run_id}/feedback`, { verdict, cause, create_case: createCase });
      onSent();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form className="feedback" onSubmit={send}>
      <span className="muted">Ce diagnostic était :</span>
      {["utile", "partiel", "faux"].map((v) => (
        <label key={v} className="check">
          <input
            type="radio"
            name="verdict"
            value={v}
            required
            checked={verdict === v}
            onChange={() => setVerdict(v)}
          />{" "}
          {v}
        </label>
      ))}
      <input
        placeholder="Cause réelle, si tu la connais"
        aria-label="Cause réelle"
        value={cause}
        onChange={(e) => setCause(e.target.value)}
      />
      <label className="check">
        <input type="checkbox" checked={createCase} onChange={(e) => setCreateCase(e.target.checked)} /> enregistrer
        comme cas confirmé
      </label>
      <button type="submit" className="btn">
        Envoyer l'avis
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export function PrecisionForm({ onRelaunch }: { onRelaunch: (precision: string) => Promise<void> }) {
  const [precision, setPrecision] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="precision"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await onRelaunch(precision.trim());
        } catch (err) {
          setError((err as Error).message);
        }
      }}
    >
      <input
        placeholder="Ta précision (par exemple : l'application Paiement)"
        aria-label="Précision"
        required
        value={precision}
        onChange={(e) => setPrecision(e.target.value)}
      />
      <button type="submit" className="btn primary">
        Préciser et relancer
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
