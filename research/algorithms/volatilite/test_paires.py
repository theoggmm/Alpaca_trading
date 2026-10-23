"""
Test pré-enregistré T28 : choisir chaque jour 2 actions de la liste Volatilité (run r001), 5 000 $ chacune, objectif
+200 $ nets, échéance 3 h 30 (core/volatility.exit_with_deadline), sur 12 mois de barres minute. Diagnostic.

Depuis la racine du dépôt :
    .venv/bin/python -m research.algorithms.volatilite.test_paires
Résultat : research/experiments/runs/volatilite/tests/<run_id>/results.json (règle 5).
"""

import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.volatility import IF_NEGATIVE, exit_with_deadline
from infra.alpaca_api import AlpacaReader
from infra.cache import cached
from infra.trace import committed_git_sha, next_run_id, save_run
from research.algorithms.volatilite import run as basket

STORAGE = "volatilite/tests"
NEW_YORK = ZoneInfo("America/New_York")
START, END = date(2025, 10, 22), date(2026, 10, 22)
AMOUNT, TARGET, COST_BPS = Decimal("5000"), Decimal("200"), Decimal("5")
SLOTS = 2
DEADLINE = timedelta(hours=3, minutes=30)
METHODS = {
    "M1_ouverture_en_hausse": "plus forte ouverture en hausse, achat 9 h 31",
    "M2_ouverture_en_baisse": "plus forte ouverture en baisse, achat 9 h 31",
    "M3_hausse_15_min": "plus forte hausse 9 h 30 – 9 h 45, achat 9 h 45",
    "M4_hausse_30_min": "plus forte hausse 9 h 30 – 10 h 00, achat 10 h 00",
    "M5_volume_relatif_15_min": "plus fort volume relatif 9 h 30 – 9 h 45, achat 9 h 45",
    "M6_baisse_la_veille": "plus forte baisse la veille, achat 9 h 31",
    "M7_volatilite_20_seances": "plus forte volatilité sur 20 séances, achat 9 h 31",
}
BUY_MINUTE = {"M1": 1, "M2": 1, "M3": 15, "M4": 30, "M5": 15, "M6": 1, "M7": 1, "repere": 1}


def _sessions(alpaca):
    return [(d, *(datetime.combine(d, t, NEW_YORK).astimezone(timezone.utc) for t in (o, c)))
            for d, o, c in alpaca.sessions(START - timedelta(days=45), END)]


def _minute_bars(alpaca, symbols, sessions):
    """Barres minute de séance régulière, cours en float (une lecture par semaine, en cache)."""
    frames = []
    by_week = defaultdict(list)
    for s in sessions:
        by_week[s[0].isocalendar()[:2]].append(s)
    for (year, week), group in sorted(by_week.items()):
        start, end = group[0][1], group[-1][2]

        def fetch():
            bars = alpaca.bars(symbols, "1Min", start, end)
            keep = pd.Series(False, index=bars.index)
            for _, o, c in group:
                keep |= (bars["timestamp"] >= o) & (bars["timestamp"] < c)
            bars = bars[keep]
            return bars.assign(open=bars["open"].astype(float), close=bars["close"].astype(float),
                               volume=bars["volume"].astype(float))
        frames.append(cached(f"volatilite_tests/minute_{year}_{week:02d}_{len(symbols)}", fetch))
        print(f"  semaine {year}-{week:02d} lue", file=sys.stderr, flush=True)
    return pd.concat(frames, ignore_index=True)


