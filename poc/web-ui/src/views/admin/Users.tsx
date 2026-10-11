// Comptes (Administrateur) : création, rôles, désactivation, nouveau mot de passe ; jamais d'empreinte.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../../api/client";
import type { Account } from "../../api/types";
import { fmtDate } from "../../lib/format";

const ROLES = ["lecteur", "operateur", "superviseur", "administrateur", "auditeur"];

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

function AccountRow({
  a,
  onDone,
  onError,
}: {
  a: Account;
  onDone: (msg: string) => void;
  onError: (msg: string) => void;
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
  return (
    <tr>
      <td>{a.login}</td>
      <td>{a.display_name}</td>
      <td>
        <RoleBoxes value={roles} onChange={setRoles} name={a.login} />{" "}
        <button type="button" className="link" onClick={() => update({ roles }, "Rôles enregistrés.")}>
          Enregistrer les rôles
        </button>
      </td>
      <td>
        {a.status === "active" ? "actif" : "désactivé"}
        {a.locked_until && <span className="faint"> (verrouillé jusqu'à {fmtDate(a.locked_until)})</span>}
      </td>
      <td>
        <button
          type="button"
          className="link"
          onClick={() => update({ status: a.status === "active" ? "disabled" : "active" }, "Compte mis à jour.")}
        >
          {a.status === "active" ? "Désactiver" : "Réactiver"}
        </button>{" "}
        <button
          type="button"
          className="link"
          onClick={() => {
            const password = window.prompt("Nouveau mot de passe (12 caractères minimum) :");
            if (password) update({ password }, "Mot de passe changé.");
          }}
        >
          Nouveau mot de passe…
        </button>
      </td>
    </tr>
  );
}

export function Users() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [login, setLogin] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState(["operateur"]);
  const [password, setPassword] = useState("");

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

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await post("/api/users", { login, display_name: name || null, roles, password });
      setLogin("");
      setName("");
      setPassword("");
      done("Compte créé.");
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
                <AccountRow key={`${a.id}-${a.roles.join(",")}-${a.status}`} a={a} onDone={done} onError={fail} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form className="ask-row" onSubmit={create}>
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
        <input
          type="password"
          placeholder="Mot de passe (12 caractères min.)"
          aria-label="Mot de passe"
          required
          minLength={12}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="btn">
          Créer le compte
        </button>
      </form>
      {message && (
        <p className={message.error ? "error" : "muted"} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      )}
    </>
  );
}
