// Barre du haut : marque, heure de référence figée, thème, utilisateur, administration, déconnexion.
import { useState } from "react";
import { post } from "../api/client";
import type { Me } from "../api/types";
import { fmtDate, fmtUtc } from "../lib/format";
import { legacyAdminHref } from "../lib/route";
import { applyTheme, effectiveTheme, loadTheme, nextTheme, type ThemeChoice } from "../lib/theme";
import { Activity, Clock, LogOut, Monitor, Moon, Settings, Sun } from "./icons";

const ADMIN_PERMISSIONS = ["review", "view_indicators", "view_costs", "view_access_log", "view_config", "manage_users"];
const THEME_LABEL: Record<ThemeChoice, string> = {
  system: "thème du système",
  dark: "thème sombre",
  light: "thème clair",
};

export function TopBar({ me }: { me: Me }) {
  const [theme, setTheme] = useState<ThemeChoice>(loadTheme);
  const canAdmin = ADMIN_PERMISSIONS.some((p) => me.permissions.includes(p));
  const ThemeIcon = theme === "system" ? Monitor : effectiveTheme(theme) === "dark" ? Moon : Sun;
  const next = nextTheme(theme);

  const switchTheme = () => {
    applyTheme(next);
    setTheme(next);
  };
  const logout = async () => {
    await post("/api/logout").catch(() => {});
    location.replace("/nouvelle"); // page rechargée : aucun état de la session précédente
  };

  return (
    <header className="topbar">
      <a href="#" className="brand" aria-label="Agent de diagnostic, accueil">
        <Activity size={18} strokeWidth={2} aria-hidden="true" />
        <span className="brand-name">Agent de diagnostic</span>
      </a>
      {me.reference_time && (
        <span className="ref-time" title={`Heure de référence figée : ${me.reference_time} (UTC)`}>
          <Clock size={13} aria-hidden="true" />
          <span className="label-long">Heure de référence figée : </span>
          <span className="label-short">Réf. </span>
          <span className="num">{fmtDate(me.reference_time)}</span>
          <span className="faint num">({fmtUtc(me.reference_time)} UTC)</span>
        </span>
      )}
      <span className="spacer" />
      <nav aria-label="Compte">
        <span className="who">
          {me.display_name} · {me.roles.join(", ")}
        </span>
        <button
          type="button"
          className="btn ghost icon"
          onClick={switchTheme}
          title={`Affichage : ${THEME_LABEL[theme]} (passer au ${THEME_LABEL[next]})`}
          aria-label={`Passer au ${THEME_LABEL[next]}`}
        >
          <ThemeIcon size={16} aria-hidden="true" />
        </button>
        {canAdmin && (
          <a className="btn ghost" href={legacyAdminHref}>
            <Settings size={16} aria-hidden="true" />
            <span className="label-long">Administration</span>
          </a>
        )}
        <button type="button" className="btn ghost" onClick={logout}>
          <LogOut size={16} aria-hidden="true" />
          <span className="label-long">Se déconnecter</span>
        </button>
      </nav>
    </header>
  );
}
