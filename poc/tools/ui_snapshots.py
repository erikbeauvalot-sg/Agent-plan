"""Captures de l'interface pour vérifier un écran (outil de développement, hors dépendances du POC).

    uv run --with playwright python tools/ui_snapshots.py --base http://127.0.0.1:8765 --login admin --password …

Navigateur : celui de Playwright, ou un Chromium déjà installé (DIAGAGENT_BROWSER=/Applications/Vivaldi.app/
Contents/MacOS/Vivaldi). Captures dans poc/.snapshots/ (ignoré par git) : connexion et accueil, en 1440, 1024 et
390 px, thèmes sombre et clair, et une fois en mouvement réduit. Regarder les images avant de conclure.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

SIZES = {"1440": (1440, 900), "1024": (1024, 768), "390": (390, 844)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8080")
    p.add_argument("--path", default="/nouvelle")
    p.add_argument("--login", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / ".snapshots"))
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("DIAGAGENT_BROWSER") or None)
        for scheme in ("dark", "light"):
            for name, (w, h) in SIZES.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, locale="fr-FR")
                page = ctx.new_page()
                page.goto(args.base + args.path)
                page.wait_for_selector("form.login-card")
                page.screenshot(path=out / f"connexion-{scheme}-{name}.png")
                page.fill("input[name=login]", args.login)
                page.fill("input[name=password]", args.password)
                page.click("button[type=submit]")
                page.wait_for_selector("text=Dernières investigations")
                page.wait_for_load_state("networkidle")
                page.screenshot(path=out / f"accueil-{scheme}-{name}.png", full_page=True)
                ctx.close()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(args.base + args.path)
        page.fill("input[name=login]", args.login)
        page.fill("input[name=password]", args.password)
        page.click("button[type=submit]")
        page.wait_for_selector("text=Dernières investigations")
        page.screenshot(path=out / "accueil-mouvement-reduit.png")
        browser.close()
    print(f"Captures dans {out}")


if __name__ == "__main__":
    main()
