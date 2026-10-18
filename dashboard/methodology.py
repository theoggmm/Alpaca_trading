"""
Page « Méthodologie » (français et anglais) : comment chaque chiffre du tableau de bord est produit.

Les valeurs (seuils, heures, frais, montants, expérience) sont lues dans les fichiers de critères et les
constantes du code au moment de la génération : la page décrit le code, elle ne peut pas le contredire.
Écrite à chaque génération du tableau de bord (dashboard/build.py).
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.domains import WEEK_SESSIONS
from core.fundamentals import MAX_STALENESS
from core.history import TOP_IN_DOMAIN
from core.performance_metrics import TRADING_DAYS_PER_YEAR
from core.portfolio import AMOUNTS, COST_BPS, STOP_LOSS, TAKE_PROFIT, TAX_RATE
from core.screener import Criteria
from core.closing import ClosingCriteria
from core.opening import OpeningCriteria
from core.strategy import load_strategies
from core.swing import SwingCriteria
from core.switch import SwitchCriteria
from dashboard.live import DEFINITIVE_AFTER, FEED_DELAY, ORDER_PLAN_AMOUNT, ROOT

HERE = ROOT / "dashboard"
TEMPLATE = HERE / "methodology_template.html"
OUTPUTS = {"fr": HERE / "methodologie.html", "en": HERE / "methodology_en.html"}
CRITERIA_DIR = ROOT / "research" / "algorithms" / "reprise_apres_baisse"
NY_OPEN_MINUTES = 9 * 60 + 30   # ouverture habituelle de New York, 9 h 30 (les séances courtes ne changent pas l'ouverture)


def _number(value, lang):
    text = format(Decimal(str(value)).normalize(), "f")
    return text.replace(".", ",") if lang == "fr" else text


def _usd(value, lang):
    value = Decimal(value)
    if value >= 1_000_000:
        m = _number(value / 1_000_000, lang)
        return f"{m} M$" if lang == "fr" else f"${m}M"
    whole = f"{int(value):,}"
    return f"{whole.replace(',', ' ')} $" if lang == "fr" else f"${whole}"


def _paris_time(minutes, lang):
    """Même heure à Paris aujourd'hui (l'écart avec New York n'est pas toujours de 6 h)."""
    day = date.today()
    moment = datetime(day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=ZoneInfo("America/New_York"))
    paris = moment.astimezone(ZoneInfo("Europe/Paris"))
    return f"{paris.hour} h {paris.minute:02d}" if lang == "fr" else paris.strftime("%H:%M")


def _ny_time(minutes, lang):
    h, m = divmod(minutes, 60)
    if lang == "fr":
        return f"{h} h {m:02d}"
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _strategies_table(lang, feed):
    """Tableau HTML des stratégies, dans l'ordre de l'accueil : sélection, décision, achat et vente (New York, Paris)."""
    kinds = {"fr": {Criteria: "Reprise après baisse (début de séance)", OpeningCriteria: "Ouverture (veille et nuit)",
                    ClosingCriteria: "Fin de journée (journée et dernière heure)",
                    SwitchCriteria: "Bascule (fin de journée, selon le marché)",
                    SwingCriteria: "Repli dans une tendance (quelques séances)"},
             "en": {Criteria: "Rebound after decline (start of session)", OpeningCriteria: "Open (previous day and overnight)",
                    ClosingCriteria: "End of day (day and last hour)",
                    SwitchCriteria: "Switch (end of day, depending on the market)",
                    SwingCriteria: "Dip in an uptrend (a few sessions)"}}[lang]
    head = {"fr": ["#", "Stratégie", "Sélection", "Décision", "Achat", "Vente"],
            "en": ["#", "Strategy", "Selection", "Decision", "Purchase", "Sale"]}[lang]
    next_day = {"fr": "le lendemain ", "en": "next day "}[lang]
    later = {"fr": "{k} séances plus tard ", "en": "{k} sessions later "}[lang]
    either = {"fr": " ou ", "en": " or "}[lang]

    def when(minutes, prefix=""):
        return f"{prefix}{_ny_time(minutes, lang)} <small>({_paris_time(minutes, lang)} Paris)</small>"

    rows = []
    for i, strategy in enumerate(load_strategies(CRITERIA_DIR, "reprise_apres_baisse"), start=1):
        c = strategy.criteria()["sans_per"]
        decision = NY_OPEN_MINUTES + c.decision_minutes
        if strategy.exit_after_sessions:
            sale = when(16 * 60 - strategy.exit_before_close_minutes, later.format(k=strategy.exit_after_sessions))
        elif strategy.overnight:
            sale = when(NY_OPEN_MINUTES + strategy.exit_next_open_minutes, next_day)
        elif strategy.exit_after_open_minutes is not None:
            sale = when(NY_OPEN_MINUTES + strategy.exit_after_open_minutes)
        else:
            sale = when(16 * 60 - strategy.exit_before_close_minutes)
        name = strategy.name if lang == "fr" else strategy.name_en
        # Bascule : deux heures de décision et d'achat possibles.
        others = [NY_OPEN_MINUTES + m for m in getattr(c, "decisions_minutes", [])[1:]]
        decided = when(decision) + "".join(either + when(m) for m in others)
        bought = when(decision + feed) + "".join(either + when(m + feed) for m in others)
        rows.append(f"<tr><td>{i}</td><td>{name}</td><td>{kinds[type(c)]}</td><td>{decided}</td>"
                    f"<td>{bought}</td><td>{sale}</td></tr>")
    return "<tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>\n    " + "\n    ".join(rows)


