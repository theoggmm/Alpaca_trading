"""
Stratégies d'une famille : règles de sélection, heures d'achat et de vente propres à chacune.

Une stratégie = un dossier contenant `strategy.json` (nom et description en français et en anglais, vente N minutes avant la clôture
ou N minutes après l'ouverture) et les fichiers de critères de ses listes (`criteres_<version>.json`).
L'heure d'achat découle des critères : décision + retard des données. Cinq sortes de critères : « reprise
après baisse » (core/screener.py), « ouverture » (core/opening.py, "signal": "ouverture"), « fin de journée »
(core/closing.py, "signal": "fin_de_journee", achat en fin de séance, vente la séance suivante), « bascule »
(core/switch.py, "signal": "bascule", deux heures d'achat possibles selon le marché) et « repli dans une
tendance » (core/swing.py, "signal": "repli_tendance", gardé quelques séances).

Vente : N minutes avant la clôture, N minutes après l'ouverture, à l'ouverture suivante + N minutes, ou N minutes
avant la clôture de la k-ième séance suivante (exit_after_sessions, au plus MAX_HOLD_SESSIONS). Stop et objectif
propres à la stratégie (stop_loss, take_profit ; take_profit null = pas d'objectif), sinon ceux de core/portfolio.
La stratégie principale est le dossier de la famille lui-même ; les autres vivent sous `strategies/<id>/` (une variante vit sous sa famille).

Chaque stratégie a sa clé de stockage (`storage`) : runs dans research/experiments/runs/<storage>/,
états de fin de séance dans research/experiments/final/<storage>/.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from core.closing import SIGNAL as CLOSING, ClosingCriteria
from core.opening import SIGNAL as OPENING, OpeningCriteria
from core.portfolio import STOP_LOSS, TAKE_PROFIT
from core.screener import Criteria
from core.swing import SIGNAL as SWING, SwingCriteria
from core.switch import SIGNAL as SWITCH, SwitchCriteria

MAIN = "principale"
STRATEGIES_DIR = "strategies"
MAX_HOLD_SESSIONS = 3   # garde la plus longue permise (décision du propriétaire : quelques jours au plus)


@dataclass(frozen=True)
class Strategy:
    id: str
    order: int                      # place sur l'accueil et dans le menu « Stratégie »
    name: str
    description: str
    name_en: str
    description_en: str
    family: str
    folder: Path                    # dossier des fichiers de critères et de strategy.json
    exit_before_close_minutes: int  # vente : dernier échange avant clôture - N minutes (ou None)
    exit_after_open_minutes: int    # vente : dernier échange avant ouverture + N minutes (ou None)
    exit_next_open_minutes: int     # vente la séance suivante : ouverture suivante + N minutes, 0 = à l'ouverture (ou None)
    exit_after_sessions: int = None  # vente k séances plus tard, exit_before_close_minutes avant leur clôture (ou None)
    stop_loss: Decimal = STOP_LOSS   # vente plus tôt si le cours passe ce pourcentage sous le prix d'achat
    take_profit: Decimal = TAKE_PROFIT  # vente plus tôt au-dessus (None : pas d'objectif)

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
    def sale_offset(self):
        """Nombre de séances entre l'achat et la vente : 0 le jour même, 1 la séance suivante, k plus tard."""
        if self.exit_next_open_minutes is not None:
            return 1
        return self.exit_after_sessions or 0

    @property
    def overnight(self):
        """Achat en fin de séance (ou dans la séance), vente une séance suivante."""
        return self.sale_offset > 0

    def exit_time(self, market_open, market_close, sale_session=None):
        """
        Heure de vente. Vente une séance suivante : sale_session = (ouverture, clôture) de la séance de vente
        (sale_offset séances plus tard) requis ; « à l'ouverture » (0) = dernier échange avant la fin de la
        première minute, c'est-à-dire le prix d'ouverture.
        """
        if self.overnight:
            if sale_session is None:
                raise ValueError(f"{self.id} : la séance de vente ({self.sale_offset} séance(s) plus tard) est requise")
            if self.exit_next_open_minutes is not None:
                return sale_session[0] + timedelta(minutes=max(self.exit_next_open_minutes, 1))
            return sale_session[1] - timedelta(minutes=self.exit_before_close_minutes)
        if self.exit_after_open_minutes is not None:
            return market_open + timedelta(minutes=self.exit_after_open_minutes)
        return market_close - timedelta(minutes=self.exit_before_close_minutes)


def criteria_from_json(raw, source="critères"):
    """Critères « ouverture » si raw porte "signal": "ouverture", sinon critères « reprise après baisse »."""
    kinds = {OPENING: OpeningCriteria, CLOSING: ClosingCriteria, SWITCH: SwitchCriteria, SWING: SwingCriteria}
    return kinds.get(raw.get("signal"), Criteria).from_json(raw, source)


def load_criteria(path):
    return criteria_from_json(json.loads(Path(path).read_text(encoding="utf-8")), str(path))


def _load(folder, family):
    raw = json.loads((folder / "strategy.json").read_text(encoding="utf-8"))
    exits = {"exit_before_close_minutes", "exit_after_open_minutes", "exit_next_open_minutes"} & set(raw)
    optional = {"exit_after_sessions", "stop_loss", "take_profit"} & set(raw)
    after = raw.get("exit_after_sessions")
    if (set(raw) - exits - optional != {"id", "order", "name", "description", "name_en", "description_en"} or len(exits) != 1
            or (after is not None and (exits != {"exit_before_close_minutes"} or not 1 <= after <= MAX_HOLD_SESSIONS))):
        raise ValueError(f"{folder / 'strategy.json'} : id, order, name, description, name_en, description_en et une seule heure de vente "
                         f"(exit_before_close_minutes, exit_after_open_minutes ou exit_next_open_minutes ; exit_after_sessions "
                         f"de 1 à {MAX_HOLD_SESSIONS} avec exit_before_close_minutes), stop_loss et take_profit facultatifs ; "
                         f"reçues : {sorted(raw)}")
    return Strategy(id=raw["id"], order=int(raw["order"]), name=raw["name"], description=raw["description"], name_en=raw["name_en"],
                    description_en=raw["description_en"], family=family, folder=folder,
                    exit_before_close_minutes=raw.get("exit_before_close_minutes"),
                    exit_after_open_minutes=raw.get("exit_after_open_minutes"),
                    exit_next_open_minutes=raw.get("exit_next_open_minutes"),
                    exit_after_sessions=after,
                    stop_loss=Decimal(raw["stop_loss"]) if "stop_loss" in raw else STOP_LOSS,
                    take_profit=(None if raw["take_profit"] is None else Decimal(raw["take_profit"]))
                    if "take_profit" in raw else TAKE_PROFIT)


def load_strategies(family_dir, family):
    """La stratégie principale (dossier de la famille), puis les variantes de strategies/, dans l'ordre de leur champ « order »."""
    family_dir = Path(family_dir)
    main = _load(family_dir, family)
    if not main.is_main:
        raise ValueError(f"{family_dir / 'strategy.json'} doit porter l'identifiant « {MAIN} »")
    others = sorted((_load(folder, family) for folder in (family_dir / STRATEGIES_DIR).glob("*/")
                     if (folder / "strategy.json").exists()), key=lambda s: (s.order, s.id))
    if len({s.id for s in [main, *others]}) != len(others) + 1:
        raise ValueError("Deux stratégies portent le même identifiant")
    return [main, *others]
