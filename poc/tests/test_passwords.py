"""Règles des mots de passe : longueur, liste locale de mots de passe compromis, identifiant."""

from diagagent.web import passwords


def test_rules():
    assert passwords.problems("cheval-agrafe-batterie", "zoe", "Zoé Martin") == []
    assert passwords.problems("court", "zoe")[0].startswith("12 caractères")
    assert any("compromis" in p for p in passwords.problems("Azertyuiop123"))  # sans casse
    assert any("identifiant" in p for p in passwords.problems("martin-du-pont-2026", "jdoe", "Jean Martin"))
    assert any("différents" in p for p in passwords.problems("abababababab"))


def test_local_list_extends_the_builtin_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGAGENT_HOME", str(tmp_path))
    assert passwords.problems("tour-eiffel-paris-1889") == []
    (tmp_path / "auth").mkdir()
    (tmp_path / "auth" / "compromised-passwords.txt").write_text("# fuite\nTour-Eiffel-Paris-1889\n", encoding="utf-8")
    assert any("compromis" in p for p in passwords.problems("tour-eiffel-paris-1889"))
