// Palette de commandes (Ctrl+K ou ⌘K, partout) : poser une question, ouvrir une investigation récente,
// investiguer une alerte, relancer, aller à l'administration, changer de thème. Recherche floue, flèches,
// Entrée ; <dialog> natif (focus piégé, Échap ferme, le focus revient où il était).
import { useEffect, useId, useMemo, useRef, useState, type ComponentType } from "react";
import { api, post } from "../api/client";
import type { Me, RunRow, StatusResponse } from "../api/types";
import { fmtDate, statusLabel } from "../lib/format";
import { fuzzyFilter } from "../lib/fuzzy";
import { alertQuestion, requestPrefill } from "../lib/prefill";
import { adminHref, runHref, type Route } from "../lib/route";
import type { ThemeChoice } from "../lib/theme";
import {
  CornerDownLeft,
  History,
  Lightbulb,
  LogOut,
  Monitor,
  Moon,
  Play,
  RefreshCw,
  Search,
  Settings,
  Sun,
  TriangleAlert,
} from "./icons";

interface Command {
  id: string;
  group: string;
  label: string;
  detail?: string;
  keys?: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: boolean | "true" }>;
  run: () => void;
}

interface Props {
  me: Me;
  open: boolean;
  route: Route;
  canAdmin: boolean;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  onClose: () => void;
}

export const SHORTCUTS: [string, string][] = [
  ["Ctrl K", "palette de commandes"],
  ["/", "aller à la question"],
  ["g h", "accueil"],
  ["g a", "administration"],
  ["Entrée", "lancer la question"],
  ["Maj Entrée", "nouvelle ligne"],
  ["Échap", "fermer"],
];