TEST_COLUMNS = (("annee_2025", {"fr": "2025 (servi à régler 11 et 12)", "en": "2025 (used to set 11 and 12)"}),
                ("annee_2024", {"fr": "2024 (jamais vu)", "en": "2024 (never seen)"}),
                ("periode_20261012_20261016", {"fr": "Semaine du 12 au 16 oct. 2026", "en": "Week of Oct 12–16, 2026"}))


def _new_strategies_table(lang):
    """
    Tableau HTML : rendement cumulé après frais de chaque stratégie (liste PER &lt; 25 / liste sans PER) dans chaque
    test (dernier résultat de chaque période, onglet « Tests »). « à venir » tant que le test n'a pas tourné.
    """
    from infra.trace import RUNS_DIR
    head = {"fr": ["#", "Stratégie"], "en": ["#", "Strategy"]}[lang] + [label[lang] for _, label in TEST_COLUMNS]
    pending = {"fr": "à venir", "en": "pending"}[lang]
    note = {"fr": "PER &lt; 25 · sans PER", "en": "P/E &lt; 25 · without P/E"}[lang]

    def pct(v):
        if v is None:
            return "—"
        return ("+" if v > 0 else "") + _number(Decimal(str(round(v * 100, 1))), lang).replace("-", "−") + (" %" if lang == "fr" else "%")

    rows = []
    for i, strategy in enumerate(load_strategies(CRITERIA_DIR, "reprise_apres_baisse"), start=1):
        latest = {}
        for path in sorted((RUNS_DIR / strategy.storage / "backtests").glob("b[0-9][0-9][0-9]/results.json")):
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("label"):
                latest[result["label"]] = result
        cells = []
        for label, _ in TEST_COLUMNS:
            result = latest.get(label)
            if result is None:
                cells.append(f"<td>{pending}</td>")
                continue
            totals = [result["summaries"].get(v, {}).get("total") for v in ("per12", "sans_per")]
            cells.append(f"<td>{pct(totals[0])} · <b>{pct(totals[1])}</b></td>")
        name = strategy.name if lang == "fr" else strategy.name_en
        rows.append(f"<tr><td>{i}</td><td>{name}</td>{''.join(cells)}</tr>")
    return ("<tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>\n    "
            + "<tr><td></td><td></td>" + "".join(f"<td><small>{note}</small></td>" for _ in TEST_COLUMNS)
            + "</tr>\n    " + "\n    ".join(rows))


