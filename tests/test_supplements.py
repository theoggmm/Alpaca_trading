"""Compléments : remplacent la simulation à l'affichage, sans toucher l'état définitif sur le disque."""

import json

from dashboard import build


def test_complement_affiche_sans_modifier_l_etat(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "FINALS_DIR", tmp_path)
    family = tmp_path / "famille"
    (family / build.SUPPLEMENTS).mkdir(parents=True)
    state = {"session_date": "2026-10-14", "provisional": False, "selection": {"changes": {}},
             "portfolio": {"versions": {"per12": {"mean_return": 0.0075}}}}
    (family / "2026-10-14.json").write_text(json.dumps(state), encoding="utf-8")
    (family / "2026-10-13.json").write_text(json.dumps({"session_date": "2026-10-13", "provisional": False}),
                                            encoding="utf-8")
    sup = {"portfolio": {"versions": {"per12": {"net_mean_return": 0.0065}}}, "order_plan": None,
           "since_entry": {"PRI": {"change": 0.01}}, "computed_at": "2026-10-15T15:00:00+00:00", "git_sha": "abc"}
    (family / build.SUPPLEMENTS / "2026-10-14.json").write_text(json.dumps(sup), encoding="utf-8")

    finals = dict((f["session_date"], f) for f, _ in build._load_finals("famille"))
    assert finals["2026-10-14"]["portfolio"] == sup["portfolio"]
    assert finals["2026-10-14"]["selection"]["since_entry"] == sup["since_entry"]
    assert finals["2026-10-14"]["supplement"]["git_sha"] == "abc"
    assert "supplement" not in finals["2026-10-13"]
    assert json.loads((family / "2026-10-14.json").read_text(encoding="utf-8")) == state   # disque intact
    results = build._results(list(finals.values()))
    assert results["series"]["per12"] == {"2026-10-14": 0.0065} and results["recomputed"] == ["2026-10-14"]
