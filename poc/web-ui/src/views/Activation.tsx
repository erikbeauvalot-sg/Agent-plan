// Activation d'un compte (ou nouveau mot de passe) par le lien à usage unique reçu de l'administrateur :
// l'utilisateur choisit son mot de passe, vérifié par la passerelle (longueur, mots de passe compromis,
// identifiant), puis la session s'ouvre. Écran accessible sans être connecté (#activation/<jeton>).
import { useEffect, useState } from "react";
import { api, post } from "../api/client";
import { Activity, Eye, EyeOff } from "../components/icons";
import { fmtDate } from "../lib/format";

interface Info {
  login: string;
  display_name?: string | null;
  expires_at: string;
}

export function Activation({ token, onActivated }: { token: string; onActivated: () => void }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Info>(`/api/activation/${encodeURIComponent(token)}`)
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, [token]);

  const mismatch = confirm.length > 0 && confirm !== password;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await post("/api/activation", { token, password });
      onActivated(); // l'accueil remplace le lien dans l'adresse (le jeton ne reste pas dans l'historique)
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <section className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1 className="brand">
          <Activity size={22} strokeWidth={2} aria-hidden="true" />
          Agent de diagnostic
        </h1>
        {!info && !error && <div className="skeleton" aria-busy="true" />}
        {info && (
          <>
            <p>
              Bienvenue{info.display_name ? `, ${info.display_name}` : ""}. Choisis le mot de passe du compte{" "}
              <strong className="mono">{info.login}</strong>.
            </p>
            <input type="text" name="username" value={info.login} autoComplete="username" readOnly hidden />
            <label>
              Nouveau mot de passe
              <span className="password">
                <input
                  type={shown ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  minLength={12}
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="btn icon"
                  onClick={() => setShown((s) => !s)}
                  aria-label={shown ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                  aria-pressed={shown}
                >
                  {shown ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
                </button>
              </span>
            </label>
            <label>
              Confirmation
              <input
                type={shown ? "text" : "password"}
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                aria-invalid={mismatch}
              />
            </label>
            <p className="faint hint">
              12 caractères au moins ; une phrase de plusieurs mots est plus sûre et plus facile à retenir. Les mots de
              passe compromis connus et ceux qui contiennent ton identifiant sont refusés. Lien valable jusqu'au{" "}
              {fmtDate(info.expires_at)}.
            </p>
            {mismatch && <p className="error">Les deux saisies diffèrent.</p>}
            <button type="submit" className="btn primary" disabled={busy || mismatch || password.length < 12}>
              {busy ? "Activation…" : "Activer et se connecter"}
            </button>
          </>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {error && !info && (
          <a href="/" className="link">
            Aller à la connexion
          </a>
        )}
      </form>
    </section>
  );
}
