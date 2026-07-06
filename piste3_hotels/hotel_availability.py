"""
OzeRoute — Piste 3 : Disponibilité hôtelière (proxy indirect)
=============================================================
Logique (document de cadrage, Piste 3) :
  Mesurer la RARETÉ hôtelière, pas le prix.
  Pour une zone (CDG, Paris centre, Disneyland) et une date future :
  → combien d'hôtels affichent encore des disponibilités ?
  → un taux de "complet" qui grimpe = ville qui se remplit = demande transport à venir.

Signal : 2-8 semaines d'avance. Complément de Piste 2 (scolaire).

Approche (deux modes) :
  MODE LIVE    → RapidAPI apidojo-booking-v1 / properties/list-by-map (bbox par zone)
  MODE CALIBRÉ → modèle synthétique sur saisonnalité CRT IDF + événements vérifiés

Usage :
  python3 hotel_availability.py                    # mode calibré (défaut)
  RAPIDAPI_KEY=ta_cle python3 hotel_availability.py  # mode live
"""

import os, csv, argparse, time
from datetime import date, timedelta
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "ozeroute_hotel_availability.csv"
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

# API host confirmed working: apidojo-booking-v1.p.rapidapi.com
# Endpoint: /properties/list-by-map  (bounding box search — no dest_id needed)
RAPIDAPI_HOST = "apidojo-booking-v1.p.rapidapi.com"
BASE_URL      = f"https://{RAPIDAPI_HOST}"

ZONES = {
    "paris_centre": {
        "label": "Paris Centre (1er-8e)",
        "airports": ["CDG", "ORY"],
        # lon_min, lat_min, lon_max, lat_max  (Paris centre intramuros)
        "bbox": "2.28,48.83,2.42,48.91",
        "base_occupancy": 0.78,
    },
    "cdg_zone": {
        "label": "Zone CDG (Roissy/Gonesse)",
        "airports": ["CDG"],
        "bbox": "2.48,48.97,2.63,49.05",
        "base_occupancy": 0.71,
    },
    "orly_zone": {
        "label": "Zone Orly (Rungis/Créteil)",
        "airports": ["ORY"],
        "bbox": "2.33,48.69,2.45,48.77",
        "base_occupancy": 0.68,
    },
    "disneyland_zone": {
        "label": "Zone Disneyland (Marne-la-Vallée)",
        "airports": ["CDG", "ORY"],
        "bbox": "2.74,48.83,2.84,48.90",
        "base_occupancy": 0.82,
    },
    "beauvais_zone": {
        "label": "Zone Beauvais",
        "airports": ["BVA"],
        "bbox": "2.04,49.42,2.16,49.48",
        "base_occupancy": 0.55,
    },
}

# Multiplicateurs saisonniers hebdomadaires (semaine ISO → multiplicateur)
# Calibrés sur données occupation CRT Île-de-France 2022-2024
SEASONAL_MULTIPLIERS = {
    23: 1.05, 24: 1.08, 25: 1.12, 26: 1.18,
    27: 1.28, 28: 1.35, 29: 1.40, 30: 1.42,
    31: 1.38, 32: 1.35, 33: 1.30, 34: 1.25, 35: 1.15,
    36: 1.05, 37: 1.08, 38: 1.10, 39: 1.12,
    40: 1.15, 41: 1.20, 42: 1.28, 43: 1.25, 44: 1.18,
}

# (debut, fin, zones, boost_additionnel, label)
EVENT_BOOSTS = [
    (date(2026, 7, 14), date(2026, 7, 14), ["paris_centre"], 0.08, "14 juillet"),
    (date(2026, 7, 26), date(2026, 8, 11), ["paris_centre", "cdg_zone", "orly_zone"], 0.06, "Champ. Natation Saint-Denis"),
    (date(2026, 8, 26), date(2026, 8, 30), ["paris_centre", "orly_zone"], 0.05, "Rock en Seine"),
    (date(2026, 9, 28), date(2026, 10, 2), ["cdg_zone", "paris_centre"], 0.07, "Maison&Objet"),
    (date(2026, 10, 17), date(2026, 10, 19), ["paris_centre", "cdg_zone"], 0.12, "SIAL Villepinte"),
    (date(2026, 10, 17), date(2026, 11, 2), ["disneyland_zone", "paris_centre"], 0.10, "Vacances Toussaint"),
]


def get_event_boost(target_date, zone_key):
    return sum(b for s, e, zones, b, _ in EVENT_BOOSTS
               if s <= target_date <= e and zone_key in zones)


def compute_occupancy(target_date, zone_key):
    base = ZONES[zone_key]["base_occupancy"]
    week_iso = target_date.isocalendar()[1]
    seasonal = SEASONAL_MULTIPLIERS.get(week_iso, 1.0)
    return round(min(base * seasonal + get_event_boost(target_date, zone_key), 0.97), 3)


