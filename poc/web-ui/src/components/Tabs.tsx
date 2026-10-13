// Onglets accessibles (motif ARIA « tabs ») : flèches gauche et droite, Début et Fin ; l'onglet actif seul est
// dans l'ordre de tabulation. Utilisés par l'administration et le tiroir d'agent.
import type { ReactNode } from "react";

export interface Tab {
  id: string;
  label: string;
  badge?: number | string | null;
}

export function Tabs({
  tabs,
  active,
  onChange,
  label,
  idPrefix,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  idPrefix: string;
}) {
  const move = (e: React.KeyboardEvent, i: number) => {
    const next =
      e.key === "ArrowRight"
        ? (i + 1) % tabs.length
        : e.key === "ArrowLeft"
          ? (i - 1 + tabs.length) % tabs.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? tabs.length - 1
              : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next]!.id);
    document.getElementById(`${idPrefix}-tab-${tabs[next]!.id}`)?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => (
        <button
          key={t.id}
          id={`${idPrefix}-tab-${t.id}`}
          type="button"
          role="tab"
          aria-selected={t.id === active}
          aria-controls={`${idPrefix}-panel-${t.id}`}
          tabIndex={t.id === active ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => move(e, i)}
        >
          {t.label}
          {t.badge !== null && t.badge !== undefined && t.badge !== 0 && <span className="tab-badge">{t.badge}</span>}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ idPrefix, id, children }: { idPrefix: string; id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} className="tab-panel">
      {children}
    </div>
  );
}
