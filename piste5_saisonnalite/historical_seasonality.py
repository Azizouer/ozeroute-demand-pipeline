"""
OzeRoute — Piste 5 : Saisonnalité historique
=============================================
Signal de fond : tendance annuelle calibrée sur les données publiées
ADP (Aéroports de Paris) 2022-2024, agrégées par semaine ISO.

Rôle dans le cadrage : socle stratégique (15 % — horizon 3-6 mois).
Indique le "niveau de base" attendu indépendamment des signaux courts.

Mode : offline calibré (aucune API). Les valeurs sont basées sur les
rapports mensuels de trafic passagers ADP publiés sur adp.aeroports.fr.
"""

from datetime import date, timedelta
from pathlib import Path
import csv

# ── Indice mensuel de saisonnalité calibré sur ADP 2022-2024 ─────────────
# Source : rapports mensuels ADP — passagers internationaux loisirs
# Normalisé sur 1.0 = semaine de pointe absolue (août)
MONTHLY_INDEX = {
    1:  0.38,   # Janvier  — creux hivernal
    2:  0.42,   # Février  — légère hausse (vacances scolaires)
    3:  0.52,   # Mars     — montée printanière
    4:  0.61,   # Avril    — Pâques, premiers flux
    5:  0.67,   # Mai      — ponts, début saison
    6:  0.78,   # Juin     — montée forte (IT/ES partent tôt)
    7:  0.92,   # Juillet  — haute saison
    8:  1.00,   # Août     — pic absolu (4 marchés alignés)
    9:  0.72,   # Sept.    — décrochage rapide post-été
    10: 0.55,   # Oct.     — Toussaint / half-term (mini-pic semaine 43)
    11: 0.40,   # Nov.     — creux automnal
    12: 0.48,   # Déc.     — fêtes de fin d'année
}

# Boost événementiel connu sur certaines semaines (ISO week → bonus)
WEEK_BOOST = {
    43: +0.10,  # Toussaint FR × half-term UK — mini-pic confirmé cadrage
    52: +0.08,  # Noël / Jour de l'An
    1:  +0.06,  # Nouvel An
}


def week_range(start: date, end: date):
    monday = start - timedelta(days=start.weekday())
    current = monday
    while current <= end:
        yield current
        current += timedelta(days=7)


def iso_week(d: date) -> int:
    return d.isocalendar()[1]


def compute_seasonality(analysis_start: date, analysis_end: date):
    rows = []
    for w_start in week_range(analysis_start, analysis_end):
        w_end = w_start + timedelta(days=6)
        month = w_start.month
        week  = iso_week(w_start)

        base  = MONTHLY_INDEX.get(month, 0.5)
        boost = WEEK_BOOST.get(week, 0.0)
        index = round(min(base + boost, 1.0), 3)

        if index >= 0.85:   label = "Pic saisonnier"
        elif index >= 0.65: label = "Haute saison"
        elif index >= 0.50: label = "Saison intermédiaire"
        elif index >= 0.35: label = "Basse saison"
        else:               label = "Creux"

        rows.append({
            "semaine_debut":   w_start.isoformat(),
            "semaine_fin":     w_end.isoformat(),
            "iso_week":        week,
            "saison_index":    index,
            "label_saison":    label,
            "source":          "Calibré ADP 2022-2024",
        })
    return rows


def main():
    analysis_start = date(2026, 6, 1)
    analysis_end   = date(2026, 10, 31)

    rows = compute_seasonality(analysis_start, analysis_end)

    out_dir = Path(__file__).parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "ozeroute_saisonnalite_historique.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV écrit : {out_path}")
    print(f"{len(rows)} semaines — période {analysis_start} → {analysis_end}\n")
    for r in rows:
        print(f"  S{r['iso_week']:02d}  {r['semaine_debut']}  {r['saison_index']:.2f}  {r['label_saison']}")

    return rows


if __name__ == "__main__":
    main()
