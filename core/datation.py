"""
Invariant de datation (règle 1 de CLAUDE.md).

Une barre n'est utilisable pour une décision prise à l'instant t que si elle est
terminée à t : horodatage de début + durée de la barre <= t.
"""


def usable_bars(bars, bar_length, decision_time):
    """Garde uniquement les barres terminées à decision_time (colonne "timestamp" = début de barre, UTC)."""
    if decision_time.tzinfo is None:
        raise ValueError("decision_time doit porter un fuseau horaire")
    return bars[bars["timestamp"] + bar_length <= decision_time]
