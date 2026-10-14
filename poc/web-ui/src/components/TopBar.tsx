// Barre du haut fine : marque, heure de référence figée, palette de commandes, thème, menu du compte
// (nom, rôles, administration, déconnexion).
import { useEffect } from "react";
import { post } from "../api/client";
import type { Me } from "../api/types";
import { useCurrentRun } from "../lib/currentRun";
import { fmtDate, fmtUtc } from "../lib/format";
import { adminHref } from "../lib/route";
import { effectiveTheme, nextTheme, type ThemeChoice } from "../lib/theme";
import { Activity, Clock, LogOut, Monitor, Moon, Search, Settings, Sun } from "./icons";
import { onMenuKeys, usePopover } from "./Popover";
import { StateBadge } from "./StateBadge";

export const ADMIN_PERMISSIONS = [
  "review",
  "view_indicators",
  "view_costs",
  "view_access_log",
  "view_config",
  "manage_users",
];
const THEME_LABEL: Record<ThemeChoice, string> = {
  system: "thème du système",
  dark: "thème sombre",
  light: "thème clair",
};
export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

const initials = (name: string) =>
  name
    .replace(/[^\p{L}\s._-]/gu, "")
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

interface Props {
  me: Me;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  onPalette: () => void;
}

export function TopBar({ me, theme, onTheme, onPalette }: Props) {
  const canAdmin = ADMIN_PERMISSIONS.some((p) => me.permissions.includes(p));
  const ThemeIcon = theme === "system" ? Monitor : effectiveTheme(theme) === "dark" ? Moon : Sun;
  const next = nextTheme(theme);
  const { open, setOpen, rootRef, triggerRef } = usePopover();
  const run = useCurrentRun();
  useEffect(() => {
    if (open) document.querySelector<HTMLElement>(".account-menu [data-item]")?.focus();
  }, [open]);

  const logout = async () => {
    await post("/api/logout").catch(() => {});
    location.replace("/"); // page rechargée : aucun état de la session précédente
  };

  return (
    <header className="topbar">
      <a href="#" className="brand" aria-label="Agent de diagnostic, accueil">
        <Activity size={18} strokeWidth={2} aria-hidden="true" />
        <span className="brand-name">Agent de diagnostic</span>
      </a>
      {run && (
        <span className="topbar-run" title={run.question}>
          <StateBadge state={run.status} hideLabel />
          <span>{run.question}</span>
        </span>
      )}
      <span className="spacer" />
      {me.reference_time && (
        <span className="ref-time" title={`Heure de référence figée : ${me.reference_time} (UTC)`}>
          <Clock size={13} aria-hidden="true" />
          <span className="label-long">Heure de référence figée : </span>
          <span className="label-short">Réf. </span>
          <span className="num">{fmtDate(me.reference_time)}</span>
          <span className="faint num">({fmtUtc(me.reference_time)} UTC)</span>
        </span>
      )}
      <button type="button" className="palette-btn" onClick={onPalette} aria-keyshortcuts="Control+K Meta+K">
        <Search size={14} aria-hidden="true" />
        <span className="label-long">Rechercher ou lancer…</span>
        <kbd>{IS_MAC ? "⌘K" : "Ctrl K"}</kbd>
      </button>
      <button
        type="button"
        className="btn ghost icon"
        onClick={() => onTheme(next)}
        title={`Affichage : ${THEME_LABEL[theme]} (passer au ${THEME_LABEL[next]})`}
        aria-label={`Passer au ${THEME_LABEL[next]}`}
      >
        <ThemeIcon size={16} aria-hidden="true" />
      </button>
      <div className="menu-wrap" ref={rootRef}>
        <button
          type="button"
          ref={triggerRef}
          className="avatar"
          aria-expanded={open}
          aria-haspopup="menu"
          // Le nom accessible commence par le texte visible (WCAG 2.5.3) : « ET, compte de Erik… ».
          aria-label={`${initials(me.display_name || me.login)}, compte de ${me.display_name}`}
          onClick={() => setOpen(!open)}
        >
          {initials(me.display_name || me.login)}
        </button>
        {open && (
          <div className="chip-menu account-menu" role="menu" aria-label="Compte" onKeyDown={onMenuKeys}>
            <div className="account-who">
              <strong>{me.display_name}</strong>
              <span className="faint">
                {me.login} · {me.roles.join(", ")}
              </span>
            </div>
            {canAdmin && (
              <a role="menuitem" data-item="" href={adminHref} onClick={() => setOpen(false)}>
                <Settings size={15} aria-hidden="true" />
                Administration
              </a>
            )}
            <button type="button" role="menuitem" data-item="" onClick={logout}>
              <LogOut size={15} aria-hidden="true" />
              Se déconnecter
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
