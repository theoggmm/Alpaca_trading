"""
Bascule de fin de journée : deux listes « fin de journée » possibles, une seule achetée selon le marché du jour.

1. À la première décision (ex. 14 h 45), si le marché tient (règle 5 bis de core/closing.py) : la liste de la
   première décision est la liste du jour (achat 15 min plus tard), même si aucune action ne passe ensuite.
2. Sinon, à la seconde décision (ex. 15 h 40) : la liste de la seconde décision, elle-même soumise à sa propre
   condition de marché (ex. « marché qui remonte » sur la dernière heure, règle 5 ter) ; aucune liste si elle
   n'est pas remplie.

Chaque décision ne lit que les barres terminées à son heure (datation de screen_closing et market_conditions).
Le run enregistre les critères de la décision retenue : heure d'achat et textes se lisent comme une liste
« fin de journée » ordinaire.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from core.closing import ClosingCriteria, market_conditions, screen_closing

SIGNAL = "bascule"


@dataclass(frozen=True)
class SwitchCriteria:
    signal: str
    version: int
    first: ClosingCriteria
    second: ClosingCriteria

    @classmethod
    def from_json(cls, raw, source="critères"):
        if set(raw) != {"signal", "version", "first", "second"} or raw["signal"] != SIGNAL:
            raise ValueError(f"Clés attendues dans {source} : signal « {SIGNAL} », version, first, second ; "
                             f"reçues : {sorted(raw)}")
        first = ClosingCriteria.from_json(raw["first"], f"{source} (first)")
        second = ClosingCriteria.from_json(raw["second"], f"{source} (second)")
        if first.market_min_day_return is None or second.decision_minutes <= first.decision_minutes:
            raise ValueError(f"{source} : first doit fixer market_min_day_return et décider avant second")
        return cls(signal=SIGNAL, version=int(raw["version"]), first=first, second=second)

    @classmethod
    def from_file(cls, path):
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    @property
    def decision_minutes(self):
        """Première décision : la liste peut être prête dès cette heure (+ retard des données)."""
        return self.first.decision_minutes

    @property
    def decisions_minutes(self):
        """Les deux heures de décision possibles (achats possibles à chacune + retard des données)."""
        return [self.first.decision_minutes, self.second.decision_minutes]

    @property
    def max_pe(self):
        return self.first.max_pe

    @property
    def market_symbol(self):
        return self.first.market_symbol

    def to_json(self):
        return {"signal": SIGNAL, "version": self.version, "first": self.first.to_json(),
                "second": self.second.to_json()}


def choose(criteria, market_minute, market_open, first_decision):
    """Vrai si la première liste est retenue : le marché tient à la première décision (barres terminées à elle)."""
    return all(market_conditions(criteria.first, market_minute, market_open, first_decision).values())


def screen_switch(daily, minute, market_open, decision_time, criteria, earnings_for=None, market_daily=None,
                  market_minute=None, fear_minute=None):
    """
    Liste de la décision decision_time (première ou seconde) : (sélection, entonnoir, critères retenus).
    À la seconde décision, la première ne doit pas avoir été retenue (sinon ValueError : la liste du jour
    était déjà celle de la première décision).
    """
    first_decision = market_open + timedelta(minutes=criteria.first.decision_minutes)
    if decision_time == first_decision:
        chosen = criteria.first
    elif decision_time == market_open + timedelta(minutes=criteria.second.decision_minutes):
        if choose(criteria, market_minute, market_open, first_decision):
            raise ValueError("Le marché tenait à la première décision : la liste du jour est la première")
        chosen = criteria.second
    else:
        raise ValueError("decision_time doit être l'une des deux décisions de la bascule")
    selection, funnel = screen_closing(daily, minute, market_open, decision_time, chosen, earnings_for=earnings_for,
                                       market_daily=market_daily, market_minute=market_minute, fear_minute=fear_minute)
    return selection, funnel, chosen

