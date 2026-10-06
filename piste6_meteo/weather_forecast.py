"""
OzeRoute — Piste 6 : Météo prévue
===================================
Signal court terme : prévision météo 7-16 jours pour les zones
des 3 aéroports (CDG, ORY, BVA) via Open-Meteo (gratuit, sans clé API).

Rôle dans le cadrage : affinage tactique (5 % — horizon 1-4 semaines).
La météo influence les excursions et les annulations de dernière minute.

Logique :
  - Bon temps (peu de pluie, T° agréable) → légère hausse de demande
  - Mauvais temps (forte pluie, froid) → légère baisse
  - Impact maximal ±0.15 sur l'indice (signal faible, affinement seulement)

Mode LIVE (défaut) : appel Open-Meteo — gratuit, aucune clé.
Mode CALIBRÉ (fallback) : profil météo historique moyen Paris été 2022-2024.
"""

from datetime import date, timedelta
from pathlib import Path
import csv

AIRPORTS = {
    "CDG": {"lat": 49.009, "lon": 2.547,  "label": "Charles-de-Gaulle"},
    "ORY": {"lat": 48.725, "lon": 2.359,  "label": "Orly"},
    "BVA": {"lat": 49.454, "lon": 2.112,  "label": "Beauvais-Tillé"},
}

# Profil calibré (fallback) — précipitations hebdo moyennes Paris 2022-2024
# Source : Météo-France / ERA5 reanalysis — mm/semaine
CALIBRATED_RAIN_MM = {
    6: 18, 7: 16, 8: 18, 9: 22, 10: 35,
}
CALIBRATED_TEMP_C = {
    6: 20, 7: 23, 8: 23, 9: 19, 10: 14,
}


def _weather_impact(rain_mm: float, temp_c: float) -> float:
    """
    Convertit pluie + température en facteur d'impact [-0.15 → +0.15].
    Logique métier OzeRoute :
      - Pluie forte (>40mm/sem) → annulations excursions → -0.10 à -0.15
      - Bon soleil (rain<10, T>20) → bonus loisirs → +0.05 à +0.10
      - Neutre sinon
    """
    rain_score = 0.0
    if rain_mm < 10:   rain_score = +0.08
    elif rain_mm < 20: rain_score = +0.03
    elif rain_mm < 35: rain_score = -0.03
    elif rain_mm < 50: rain_score = -0.08
    else:              rain_score = -0.15

    temp_score = 0.0
    if temp_c >= 22:   temp_score = +0.05
    elif temp_c >= 17: temp_score = +0.02
    elif temp_c >= 12: temp_score = -0.02
    else:              temp_score = -0.05

    return round(max(-0.15, min(0.15, rain_score + temp_score)), 3)


def fetch_live_weather(lat: float, lon: float, start: date, end: date):
    """Appel Open-Meteo — gratuit, aucune clé."""
    try:
        import requests
        params = {
            "latitude":  lat,
            "longitude": lon,
            "daily": "precipitation_sum,temperature_2m_max",
            "start_date": start.isoformat(),
            "end_date":   end.isoformat(),
            "timezone":   "Europe/Paris",
        }
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json().get("daily", {})
        rain_vals = data.get("precipitation_sum", [])
        temp_vals = data.get("temperature_2m_max", [])
        if not rain_vals:
            return None
        rain_mm = sum(v for v in rain_vals if v is not None)
        temp_c  = sum(v for v in temp_vals if v is not None) / max(len(temp_vals), 1)
        return {"rain_mm": round(rain_mm, 1), "temp_c": round(temp_c, 1)}
    except Exception:
        return None


def calibrated_weather(month: int):
    rain = CALIBRATED_RAIN_MM.get(month, 25)
    temp = CALIBRATED_TEMP_C.get(month, 18)
    return {"rain_mm": rain, "temp_c": temp}


def week_range(start: date, end: date):
    monday = start - timedelta(days=start.weekday())
    current = monday
    while current <= end:
        yield current
        current += timedelta(days=7)


def main():
    today = date.today()
    # Use P2 week range so past weeks (e.g. September) are covered
    p2_file = Path(__file__).parent.parent / "output" / "ozeroute_overlap_index_semaine_2026.csv"
    if p2_file.exists():
        import csv as _csv
        with open(p2_file) as _f:
            _rows = list(_csv.DictReader(_f))
        p2_starts = sorted(r["semaine_debut"] for r in _rows if r.get("semaine_debut"))
        analysis_start = date.fromisoformat(p2_starts[0])  if p2_starts else date(2026, 6, 1)
        analysis_end   = date.fromisoformat(p2_starts[-1]) if p2_starts else today + timedelta(weeks=8)
    else:
        analysis_start = date(2026, 6, 1)
        analysis_end   = today + timedelta(weeks=8)

    rows = []
    for w_start in week_range(analysis_start, analysis_end):
        w_end   = w_start + timedelta(days=6)
        # Only fetch if week is within 16-day forecast window
        live_possible = (w_start - today).days <= 14

        for apt_code, apt in AIRPORTS.items():
            if live_possible:
                wx = fetch_live_weather(apt["lat"], apt["lon"], w_start,
                                        min(w_end, today + timedelta(days=15)))
                source = "Open-Meteo live"
            else:
                wx = None

            if wx is None:
                wx     = calibrated_weather(w_start.month)
                source = "Calibré historique Paris 2022-2024"

            impact = _weather_impact(wx["rain_mm"], wx["temp_c"])

            if impact >= 0.08:    label = "Très favorable"
            elif impact >= 0.03:  label = "Favorable"
            elif impact >= -0.03: label = "Neutre"
            elif impact >= -0.08: label = "Défavorable"
            else:                 label = "Très défavorable"

            rows.append({
                "semaine_debut":   w_start.isoformat(),
                "semaine_fin":     w_end.isoformat(),
                "airport":         apt_code,
                "airport_label":   apt["label"],
                "rain_mm":         wx["rain_mm"],
                "temp_c":          wx["temp_c"],
                "meteo_impact":    impact,
                "label_meteo":     label,
                "source":          source,
            })

    out_dir = Path(__file__).parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "ozeroute_meteo_prevue.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV écrit : {out_path}")
    print(f"{len(rows)} entrées (aéroport × semaine)\n")
    for r in rows:
        print(f"  {r['airport']}  {r['semaine_debut']}  "
              f"pluie={r['rain_mm']}mm  T={r['temp_c']}°C  "
              f"impact={r['meteo_impact']:+.2f}  {r['label_meteo']}  [{r['source']}]")

    return rows


if __name__ == "__main__":
    main()
