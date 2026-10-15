"""
Complément des séances définitives produites avant l'ajout des frais et des repères : simulation
recalculée après coup (diagnostic), à côté de l'état de fin de séance, qui n'est pas modifié.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.supplement reprise_apres_baisse
"""

import sys

from dashboard.live import main, supplement


def report(family):
    paths = supplement(family)
    print("\n".join(f"Complément : {p}" for p in paths) or "Aucune séance à compléter.")
    return 0


if __name__ == "__main__":
    sys.exit(main(report))