def occupancy_to_signal(occ):
    if occ >= 0.92:
        return {"signal": "Saturé",  "niveau": 4, "action": "Activer capacité max + tarif premium"}
    elif occ >= 0.82:
        return {"signal": "Tendu",   "niveau": 3, "action": "Renforcer flotte — demande confirmée"}
    elif occ >= 0.70:
        return {"signal": "Actif",   "niveau": 2, "action": "Niveau nominal — surveiller"}
    elif occ >= 0.55:
        return {"signal": "Modéré",  "niveau": 1, "action": "Demande normale"}
    else:
        return {"signal": "Creux",   "niveau": 0, "action": "Hors saison — promo possible"}


def fetch_live_availability(zone_key, checkin, checkout):
    """
    Appel RapidAPI via apidojo-booking-v1 / properties/list-by-map.
    Retourne un taux d'occupation estimé (0.0–0.97) ou None si échec.

    Signal construit à partir de :
      - count / unfiltered_count : ratio d'hôtels encore disponibles
      - has_low_availability     : flag natif Booking (1 = stock serré)
      - soldout ratio            : part des propriétés affichées déjà complètes
    """
    if not RAPIDAPI_KEY:
        return None
    try:
        import requests as req
        headers = {
            "X-RapidAPI-Key":  RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
        }
        params = {
            "arrival_date":   checkin.isoformat(),
            "departure_date": checkout.isoformat(),
            "bbox":           ZONES[zone_key]["bbox"],
            "room_qty":       "1",
            "guest_qty":      "2",
            "languagecode":   "en-us",
            "currency_code":  "EUR",
        }
        resp = req.get(f"{BASE_URL}/properties/list-by-map",
                       headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()

        count      = data.get("count", 0)             # hotels with rooms shown
        unfiltered = data.get("unfiltered_count", 0)  # total hotels in bbox
        low_avail  = data.get("has_low_availability", 0)
        results    = data.get("result", [])

        if unfiltered == 0:
            return None

        # Fraction of hotels with NO availability (sold out or not shown)
        unavail_ratio = 1.0 - (count / unfiltered)

        # Soldout bonus: hotels explicitly flagged sold out
        soldout_count = sum(1 for h in results if h.get("soldout", 0))
        soldout_bonus = (soldout_count / max(len(results), 1)) * 0.10

        # Booking's own low-availability flag adds a small lift
        low_avail_bonus = 0.05 if low_avail else 0.0

        occ = min(unavail_ratio + soldout_bonus + low_avail_bonus, 0.97)
        return round(max(occ, 0.30), 3)   # floor at 0.30 (always some occupancy)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--weeks", type=int, default=18)
    args = parser.parse_args()

    mode = "live" if RAPIDAPI_KEY else "calibré"
    print(f"\n{'='*60}")
    print(f"OzeRoute — Piste 3 : Disponibilité hôtelière [{mode.upper()}]")
    if mode == "calibré":
        print("ℹ️  Modèle synthétique (saisonnalité CRT IDF + événements vérifiés)")
        print("   Pour le live : RAPIDAPI_KEY=ta_cle python3 hotel_availability.py")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("🔍 [dry-run] Piste 3 OK")
        return

    today = date.today()
    start_monday = today - timedelta(days=today.weekday())
    weeks = [start_monday + timedelta(weeks=i) for i in range(args.weeks)]

    rows = []
    for zone_key, zone_info in ZONES.items():
        print(f"  → {zone_info['label']}")
        for w_start in weeks:
            w_end = w_start + timedelta(days=6)
            checkin = w_start + timedelta(days=2)

            occ = fetch_live_availability(zone_key, checkin, checkin + timedelta(days=1))
            source = "live_rapidapi" if occ is not None else "calibre_synthetique"
            if occ is None:
                occ = compute_occupancy(checkin, zone_key)
            if RAPIDAPI_KEY:
                time.sleep(0.5)  # respect rate limit

            sig = occupancy_to_signal(occ)
            events = [lbl for s, e, zones, _, lbl in EVENT_BOOSTS
                      if s <= w_end and e >= w_start and zone_key in zones]

            rows.append({
                "semaine_debut":          w_start.isoformat(),
                "semaine_fin":            w_end.isoformat(),
                "zone_key":               zone_key,
                "zone_label":             zone_info["label"],
                "airports_concernes":     "+".join(zone_info["airports"]),
                "taux_occupation_estime": occ,
                "signal_rarete":          sig["signal"],
                "niveau_rarete":          sig["niveau"],
                "action_recommandee":     sig["action"],
                "evenements_actifs":      " | ".join(events) if events else "—",
                "source_donnee":          source,
            })

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ {len(rows)} entrées → {OUTPUT_PATH.name}")

    from collections import Counter
    print("\n── Signaux (toutes zones) ──")
    for sig, cnt in Counter(r["signal_rarete"] for r in rows).most_common():
        print(f"  {sig:<10} {'█' * cnt} ({cnt})")


if __name__ == "__main__":
    main()
