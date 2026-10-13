// Comptes (Administrateur) : création par lien d'activation (l'utilisateur choisit son mot de passe, lien à
// usage unique valable 24 h), rôles, désactivation, nouveau lien en cas d'oubli ; jamais d'empreinte affichée.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../../api/client";
import type { Account, ActivationLink } from "../../api/types";
import { Check, Copy } from "../../components/icons";
import { fmtDate } from "../../lib/format";

const ROLES = ["lecteur", "operateur", "superviseur", "administrateur", "auditeur"];
const STATUS: Record<string, string> = { active: "actif", disabled: "désactivé", pending: "en attente d'activation" };

function RoleBoxes({ value, onChange, name }: { value: string[]; onChange: (v: string[]) => void; name: string }) {
  return (
    <span className="roles" role="group" aria-label={`Rôles de ${name}`}>
      {ROLES.map((r) => (
        <label key={r} className="check">
          <input
            type="checkbox"
            checked={value.includes(r)}
            onChange={(e) => onChange(e.target.checked ? [...value, r] : value.filter((x) => x !== r))}
          />{" "}
          {r}
        </label>
      ))}
    </span>
  );
}

/** Lien à transmettre à l'utilisateur (messagerie interne, en main propre) : jamais envoyé par la passerelle. */
function LinkBox({ login, link }: { login: string; link: ActivationLink }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="activation-link" role="status">
      <p>
        Lien d'activation de <strong>{login}</strong>, à lui transmettre : valable jusqu'au{" "}
        <span className="num">{fmtDate(link.expires_at)}</span>, une seule fois.
      </p>
      <span className="link-row">
        <input
          readOnly
          value={link.url}
          aria-label={`Lien d'activation de ${login}`}
          onFocus={(e) => e.target.select()}
        />
        <button
          type="button"
          className="btn"
          onClick={() =>
            navigator.clipboard
              .writeText(link.url)
              .then(() => setCopied(true))
              .catch(() => {})
          }
        >
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          {copied ? "Copié" : "Copier"}
        </button>
      </span>
    </div>
  );
}

function AccountRow({
  a,
  onDone,
  onError,
  onLink,
}: {
  a: Account;
  onDone: (msg: string) => void;
  onError: (msg: string) => void;
  onLink: (login: string, link: ActivationLink) => void;
}) {
  const [roles, setRoles] = useState(a.roles);
  const update = async (body: Record<string, unknown>, msg: string) => {
    try {
      await post(`/api/users/${a.id}`, body);
      onDone(msg);
    } catch (e) {
      onError((e as Error).message);
    }
  };
  const newLink = async () => {
    try {
      onLink(a.login, await post<ActivationLink>(`/api/users/${a.id}/activation-link`));
    } catch (e) {
      onError((e as Error).message);
    }
  };
  return (
    <tr>
      <td className="mono">{a.login}</td>
      <td>{a.display_name}</td>
      <td>
        <div className="role-cell">
          <RoleBoxes value={roles} onChange={setRoles} name={a.login} />
          {roles.join() !== a.roles.join() && (
            <button type="button" className="btn" onClick={() => update({ roles }, "Rôles enregistrés.")}>
              Enregistrer les rôles
            </button>
          )}
        </div>
      </td>
      <td>
        <span className="tag" data-status={a.status}>
          {STATUS[a.status] ?? a.status}
        </span>
        {a.status === "pending" && a.activation_expires_at && (
          <span className="faint"> · lien valable jusqu'au {fmtDate(a.activation_expires_at)}</span>
        )}
        {a.locked_until && <span className="faint"> · verrouillé jusqu'à {fmtDate(a.locked_until)}</span>}
      </td>
      <td className="row-actions">
        {a.status !== "pending" && (
          <button
            type="button"
            className="link"
            onClick={() => update({ status: a.status === "active" ? "disabled" : "active" }, "Compte mis à jour.")}
          >
            {a.status === "active" ? "Désactiver" : "Réactiver"}
          </button>
        )}
        {a.status !== "disabled" && (
          <button type="button" className="link" onClick={newLink}>
            {a.status === "pending" ? "Nouveau lien d'activation" : "Lien de nouveau mot de passe"}
          </button>
        )}
      </td>
    </tr>
  );
}

export function Users() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [link, setLink] = useState<{ login: string; link: ActivationLink } | null>(null);
  const [login, setLogin] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState(["operateur"]);

  const load = useCallback(
    () =>
      api<Account[]>("/api/users")
        .then(setAccounts)
        .catch((e: Error) => setMessage({ text: e.message, error: true })),
    [],
  );
  useEffect(() => {
    load();
  }, [load]);
  const done = (text: string) => (setMessage({ text, error: false }), load());
  const fail = (text: string) => setMessage({ text, error: true });
  const showLink = (who: string, l: ActivationLink) => {
    setLink({ login: who, link: l });
    setMessage(null);
    load();
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const created = await post<Account & { activation: ActivationLink | null }>("/api/users", {
        login,
        display_name: name || null,
        roles,
      });
      setLogin("");
      setName("");
      if (created.activation) showLink(created.login, created.activation);
      else done("Compte créé.");
    } catch (err) {
      fail((err as Error).message);
    }
  };

  return (
    <>
      {!accounts ? (
        <div className="skeleton" aria-busy="true" />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Identifiant</th>
                <th>Nom</th>
                <th>Rôles</th>
                <th>État</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <AccountRow
                  key={`${a.id}-${a.roles.join(",")}-${a.status}`}
                  a={a}
                  onDone={done}
                  onError={fail}
                  onLink={showLink}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {link && <LinkBox login={link.login} link={link.link} />}
      <form className="new-account" onSubmit={create}>
        <h3>Nouveau compte</h3>
        <input
          placeholder="Identifiant"
          aria-label="Identifiant"
          required
          pattern="[a-zA-Z0-9._\-]+"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
        />
        <input
          placeholder="Nom affiché"
          aria-label="Nom affiché"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <RoleBoxes value={roles} onChange={setRoles} name="nouveau compte" />
        <button type="submit" className="btn primary">
          Créer et obtenir le lien d'activation
        </button>
        <p className="faint hint">
          L'utilisateur choisit lui-même son mot de passe (12 caractères au moins, hors mots de passe compromis) avec le
          lien, valable 24 h et une seule fois. Aucun mot de passe ne passe par l'administrateur.
        </p>
      </form>
      {message && (
        <p className={message.error ? "error" : "muted"} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      )}
    </>
  );
}
