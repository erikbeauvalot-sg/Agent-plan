// Thème : suit le réglage du système par défaut ; la bascule force sombre ou clair et est retenue.
import { stored } from "./storage";

export type ThemeChoice = "system" | "dark" | "light";

export function loadTheme(): ThemeChoice {
  const v = stored.get("theme");
  return v === "dark" || v === "light" ? v : "system";
}

export function applyTheme(choice: ThemeChoice): void {
  if (choice === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", choice);
  stored.set("theme", choice);
}

/** Thème réellement affiché, pour choisir l'icône de la bascule. */
export function effectiveTheme(choice: ThemeChoice): "dark" | "light" {
  if (choice !== "system") return choice;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/** Système → l'inverse de ce qui est affiché → système : deux clics suffisent pour revenir au réglage du poste. */
export function nextTheme(choice: ThemeChoice): ThemeChoice {
  if (choice === "system") return effectiveTheme("system") === "dark" ? "light" : "dark";
  return "system";
}
