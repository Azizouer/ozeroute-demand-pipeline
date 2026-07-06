"""
OzeRoute — Piste 2 : Calcul de l'index de superposition hebdomadaire
=====================================================================
Logique (cf. document de cadrage, Piste 2) :
  "Les 4 marchés ne partent pas aux mêmes dates, donc la demande réelle
   est leur superposition."

Pour chaque semaine ISO de juin à septembre 2026, on calcule :
  - le nombre de marchés en vacances cette semaine (0 à 4)
  - un index pondéré = somme des poids des marchés en vacances cette semaine
  - le détail des zones actives (pour traçabilité / debug)

Cet index est un signal de POSSIBILITÉ ("peuvent venir"), pas de décision.
Il doit être combiné à la Piste 1 (programmes de vols) pour devenir un signal
de confirmation actionnable. Ne pas l'utiliser seul pour dimensionner la flotte.

Sortie : CSV semaine-par-semaine + résumé texte, prêt pour le dashboard / pptx.
"""

import csv
from datetime import date, timedelta
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from calendar_data import SUMMER_HOLIDAYS_2026, SHOULDER_HOLIDAYS_2026, MARKET_WEIGHTS, ZONE_WEIGHT_SHARE


def week_range(start: date, end: date):
    """Génère les lundis de chaque semaine ISO entre start et end inclus."""
    monday = start - timedelta(days=start.weekday())
    current = monday
    while current <= end:
        yield current
        current += timedelta(days=7)


def overlaps(period_start: date, period_end: date, week_start: date, week_end: date) -> bool:
    return period_start <= week_end and period_end >= week_start


def zone_weight(market: str, zone: str) -> float:
    """Poids absolu d'une zone = poids du marché × part de la zone dans ce marché."""
    share = ZONE_WEIGHT_SHARE.get((market, zone), 1.0)  # fallback 100% si zone unique
    return MARKET_WEIGHTS.get(market, 0) * share


def compute_weekly_index(holidays: list, analysis_start: date, analysis_end: date):
    """
    Index de superposition pondéré à la granularité ZONE (pas marché entier).
    Une semaine où seules 2 des 3 zones italiennes sont parties pèse moins
    qu'une semaine où les 3 le sont — c'est ce qui préserve le signal de décalage
    interne à chaque marché (l'insight central de la Piste 2).
    """
    rows = []
    for w_start in week_range(analysis_start, analysis_end):
        w_end = w_start + timedelta(days=6)

        markets_active = set()
        zones_active = []
        weighted_sum = 0.0

        for h in holidays:
            if overlaps(h["start"], h["end"], w_start, w_end):
                markets_active.add(h["market"])
                zones_active.append(f"{h['market']} — {h['zone']}")
                weighted_sum += zone_weight(h["market"], h["zone"])

        rows.append(dict(
            week_start=w_start,
            week_end=w_end,
            n_markets_active=len(markets_active),
            markets_active=sorted(markets_active),
            overlap_index=round(min(weighted_sum, 1.0), 3),
            zones_detail=zones_active,
        ))
    return rows


def classify_intensity(overlap_index: float) -> str:
    """Bandes de lecture pour le dashboard — seuils calibrés sur poids marchés (somme=1.0)."""
    if overlap_index >= 0.85:
        return "Pic — 4 marchés alignés"
    elif overlap_index >= 0.60:
        return "Fort — 3 marchés alignés"
    elif overlap_index >= 0.35:
        return "Modéré — 2 marchés alignés"
    elif overlap_index > 0:
        return "Faible — 1 marché actif"
    else:
        return "Hors saison"


def main():
    analysis_start = date(2026, 6, 1)
    analysis_end = date(2026, 9, 30)

    all_holidays = SUMMER_HOLIDAYS_2026 + SHOULDER_HOLIDAYS_2026
    rows = compute_weekly_index(all_holidays, analysis_start, analysis_end)

    from pathlib import Path
    out_dir = Path(__file__).parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = str(out_dir / "ozeroute_overlap_index_semaine_2026.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "semaine_debut", "semaine_fin", "nb_marches_actifs",
            "marches_actifs", "index_superposition", "intensite", "zones_detail"
        ])
        for r in rows:
            writer.writerow([
                r["week_start"].isoformat(),
                r["week_end"].isoformat(),
                r["n_markets_active"],
                "+".join(r["markets_active"]) if r["markets_active"] else "—",
                r["overlap_index"],
                classify_intensity(r["overlap_index"]),
                " | ".join(r["zones_detail"]) if r["zones_detail"] else "—",
            ])

    print(f"CSV écrit : {out_path}")
    print(f"{len(rows)} semaines calculées ({analysis_start} -> {analysis_end})\n")

    print(f"{'Semaine':<24} {'Marchés':<8} {'Index':<7} {'Intensité'}")
    print("-" * 75)
    for r in rows:
        label = f"{r['week_start'].strftime('%d %b')} - {r['week_end'].strftime('%d %b')}"
        markets_str = "+".join(m[:2].upper() for m in r["markets_active"]) if r["markets_active"] else "—"
        print(f"{label:<24} {markets_str:<8} {r['overlap_index']:<7} {classify_intensity(r['overlap_index'])}")

    return rows


if __name__ == "__main__":
    main()
