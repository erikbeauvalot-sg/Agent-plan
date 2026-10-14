"""Captures de l'interface et audit d'accessibilité (outil de développement, hors dépendances du POC).

    uv run --with playwright playwright install chromium        # une fois
    uv run --with playwright python tools/ui_snapshots.py --base http://127.0.0.1:8080 --login … --password … \
        --run 20261011T142151Z-dae2 [--axe]

Captures dans poc/.snapshots/ (ignoré par git) : connexion, accueil, palette de commandes, investigation (--run),
tiroir de l'agent (onglets Résumé et Appels), chaque onglet de l'administration ; en 1440, 1024 et 390 px,
thèmes sombre et clair, et l'accueil en mouvement réduit. Regarder les images avant de conclure.

--axe : audit axe-core sur chaque écran, en 1440 px et dans les deux thèmes (axe injecté depuis
web-ui/node_modules après `npm install` : jamais en production). Rapport des violations « serious » et
« critical » ; code de sortie 1 s'il y en a.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

SIZES = {"1440": (1440, 900), "1024": (1024, 768), "390": (390, 844)}
AXE = Path(__file__).resolve().parents[1] / "web-ui" / "node_modules" / "axe-core" / "axe.min.js"
AXE_RUN = """async () => {
  const r = await axe.run(document, {resultTypes: ['violations']});
  return r.violations.filter(v => ['serious', 'critical'].includes(v.impact))
    .map(v => `${v.impact} ${v.id} : ${v.help} — ${v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' ; ')}`);
}"""


def login(page: Page, base: str, user: str, password: str) -> None:
    page.goto(base + "/")
    page.wait_for_selector("form.login-card")
    page.fill("input[name=login]", user)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_selector("#runs-title, #welcome-title")
    page.wait_for_load_state("networkidle")


class Shots:
    def __init__(self, out: Path, axe: bool):
        self.out, self.axe, self.violations = out, axe, {}

    def take(self, page: Page, name: str, tag: str, audit: bool, full: bool = False) -> None:
        page.wait_for_timeout(450)  # fin des animations d'ouverture : capture nette, contrastes justes
        page.screenshot(path=self.out / f"{name}-{tag}.png", full_page=full)
        if self.axe and audit:
            page.add_script_tag(path=str(AXE))
            found = page.evaluate(AXE_RUN)
            if found:
                self.violations[f"{name}-{tag}"] = found


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8080")
    p.add_argument("--login", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--run", help="investigation terminée à capturer (run_id)")
    p.add_argument("--axe", action="store_true", help="audit d'accessibilité axe-core")
    p.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / ".snapshots"))
    args = p.parse_args()
    if args.axe and not AXE.exists():
        sys.exit(f"axe-core introuvable ({AXE}) : lancer `npm install` dans web-ui")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = Shots(out, args.axe)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("DIAGAGENT_BROWSER") or None)
        for scheme in ("dark", "light"):
            for name, (w, h) in SIZES.items():
                tag, audit = f"{scheme}-{name}", name == "1440"
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, locale="fr-FR")
                page = ctx.new_page()
                page.goto(args.base + "/")
                page.wait_for_selector("form.login-card")
                shots.take(page, "connexion", tag, audit)
                login(page, args.base, args.login, args.password)
                shots.take(page, "accueil", tag, audit, full=True)
                page.keyboard.press("Control+k")
                page.wait_for_selector(".palette[open] .palette-item")
                shots.take(page, "palette", tag, audit)
                page.keyboard.press("Escape")
                if args.run:
                    page.goto(f"{args.base}/#{args.run}")
                    page.wait_for_selector(".agent-node")
                    page.wait_for_load_state("networkidle")
                    shots.take(page, "investigation", tag, audit, full=True)
                    page.locator(".agent-node").first.click()
                    page.wait_for_selector(".drawer [role=tablist]")
                    shots.take(page, "tiroir", tag, audit)
                    page.get_by_role("tab", name="Appels d'outils").click()
                    shots.take(page, "tiroir-appels", tag, False)
                    page.keyboard.press("Escape")
                page.goto(f"{args.base}/#admin")
                page.wait_for_selector("[role=tablist]")
                page.wait_for_load_state("networkidle")
                for label in [t.split("\n")[0] for t in page.locator("[role=tab]").all_inner_texts()]:
                    page.get_by_role("tab", name=label).click()
                    page.wait_for_load_state("networkidle")
                    slug = label.lower().replace(" ", "-").replace("à", "a").replace("û", "u")
                    shots.take(page, f"administration-{slug}", tag, audit, full=True)
                ctx.close()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        login(page, args.base, args.login, args.password)
        page.screenshot(path=out / "accueil-mouvement-reduit.png")
        browser.close()
    print(f"Captures dans {out}")
    if args.axe:
        for screen, found in shots.violations.items():
            print(f"[{screen}]")
            for line in found:
                print("   ", line)
        print(f"Accessibilité : {sum(map(len, shots.violations.values()))} violation(s) graves ou critiques")
        sys.exit(1 if shots.violations else 0)


if __name__ == "__main__":
    main()