def _values(lang, experiment):
    base = Criteria.from_file(CRITERIA_DIR / "criteres_sans_per.json")
    per12 = Criteria.from_file(CRITERIA_DIR / "criteres_per12.json")
    if per12.to_json() | {"max_pe": None, "version": None} != base.to_json() | {"max_pe": None, "version": None}:
        raise ValueError("Les deux fichiers de critères diffèrent ailleurs que sur le PER : la page serait fausse.")
    feed = int(FEED_DELAY.total_seconds() // 60)
    # Page de la stratégie principale : sa vente (N minutes avant la clôture).
    exit_before = load_strategies(CRITERIA_DIR, "reprise_apres_baisse")[0].exit_before_close_minutes
    decision = NY_OPEN_MINUTES + base.first_hour_minutes
    confirm_decision = NY_OPEN_MINUTES + base.decision_minutes
    # Règles des sélections « ouverture » et « fin de journée » : celles de la première stratégie de chaque sorte.
    every = load_strategies(CRITERIA_DIR, "reprise_apres_baisse")
    opening = next(c for s in every for c in s.criteria().values() if isinstance(c, OpeningCriteria))
    closing = next(c for s in every for c in s.criteria().values() if isinstance(c, ClosingCriteria))
    return {
        "page_title": "Méthodologie" if lang == "fr" else "Methodology",
        "strategies_table": _strategies_table(lang, feed), "n_strategies": len(every),
        "new_strategies_table": _new_strategies_table(lang),
        "open_last_hour": opening.last_hour_minutes, "open_min_night": _number(opening.min_overnight * 100, lang),
        "open_max_night": _number(opening.max_overnight * 100, lang), "open_min_volume": opening.min_premarket_volume,
        "open_decision": _ny_time(NY_OPEN_MINUTES + opening.decision_minutes, lang),
        "open_decision_paris": _paris_time(NY_OPEN_MINUTES + opening.decision_minutes, lang),
        "close_min_day": _number(closing.min_day_gain * 100, lang), "close_max_day": _number(closing.max_day_gain * 100, lang),
        "close_last_hour": closing.last_hour_minutes, "close_below_high": _number(closing.max_below_day_high * 100, lang),
        "count": base.count, "month_sessions": base.month_sessions, "up_days": base.up_days,
        "first_hour": base.first_hour_minutes, "liquidity_sessions": base.liquidity_sessions,
        "min_price": _usd(base.min_price_usd, lang), "min_volume": _usd(base.min_avg_dollar_volume_usd, lang),
        "volatility_sessions": base.volatility_sessions,
        "volatility_pct": _number(Decimal(str(base.max_volatility_quantile)) * 100, lang),
        "correlation_sessions": base.correlation_sessions,
        "max_corr": _number(base.max_pairwise_correlation, lang), "max_pe": _number(per12.max_pe, lang),
        "closes": base.required_sessions,
        # Décision en deux temps : fin de la première heure, puis confirmation ; achat quand la confirmation est servie.
        "decision_time": _ny_time(decision, lang), "confirm_decision_time": _ny_time(confirm_decision, lang),
        "open_paris": _paris_time(NY_OPEN_MINUTES, lang), "close_paris": _paris_time(16 * 60, lang),
        "decision_paris": _paris_time(decision, lang), "confirm_paris": _paris_time(confirm_decision, lang),
        "entry_paris": _paris_time(confirm_decision + feed, lang), "exit_paris": _paris_time(16 * 60 - exit_before, lang),
        "entry_time": _ny_time(confirm_decision + feed, lang),
        "confirmation_minutes": base.confirmation_minutes,
        "confirm_tolerance": _number((base.confirmation_tolerance or 0) * 100, lang),
        "gap_pct": _number(base.min_gap_below_high * 100, lang),
        "ma_pct": _number(base.max_below_ma * 100, lang), "ma_sessions": base.ma_sessions,
        "market_symbol": base.market_symbol, "market_ma_sessions": base.market_ma_sessions,
        "exit_time": _ny_time(16 * 60 - exit_before, lang), "feed_delay": feed, "exit_before": exit_before,
        "tax_pct": _number(TAX_RATE * 100, lang),
        "stop_pct": _number(STOP_LOSS * 100, lang), "target_pct": _number(TAKE_PROFIT * 100, lang),
        "cost_pct": _number(COST_BPS / 100, lang), "cost_round_pct": _number(COST_BPS * 2 / 100, lang),
        "amounts": ", ".join(_usd(a, lang) for a in AMOUNTS), "plan_amount": _usd(ORDER_PLAN_AMOUNT, lang),
        "definitive_after": int(DEFINITIVE_AFTER.total_seconds() // 3600), "top_n": TOP_IN_DOMAIN,
        "week_sessions": WEEK_SESSIONS, "eps_staleness": MAX_STALENESS.days, "year_days": TRADING_DAYS_PER_YEAR,
        "exp_id": experiment["id"], "exp_start": experiment["start"], "exp_sessions": experiment["sessions"],
        "exp_file": experiment["file"],
    }


def _page(lang, experiment):
    """Page complète d'une langue ; une valeur absente du dictionnaire lève une erreur plutôt que d'afficher {{…}}."""
    values = _values(lang, experiment)
    page = re.sub(r'<article lang="(fr|en)">.*?</article>\n',
                  lambda m: m.group(0) if m.group(1) == lang else "", TEMPLATE.read_text(encoding="utf-8"), flags=re.S)
    page = re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m.group(1)]), page)
    return page.replace("__LANG__", lang)


def write(experiment):
    """Écrit les deux pages autonomes."""
    for lang, path in OUTPUTS.items():
        path.write_text(_page(lang, experiment), encoding="utf-8")
    return OUTPUTS


def embedded(lang, experiment):
    """
    Contenu de la page pour l'onglet « Méthodologie » du tableau de bord : sans l'en-tête de navigation,
    identifiants préfixés « m- » pour ne pas heurter ceux du tableau de bord (selection, experiment…).
    """
    body = re.search(r'<article lang="\w+">(.*?)</article>', _page(lang, experiment), flags=re.S).group(1)
    body = re.sub(r"<header>.*?</header>", "", body, flags=re.S)
    return re.sub(r'(id="|href="#)', r"\1m-", body)
