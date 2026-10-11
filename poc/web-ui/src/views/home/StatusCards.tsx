// État des modèles et des sources (vérification relançable), alertes en cours avec « Investiguer ».
import type { Alert, StatusResponse } from "../../api/types";
import { RefreshCw, TriangleAlert } from "../../components/icons";
import { StateBadge } from "../../components/StateBadge";
import { fmtDate } from "../../lib/format";

interface Props {
  status: StatusResponse | null;
  error: string | null;
  refreshing: boolean;
  onRefresh: () => void;
}

const unique = (values: string[]) => values.filter((v, i, a) => a.indexOf(v) === i);

export function StatusCard({ status, error, refreshing, onRefresh }: Props) {
  return (
    <section className="card" aria-labelledby="status-title" aria-busy={refreshing}>
      <div className="card-head">
        <h2 id="status-title">État</h2>
        <button
          type="button"
          className="btn ghost icon"
          onClick={onRefresh}
          disabled={refreshing}
          title="Vérifier à nouveau"
          aria-label="Vérifier à nouveau l'état"
        >
          <RefreshCw size={15} className={refreshing ? "spin" : undefined} aria-hidden="true" />
        </button>
      </div>
      {error ? (
        <p className="error">{error}</p>
      ) : !status ? (
        <p className="muted">Vérification des modèles et des sources…</p>
      ) : (
        <ul className="status-list">
          {status.models.map((m) => (
            <li key={`m-${m.profile}`}>
              <StateBadge state={m.ok ? "ok" : "bad"} label={m.ok ? "disponible" : "indisponible"} hideLabel />
              <strong>
                Modèles {m.profile}
                {m.default ? " (défaut)" : ""}
              </strong>
              <span className="detail">
                {unique(Object.values(m.roles)).join(", ")} · {m.detail}
              </span>
            </li>
          ))}
          {status.sources.map((s) => (
            <li key={`s-${s.name}`}>
              <StateBadge
                state={s.configured === false ? "off" : s.ok ? "ok" : "bad"}
                label={s.configured === false ? "non configurée" : s.ok ? "joignable" : "injoignable"}
                hideLabel
              />
              <strong>{s.name}</strong>
              <span className="detail">{s.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AlertsCard({
  alerts,
  canAsk,
  onInvestigate,
}: {
  alerts: Alert[];
  canAsk: boolean;
  onInvestigate: (a: Alert) => void;
}) {
  if (!alerts.length) return null;
  return (
    <section className="card" aria-labelledby="alerts-title">
      <h2 id="alerts-title">
        <TriangleAlert size={15} aria-hidden="true" />
        Alertes en cours <span className="faint">· maison</span>
      </h2>
      <ul className="alerts">
        {alerts.map((a, i) => (
          <li key={`${a.alertname}-${a.host}-${i}`}>
            <span className="sev" data-sev={a.severity ?? ""}>
              {a.severity || "?"}
            </span>
            <span>
              <strong>{a.alertname}</strong>
              {a.host ? ` · ${a.host}` : ""}{" "}
              <span className="muted">
                {a.summary || ""} · depuis {fmtDate(a.starts_at)}
              </span>
            </span>
            {canAsk && (
              <button type="button" className="link" onClick={() => onInvestigate(a)}>
                Investiguer
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
