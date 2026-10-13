"""
Rattrapage : état de fin de séance de chaque séance terminée qui n'en a pas encore.

Depuis la racine du dépôt :
    .venv/bin/python -m dashboard.final reprise_apres_baisse
"""

import sys

from dashboard.live import catch_up, main


def report(family):
    paths = catch_up(family)
    print("\n".join(f"État de fin de séance : {p}" for p in paths) or "Aucune séance à rattraper.")
    return 0


if __name__ == "__main__":
    sys.exit(main(report))
