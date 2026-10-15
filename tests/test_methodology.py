"""Page Méthodologie : toutes les valeurs sont remplacées, une seule langue par page."""

from dashboard import methodology
from dashboard.build import EXPERIMENT


def test_pages_completes(tmp_path, monkeypatch):
    outputs = {"fr": tmp_path / "fr.html", "en": tmp_path / "en.html"}
    monkeypatch.setattr(methodology, "OUTPUTS", outputs)
    methodology.write(EXPERIMENT)
    fr, en = (outputs[lang].read_text(encoding="utf-8") for lang in ("fr", "en"))
    assert "{{" not in fr and "{{" not in en
    assert '<article lang="en">' not in fr and '<article lang="fr">' not in en
    assert "PER &lt; 25" in fr and "11 h 00" in fr and "Last close ≥ $5" in en and "0.05%" in en
    assert "0,2 %" in fr and "11:00 AM" in en
