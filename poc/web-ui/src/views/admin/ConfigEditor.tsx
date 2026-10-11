// Éditeur de configuration : fichiers groupés, lecture seule selon le rôle, Vérifier sans écrire, Enregistrer
// avec commentaire (refus si invalide ou modifié entre-temps), historique avec écart et reprise d'une version.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../../api/client";
import type { ConfigContent, ConfigList, ConfigVersion } from "../../api/types";
import { fmtDate } from "../../lib/format";

interface Editing {
  path: string;
  version: string | null;
  content: string;
  editable: boolean;
  isNew: boolean;
}

const stampDate = (id: string) =>
  fmtDate(id.replace(/^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)\d*Z$/, "$1-$2-$3T$4:$5:$6Z"));

export function ConfigEditor() {
  const [list, setList] = useState<ConfigList | null>(null);
  const [file, setFile] = useState<Editing | null>(null);
  const [text, setText] = useState("");
  const [comment, setComment] = useState("");
  const [newDir, setNewDir] = useState("");
  const [newName, setNewName] = useState("");
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [history, setHistory] = useState<ConfigVersion[]>([]);
  const [diff, setDiff] = useState<string | null>(null);

  const loadList = useCallback(
    () =>
      api<ConfigList>("/api/config")
        .then((l) => {
          setList(l);
          setNewDir((d) => d || l.creatable[0]?.pattern || "");
        })
        .catch((e: Error) => setMessage({ text: e.message, error: true })),
    [],
  );
  useEffect(() => {
    loadList();
  }, [loadList]);

  const dirty = !!file && file.editable && text !== file.content;
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => dirty && e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const loadHistory = (path: string) =>
    api<ConfigVersion[]>(`/api/config/history?path=${encodeURIComponent(path)}`)
      .then(setHistory)
      .catch(() => setHistory([]));

  const show = (f: Editing) => {
    setFile(f);
    setText(f.content);
    setComment("");
    setMessage(null);
    setDiff(null);
    if (f.isNew) setHistory([]);
    else loadHistory(f.path);
  };

  const open = async (path: string) => {
    if (dirty && !window.confirm("Abandonner les modifications non enregistrées ?")) return;
    try {
      const f = await api<ConfigContent>(`/api/config/file?path=${encodeURIComponent(path)}`);
      show({ path: f.path, version: f.version, content: f.content, editable: f.editable, isNew: false });
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    }
  };

  const target = () => (file?.isNew ? `${newDir.replace(/\/[^/]*$/, "")}/${newName.trim()}` : (file?.path ?? ""));

  const check = async () => {
    try {
      const r = await post<{ ok: boolean; error?: string }>("/api/config/validate", { path: target(), content: text });
      setMessage(r.ok ? { text: "Fichier valide.", error: false } : { text: r.error ?? "Invalide", error: true });
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    }
  };

  const save = async () => {
    if (!file) return;
    try {
      const path = target();
      const saved = await post<{ version: string }>("/api/config/file", {
        path,
        content: text,
        version: file.version,
        comment,
      });
      show({ path, version: saved.version, content: text, editable: true, isNew: false });
      setMessage({ text: "Enregistré. Les prochaines investigations utiliseront cette version.", error: false });
      loadList();
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    }
  };

  const version = async (v: ConfigVersion, restore: boolean) => {
    if (!file) return;
    try {
      const r = await api<{ content: string; diff: string }>(
        `/api/config/version?path=${encodeURIComponent(file.path)}&id=${encodeURIComponent(v.id)}`,
      );
      if (restore) {
        setText(r.content);
        setComment(`Retour à la version du ${stampDate(v.id)}`);
        setMessage({
          text: "Version reprise dans l'éditeur : vérifie puis enregistre pour la rétablir.",
          error: false,
        });
      } else setDiff(r.diff || "Identique au fichier actuel.");
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true });
    }
  };

  if (!list) return message ? <p className="error">{message.text}</p> : <div className="skeleton" aria-busy="true" />;
  const groups: Record<string, typeof list.files> = {};
  for (const f of list.files) (groups[f.group] ??= []).push(f);

  return (
    <div className="config-grid">
      <nav className="config-files" aria-label="Fichiers de configuration">
        {list.creatable.length > 0 && (
          <button
            type="button"
            className="link"
            onClick={() => {
              if (dirty && !window.confirm("Abandonner les modifications non enregistrées ?")) return;
              show({ path: "", version: null, content: "", editable: true, isNew: true });
            }}
          >
            Nouveau fichier…
          </button>
        )}
        {Object.entries(groups).map(([g, files]) => (
          <div key={g}>
            <h3>{g}</h3>
            <ul>
              {files.map((f) => (
                <li key={f.path}>
                  <button
                    type="button"
                    className={`file ${file?.path === f.path ? "active" : ""}`}
                    onClick={() => open(f.path)}
                    aria-current={file?.path === f.path}
                  >
                    {f.path}
                  </button>
                  {!f.editable && <span className="faint hint"> lecture</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      {file ? (
        <div className="config-editor">
          <div className="card-head">
            <h3>{file.isNew ? "Nouveau fichier" : file.path}</h3>
            <span className="tag">{file.editable ? "modifiable" : "lecture seule"}</span>
          </div>
          {file.isNew && (
            <div className="filters">
              <select aria-label="Dossier" value={newDir} onChange={(e) => setNewDir(e.target.value)}>
                {list.creatable.map((c) => (
                  <option key={c.pattern} value={c.pattern}>
                    {c.pattern}
                  </option>
                ))}
              </select>
              <input
                placeholder="nom-du-fichier.yaml"
                aria-label="Nom du fichier"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
          )}
          <textarea
            className="code"
            spellCheck={false}
            rows={26}
            aria-label="Contenu du fichier"
            value={text}
            readOnly={!file.editable}
            onChange={(e) => setText(e.target.value)}
          />
          {file.editable && (
            <div className="ask-row">
              <input
                className="grow"
                placeholder="Commentaire obligatoire : pourquoi ce changement ?"
                aria-label="Commentaire"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <button type="button" className="btn" onClick={check}>
                Vérifier
              </button>
              <button type="button" className="btn primary" onClick={save}>
                Enregistrer
              </button>
              <button type="button" className="link" onClick={() => (setText(file.content), setMessage(null))}>
                Annuler les modifications
              </button>
            </div>
          )}
          {message && (
            <p className={message.error ? "error" : "muted"} role={message.error ? "alert" : "status"}>
              {message.text}
            </p>
          )}
          {!file.isNew && (
            <details>
              <summary>Historique</summary>
              <ul className="config-history">
                {history.length ? (
                  history.map((v) => (
                    <li key={v.id}>
                      <span className="num">{stampDate(v.id)}</span> <strong>{v.author ?? "origine"}</strong>{" "}
                      <span>{v.comment}</span>
                      <button type="button" className="link" onClick={() => version(v, false)}>
                        Écart avec l'actuel
                      </button>
                      {file.editable && (
                        <button type="button" className="link" onClick={() => version(v, true)}>
                          Reprendre cette version
                        </button>
                      )}
                    </li>
                  ))
                ) : (
                  <li className="muted">Jamais modifié depuis l'interface.</li>
                )}
              </ul>
              {diff && (
                <pre className="config-diff">
                  {diff.split("\n").map((line, i) => (
                    <span key={i} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : undefined}>
                      {line}
                      {"\n"}
                    </span>
                  ))}
                </pre>
              )}
            </details>
          )}
        </div>
      ) : (
        <p className="muted">Choisis un fichier à gauche.</p>
      )}
    </div>
  );
}