def main():
    git_sha = committed_git_sha()
    alpaca = AlpacaReader()
    first = basket.list_for(date(2026, 10, 21))
    symbols = sorted(i["symbol"] for i in first["selection"])
    sessions = _sessions(alpaca)
    tested = [s for s in sessions if START <= s[0] <= END]
    print(f"{len(symbols)} actions, {len(tested)} séances testées ; lecture des barres minute…", file=sys.stderr)
    bars = _minute_bars(alpaca, symbols, sessions)
    daily = cached("volatilite_tests/daily", lambda: alpaca.bars(symbols, "1Day", sessions[0][1] - timedelta(days=60),
                                                                  sessions[-1][2]))
    closes = daily.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last").sort_index().astype(float)
    closes.index = [t.astimezone(NEW_YORK).date() for t in closes.index]

    # Trajets par action : fins de minute et cours, pour toute la période.
    paths = {}
    for s, g in bars.sort_values("timestamp").groupby("symbol"):
        starts = pd.DatetimeIndex(g["timestamp"])
        paths[s] = (starts + pd.Timedelta(minutes=1), g["close"].to_numpy(), g["open"].to_numpy(),
                    g["volume"].to_numpy(), starts)

    def minute_index(s, at):
        return int(paths[s][4].searchsorted(at))     # première barre commençant à at ou après

    early_volume = defaultdict(dict)                     # action -> séance -> volume 9 h 30 – 9 h 45
    day_info = {}
    for d, o, c in sessions:
        info = {}
        for s in symbols:
            if s not in paths:
                continue
            i0, i15, i30 = (minute_index(s, o + timedelta(minutes=k)) for k in (0, 15, 30))
            ts = paths[s][4]
            if i0 >= len(ts) or ts[i0] >= c:
                continue
            first_open = paths[s][2][i0]
            info[s] = {"open": first_open, "i0": i0,
                       "close_15": paths[s][1][i15 - 1] if i15 > i0 else None,
                       "close_30": paths[s][1][i30 - 1] if i30 > i0 else None}
            early_volume[s][d] = paths[s][3][i0:i15].sum()
        day_info[d] = info
    days_all = [s[0] for s in sessions]

    def signals(d):
        """Classement de chaque méthode pour la séance d (données connues avant l'heure d'achat de la méthode)."""
        k = days_all.index(d)
        prev = days_all[k - 1]
        info = day_info[d]
        out = {}
        hist = closes[closes.index < d]
        for s, x in info.items():
            if s not in hist or hist[s].dropna().shape[0] < 22:
                continue
            series = hist[s].dropna()
            prev_close = series.iloc[-1]
            vols = [early_volume[s].get(days_all[j]) for j in range(max(0, k - 20), k)]
            vols = [v for v in vols if v]
            out[s] = {
                "M1": x["open"] / prev_close - 1, "M2": -(x["open"] / prev_close - 1),
                "M3": None if x["close_15"] is None else x["close_15"] / x["open"] - 1,
                "M4": None if x["close_30"] is None else x["close_30"] / x["open"] - 1,
                "M5": (early_volume[s].get(d, 0) / np.mean(vols)) if vols else None,
                "M6": -(series.iloc[-1] / series.iloc[-2] - 1),
                "M7": float(np.log(series.tail(21)).diff().std()),
            }
        return out

    def position(s, d, buy_minute, if_negative):
        """Achat de s à la séance d (minute buy_minute après l'ouverture) puis vente selon la règle. None si impossible."""
        _, o, c = next(x for x in sessions if x[0] == d)
        buy_at = o + timedelta(minutes=buy_minute)
        i = minute_index(s, buy_at)
        ends, cl, op, _, ts = paths[s]
        if i >= len(ts) or ts[i] >= c:
            return None
        entry = Decimal(str(op[i]))
        path = ((ends[j], Decimal(str(cl[j]))) for j in range(i, len(ts)))
        sale = exit_with_deadline(path, entry, AMOUNT, TARGET, COST_BPS, ts[i] + DEADLINE, c, if_negative)
        return {"symbol": s, "day": d, "buy_at": ts[i], "entry": entry, "sale": sale,
                "last": Decimal(str(cl[-1]))}

    # 1. Taux d'objectif en 3 h 30 : repère (les 39) et top 2 de chaque méthode, chaque jour (sans contrainte de compte).
    hits = defaultdict(lambda: defaultdict(lambda: [0, 0]))     # méthode -> mois -> [atteints, essais]
    durations = defaultdict(list)
    ranks = {}
    for d, _, _ in tested:
        sig = signals(d)
        ranks[d] = {}
        for m in BUY_MINUTE:
            if m == "repere":
                chosen = list(sig)
            else:
                scored = [(v[m], s) for s, v in sig.items() if v[m] is not None and not math.isnan(v[m])]
                ranks[d][m] = [s for _, s in sorted(scored, reverse=True)]
                chosen = ranks[d][m][:SLOTS]
            for s in chosen:
                p = position(s, d, BUY_MINUTE[m], "cloture")
                if p is None:
                    continue
                hit = p["sale"] is not None and p["sale"]["reason"] == "objectif"
                month = d.strftime("%Y-%m")
                hits[m][month][1] += 1
                hits[m][month][0] += hit
                if hit:
                    durations[m].append((p["sale"]["exit_at"] - p["buy_at"]).total_seconds())

    # 2. Compte de 2 places, pour chaque méthode et chaque variante (A, B, C).
    accounts = {}
    for m in METHODS:
        key = m.split("_")[0]
        for variant in IF_NEGATIVE:
            held, closed = [], []
            for d, o, _ in tested:
                buy_at = o + timedelta(minutes=BUY_MINUTE[key])
                held = [p for p in held if not (p["sale"] and p["sale"]["exit_at"] <= buy_at)]
                for s in ranks[d].get(key, []):
                    if len(held) >= SLOTS:
                        break
                    if any(p["symbol"] == s for p in held):
                        continue
                    p = position(s, d, BUY_MINUTE[key], variant)
                    if p:
                        held.append(p)
                        closed.append(p)
            gains = defaultdict(Decimal)
            reasons = defaultdict(int)
            still = []
            for p in closed:
                if p["sale"]:
                    gains[p["sale"]["exit_at"].astimezone(NEW_YORK).strftime("%Y-%m")] += p["sale"]["gain"]
                    reasons[p["sale"]["reason"]] += 1
                else:
                    still.append({"symbol": p["symbol"], "bought": p["day"].isoformat(),
                                  "open_gain": str((AMOUNT / p["entry"] * p["last"] - AMOUNT).quantize(Decimal("0.01")))})
            held_days = [((p["sale"]["exit_at"] - p["buy_at"]).total_seconds() / 86400) for p in closed if p["sale"]]
            accounts[f"{m}|{variant}"] = {
                "method": m, "variant": variant, "trades": len(closed), "reasons": dict(reasons),
                "net": str(sum(gains.values(), Decimal(0)).quantize(Decimal("0.01"))),
                "by_month": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(gains.items())},
                "losing_months": sum(1 for v in gains.values() if v < 0),
                "longest_hold_days": round(max(held_days, default=0), 1), "still_held": still}

    base = {mo: h / n for mo, (h, n) in hits["repere"].items() if n}
    base_rate = sum(h for h, _ in hits["repere"].values()) / sum(n for _, n in hits["repere"].values())
    methods = []
    for m, label in METHODS.items():
        key = m.split("_")[0]
        total_h = sum(h for h, _ in hits[key].values())
        total_n = sum(n for _, n in hits[key].values())
        rate = total_h / total_n if total_n else 0
        months_better = sum(1 for mo, (h, n) in hits[key].items() if n and h / n > base.get(mo, 0))
        best = max((accounts[f"{m}|{v}"] for v in IF_NEGATIVE), key=lambda a: Decimal(a["net"]))
        passed = rate >= 1.5 * base_rate and months_better >= 8 and Decimal(best["net"]) > 0
        methods.append({"method": m, "label": label, "hit_rate_3h30": rate, "positions": total_n,
                        "months_better_than_baseline": months_better, "months": len(hits[key]),
                        "mean_minutes_to_target": float(np.mean(durations[key]) / 60) if durations[key] else None,
                        "passed": passed,
                        "accounts": {v: accounts[f"{m}|{v}"] for v in IF_NEGATIVE}})
    winners = sorted((x for x in methods if x["passed"]),
                     key=lambda x: max(Decimal(a["net"]) for a in x["accounts"].values()), reverse=True)
    payload = {
        "run_id": next_run_id(STORAGE), "family": "volatilite", "variant": "test_paires", "status": "diagnostic",
        "session_date": END.isoformat(), "decision_time": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(), "git_sha": git_sha, "preregistration": "T28",
        "period": [START.isoformat(), END.isoformat()], "sessions": len(tested), "symbols": symbols,
        "baseline": {"hit_rate_3h30": base_rate, "positions": sum(n for _, n in hits["repere"].values()),
                     "mean_minutes_to_target": float(np.mean(durations["repere"]) / 60) if durations["repere"] else None},
        "winner": winners[0]["method"] if winners else None,
        "selection": methods,
    }
    path = save_run(STORAGE, payload)
    print(f"Run {payload['run_id']} ({path}) — repère : {base_rate:.1%} des positions à +200 $ en 3 h 30")
    for x in methods:
        nets = " · ".join(f"{v} {x['accounts'][v]['net']} $" for v in IF_NEGATIVE)
        print(f"{x['method']:<28} {x['hit_rate_3h30']:6.1%}  mieux que le repère {x['months_better_than_baseline']}/"
              f"{x['months']} mois  {'RETENUE' if x['passed'] else '—':8} {nets}")
    print(f"Gagnante : {payload['winner']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
