"""Captures de l'interface pour vérifier un écran (outil de développement, hors dépendances du POC).

    uv run --with playwright playwright install chromium        # une fois
    uv run --with playwright python tools/ui_snapshots.py --base http://127.0.0.1:8080 --login … --password … \
        --run 20261011T142151Z-dae2

Captures dans poc/.snapshots/ (ignoré par git) : connexion, accueil, palette de commandes, investigation (--run), tiroir de l'agent
principal, administration ; en 1440, 1024 et 390 px, thèmes sombre et clair, et l'accueil en mouvement réduit.
Regarder les images avant de conclure.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

SIZES = {"1440": (1440, 900), "1024": (1024, 768), "390": (390, 844)}


def login(page: Page, base: str, user: str, password: str) -> None:
    page.goto(base + "/")
    page.wait_for_selector("form.login-card")
    page.fill("input[name=login]", user)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_selector("#runs-title, #welcome-title")
    page.wait_for_load_state("networkidle")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8080")
    p.add_argument("--login", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--run", help="investigation terminée à capturer (run_id)")
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
                page.goto(args.base + "/")
                page.wait_for_selector("form.login-card")
                page.screenshot(path=out / f"connexion-{scheme}-{name}.png")
                login(page, args.base, args.login, args.password)
                page.screenshot(path=out / f"accueil-{scheme}-{name}.png", full_page=True)
                page.keyboard.press("Control+k")
                page.wait_for_selector(".palette[open] .palette-item")
                page.wait_for_timeout(250)
                page.screenshot(path=out / f"palette-{scheme}-{name}.png")
                page.keyboard.press("Escape")
                if args.run:
                    page.goto(f"{args.base}/#{args.run}")
                    page.wait_for_selector(".agent-node")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(400)
                    page.screenshot(path=out / f"investigation-{scheme}-{name}.png", full_page=True)
                    page.locator(".agent-node").first.click()
                    page.wait_for_selector(".drawer h3")
                    page.wait_for_timeout(500)  # fin de l'animation d'ouverture
                    page.screenshot(path=out / f"tiroir-{scheme}-{name}.png")
                    page.keyboard.press("Escape")
                page.goto(f"{args.base}/#admin")
                page.wait_for_selector("text=Administration")
                page.wait_for_load_state("networkidle")
                page.screenshot(path=out / f"administration-{scheme}-{name}.png", full_page=True)
                ctx.close()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        login(page, args.base, args.login, args.password)
        page.screenshot(path=out / "accueil-mouvement-reduit.png")
        browser.close()
    print(f"Captures dans {out}")


if __name__ == "__main__":
    main()
