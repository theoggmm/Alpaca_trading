"""
Page « Méthodologie » (français et anglais) : comment chaque chiffre du tableau de bord est produit.

Les valeurs (seuils, heures, frais, montants, expérience) sont lues dans les fichiers de critères et les
constantes du code au moment de la génération : la page décrit le code, elle ne peut pas le contredire.
Écrite à chaque génération du tableau de bord (dashboard/build.py).
"""

import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.domains import WEEK_SESSIONS
from core.fundamentals import MAX_STALENESS
from core.history import TOP_IN_DOMAIN
from core.performance_metrics import TRADING_DAYS_PER_YEAR
from core.portfolio import AMOUNTS, COST_BPS, TAX_RATE
from core.screener import Criteria
from core.strategy import load_strategies
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
    return {
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
        "gap_pct": _number(base.min_gap_below_high * 100, lang),
        "ma_pct": _number(base.max_below_ma * 100, lang), "ma_sessions": base.ma_sessions,
        "market_symbol": base.market_symbol, "market_ma_sessions": base.market_ma_sessions,
        "exit_time": _ny_time(16 * 60 - exit_before, lang), "feed_delay": feed, "exit_before": exit_before,
        "tax_pct": _number(TAX_RATE * 100, lang),
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
