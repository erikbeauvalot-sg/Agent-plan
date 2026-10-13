// Connexion : un vrai envoi de formulaire (POST /login puis redirection), pour que Entrée marche partout et
// que les gestionnaires de mots de passe reconnaissent la connexion. La page visée (#…) est conservée.
import { useEffect, useState } from "react";
import { Activity, Eye, EyeOff, Lock } from "../components/icons";

export function Login() {
  const [params] = useState(() => new URLSearchParams(location.search));
  const failed = params.has("echec");
  const locked = Number(params.get("verrou")) || null; // minutes restantes après 5 échecs
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (failed || locked) history.replaceState(null, "", "/" + location.hash); // adresse nettoyée, page visée gardée
  }, [failed, locked]);

  return (
    <section className="login">
      <form
        className="card login-card"
        method="post"
        action="/login"
        onSubmit={(e) => {
          (e.currentTarget.elements.namedItem("next") as HTMLInputElement).value = location.hash.slice(1);
        }}
      >
        <input type="hidden" name="next" />
        <h1 className="brand">
          <Activity size={22} strokeWidth={2} aria-hidden="true" />
          Agent de diagnostic
        </h1>
        <label>
          Identifiant
          <input name="login" autoComplete="username" required autoFocus />
        </label>
        <label>
          Mot de passe
          <span className="password">
            <input name="password" type={shown ? "text" : "password"} autoComplete="current-password" required />
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
        <button type="submit" className="btn primary">
          Se connecter
        </button>
        {locked ? (
          <p className="error" role="alert">
            <Lock size={14} aria-hidden="true" /> Compte verrouillé après 5 échecs : réessaie dans {locked} min, ou
            demande un lien de nouveau mot de passe à un administrateur.
          </p>
        ) : (
          failed && (
            <p className="error" role="alert">
              Identifiant ou mot de passe incorrect. Le compte est verrouillé 15 minutes après 5 échecs.
            </p>
          )
        )}
      </form>
    </section>
  );
}
