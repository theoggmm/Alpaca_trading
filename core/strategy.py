"""
Stratégies d'une famille : règles de sélection, heures d'achat et de vente propres à chacune.

Une stratégie = un dossier contenant `strategy.json` (nom et description en français et en anglais, vente N minutes avant la clôture
ou N minutes après l'ouverture) et les fichiers de critères de ses listes (`criteres_<version>.json`).
L'heure d'achat découle des critères : décision + retard des données. Trois sortes de critères : « reprise
après baisse » (core/screener.py), « ouverture » (core/opening.py, "signal": "ouverture") et « fin de journée »
(core/closing.py, "signal": "fin_de_journee", achat en fin de séance, vente la séance suivante).
La stratégie principale est le dossier de la famille lui-même ; les autres vivent sous `strategies/<id>/` (une variante vit sous sa famille).

Chaque stratégie a sa clé de stockage (`storage`) : runs dans research/experiments/runs/<storage>/,
états de fin de séance dans research/experiments/final/<storage>/.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from core.closing import SIGNAL as CLOSING, ClosingCriteria
from core.opening import SIGNAL as OPENING, OpeningCriteria
from core.screener import Criteria

MAIN = "principale"
STRATEGIES_DIR = "strategies"


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    description: str
    name_en: str
    description_en: str
    family: str
    folder: Path                    # dossier des fichiers de critères et de strategy.json
    exit_before_close_minutes: int  # vente : dernier échange avant clôture - N minutes (ou None)
    exit_after_open_minutes: int    # vente : dernier échange avant ouverture + N minutes (ou None)
    exit_next_open_minutes: int     # vente la séance suivante : ouverture suivante + N minutes, 0 = à l'ouverture (ou None)

    @property
    def is_main(self):
        return self.id == MAIN

    @property
    def storage(self):
        """Clé de stockage des runs et des états de fin de séance (sous la famille pour une variante)."""
        return self.family if self.is_main else f"{self.family}/{STRATEGIES_DIR}/{self.id}"

    @property
    def criteria_files(self):
        """version de la liste -> fichier de critères (criteres_sans_per.json -> « sans_per »)."""
        return {path.stem.removeprefix("criteres_"): path for path in sorted(self.folder.glob("criteres_*.json"))}

    def criteria(self):
        return {variant: load_criteria(path) for variant, path in self.criteria_files.items()}

    @property
    def overnight(self):
        """Achat en fin de séance, vente la séance suivante."""
        return self.exit_next_open_minutes is not None

    def exit_time(self, market_open, market_close, next_open=None):
        """
        Heure de vente. Vente la séance suivante : next_open (ouverture suivante) requis ; « à l'ouverture » (0)
        = dernier échange avant la fin de la première minute, c'est-à-dire le prix d'ouverture.
        """
        if self.overnight:
            if next_open is None:
                raise ValueError(f"{self.id} : l'ouverture de la séance suivante est requise")
            return next_open + timedelta(minutes=max(self.exit_next_open_minutes, 1))
        if self.exit_after_open_minutes is not None:
            return market_open + timedelta(minutes=self.exit_after_open_minutes)
        return market_close - timedelta(minutes=self.exit_before_close_minutes)


def criteria_from_json(raw, source="critères"):
    """Critères « ouverture » si raw porte "signal": "ouverture", sinon critères « reprise après baisse »."""
    kinds = {OPENING: OpeningCriteria, CLOSING: ClosingCriteria}
    return kinds.get(raw.get("signal"), Criteria).from_json(raw, source)


def load_criteria(path):
    return criteria_from_json(json.loads(Path(path).read_text(encoding="utf-8")), str(path))


def _load(folder, family):
    raw = json.loads((folder / "strategy.json").read_text(encoding="utf-8"))
    exits = {"exit_before_close_minutes", "exit_after_open_minutes", "exit_next_open_minutes"} & set(raw)
    if set(raw) - exits != {"id", "name", "description", "name_en", "description_en"} or len(exits) != 1:
        raise ValueError(f"{folder / 'strategy.json'} : id, name, description, name_en, description_en et une seule heure de vente "
                         f"(exit_before_close_minutes, exit_after_open_minutes ou exit_next_open_minutes) ; reçues : {sorted(raw)}")
    return Strategy(id=raw["id"], name=raw["name"], description=raw["description"], name_en=raw["name_en"],
                    description_en=raw["description_en"], family=family, folder=folder,
                    exit_before_close_minutes=raw.get("exit_before_close_minutes"),
                    exit_after_open_minutes=raw.get("exit_after_open_minutes"),
                    exit_next_open_minutes=raw.get("exit_next_open_minutes"))


def load_strategies(family_dir, family):
    """La stratégie principale (dossier de la famille), puis les variantes de strategies/, par ordre alphabétique."""
    family_dir = Path(family_dir)
    main = _load(family_dir, family)
    if not main.is_main:
        raise ValueError(f"{family_dir / 'strategy.json'} doit porter l'identifiant « {MAIN} »")
    others = [_load(folder, family) for folder in sorted((family_dir / STRATEGIES_DIR).glob("*/"))
              if (folder / "strategy.json").exists()]
    if len({s.id for s in [main, *others]}) != len(others) + 1:
        raise ValueError("Deux stratégies portent le même identifiant")
    return [main, *others]
