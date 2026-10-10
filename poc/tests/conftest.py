import os
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def poc_env(tmp_path, monkeypatch):
    """Données de démonstration seules (même si PROMETHEUS_URL est exportée), heure figée, traces dans
    un dossier temporaire."""
    monkeypatch.setenv("DIAGAGENT_HOME", str(POC))
    monkeypatch.setenv("DIAGAGENT_SOURCES", "demo")
    monkeypatch.setenv("DIAGAGENT_NOW", "2026-10-07T06:00:00Z")
    monkeypatch.setenv("DIAGAGENT_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    for var in ("SSH_HOSTS", "WEB_SEARCH"):  # sources maison activées test par test
        monkeypatch.delenv(var, raising=False)
    from diagagent import catalog
    catalog.load_catalog.cache_clear()
    catalog.load_yaml.cache_clear()
    catalog._load_rows.cache_clear()
    return tmp_path