export function CommandPalette({ me, open, route, canAdmin, theme, onTheme, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const origin = useRef<Element | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const listId = useId();
  const canAsk = me.permissions.includes("ask");

  // Ouverture : la saisie repart de zéro, les investigations et alertes sont relues.
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      origin.current = document.activeElement;
      dialog.showModal();
      api<RunRow[]>("/api/runs?limit=40")
        .then(setRuns)
        .catch(() => setRuns([]));
      api<StatusResponse>("/api/status")
        .then(setStatus)
        .catch(() => setStatus(null));
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const close = () => {
    onClose();
    setQuery("");
    setActive(0);
    (origin.current as HTMLElement | null)?.focus?.();
  };
  const go = (hash: string) => () => {
    location.hash = hash;
  };

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [];
    if (canAsk) {
      const typed = query.trim();
      list.push({
        id: "ask",
        group: "Actions",
        label: typed ? `Poser la question « ${typed} »` : "Poser une question",
        detail: typed ? "préremplie, à lancer depuis l'accueil" : undefined,
        keys: "/",
        icon: Lightbulb,
        run: () => (typed ? requestPrefill({ question: typed }) : focusQuestion()),
      });
      if (route.view === "run")
        list.push({
          id: "rerun",
          group: "Actions",
          label: "Relancer cette investigation…",
          icon: RefreshCw,
          run: go(`relance/${route.runId}`),
        });
    }
    list.push({ id: "home", group: "Aller à", label: "Accueil", keys: "g h", icon: History, run: go("") });
    if (canAdmin)
      list.push({
        id: "admin",
        group: "Aller à",
        label: "Administration",
        keys: "g a",
        icon: Settings,
        run: go(adminHref.slice(1)),
      });
    for (const r of runs.filter((r, i) => runs.findIndex((x) => x.question === r.question) === i))
      list.push({
        id: `run-${r.run_id}`,
        group: "Investigations récentes",
        label: r.question,
        detail: `${statusLabel(r.status)} · ${fmtDate(r.started_at)}${r.user !== me.login ? ` · ${r.user}` : ""}`,
        icon: r.status === "running" ? Play : Search,
        run: go(runHref(r.run_id).slice(1)),
      });
    if (canAsk)
      for (const [i, a] of (status?.alerts ?? []).entries())
        list.push({
          id: `alert-${i}`,
          group: "Alertes en cours",
          label: `Investiguer ${a.alertname}${a.host ? ` sur ${a.host}` : ""}`,
          detail: a.summary ?? undefined,
          icon: TriangleAlert,
          run: () => requestPrefill({ question: alertQuestion(a), sources: "maison" }),
        });
    const themes: [ThemeChoice, string, Command["icon"]][] = [
      ["system", "Thème du système", Monitor],
      ["dark", "Thème sombre", Moon],
      ["light", "Thème clair", Sun],
    ];
    for (const [t, label, icon] of themes)
      list.push({
        id: `theme-${t}`,
        group: "Affichage",
        label,
        detail: t === theme ? "actuel" : undefined,
        icon,
        run: () => onTheme(t),
      });
    list.push({
      id: "logout",
      group: "Compte",
      label: "Se déconnecter",
      icon: LogOut,
      run: () => {
        void post("/api/logout")
          .catch(() => {})
          .then(() => location.replace("/"));
      },
    });
    return list;
  }, [canAsk, canAdmin, route, runs, status, theme, onTheme, query, me.login]);

  // La question tapée reste toujours proposée en premier ; le reste est trié par la recherche floue.
  const shown = useMemo(() => {
    const [ask, ...rest] = commands[0]?.id === "ask" ? commands : [undefined, ...commands];
    const found = fuzzyFilter(rest as Command[], query, (c) => `${c.label} ${c.detail ?? ""} ${c.group}`).slice(0, 30);
    return ask ? [ask, ...found] : found;
  }, [commands, query]);
  const current = Math.min(active, Math.max(0, shown.length - 1));

  const runCommand = (c: Command | undefined) => {
    if (!c) return;
    close();
    c.run();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = shown.length;
      if (n) setActive((current + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
    } else if (e.key === "Enter") {
      e.preventDefault();
      runCommand(shown[current]);
    }
  };

  // L'élément actif reste visible quand on descend dans la liste.
  useEffect(() => {
    document.getElementById(`${listId}-${current}`)?.scrollIntoView({ block: "nearest" });
  }, [current, listId]);

  return (
    <dialog
      ref={ref}
      className="palette"
      aria-label="Palette de commandes"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => e.target === ref.current && close()}
    >
      <div className="palette-search">
        <Search size={16} aria-hidden="true" />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={shown.length ? `${listId}-${current}` : undefined}
          aria-label="Rechercher une commande, une investigation ou une alerte"
          placeholder={
            canAsk ? "Une commande, une investigation, ou une question à poser…" : "Une commande ou une investigation…"
          }
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <kbd>Échap</kbd>
      </div>
      <ul className="palette-list" id={listId} role="listbox" aria-label="Résultats">
        {shown.map((c, i) => {
          const header = c.group !== shown[i - 1]?.group ? c.group : null;
          const Icon = c.icon;
          return (
            <li key={c.id} role="presentation">
              {header && (
                <div className="palette-group" role="presentation">
                  {header}
                </div>
              )}
              <div
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === current}
                className="palette-item"
                onPointerMove={() => i !== current && setActive(i)}
                onClick={() => runCommand(c)}
              >
                <Icon size={15} aria-hidden="true" />
                <span className="palette-label">
                  <span>{c.label}</span>
                  {c.detail && <span className="faint">{c.detail}</span>}
                </span>
                {c.keys && <kbd>{c.keys}</kbd>}
                {i === current && <CornerDownLeft size={14} className="faint" aria-hidden="true" />}
              </div>
            </li>
          );
        })}
        {!shown.length && <li className="palette-empty muted">Aucun résultat.</li>}
      </ul>
      <footer className="palette-foot faint">
        {SHORTCUTS.map(([k, label]) => (
          <span key={k}>
            <kbd>{k}</kbd> {label}
          </span>
        ))}
      </footer>
    </dialog>
  );
}

/** Champ de question de l'accueil : y aller (et y revenir depuis une autre vue). */
export function focusQuestion(): void {
  const field = document.getElementById("ask-question");
  if (field) {
    field.focus();
    field.scrollIntoView({ block: "center" });
    return;
  }
  location.hash = "";
  requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById("ask-question")?.focus()));
}
