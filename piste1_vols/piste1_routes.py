"""
OzeRoute — Piste 1 : Programmes de vols via AirLabs Routes Database
====================================================================
Objectif : cartographier les routes opérées vers CDG, Orly et Beauvais
depuis les marchés sources OzeRoute (France, Italie, Espagne, UK).

Endpoint utilisé : /routes (Routes Database)
  - Donne les routes récurrentes avec jours d'opération et horaires
  - Pas de limite temporelle (≠ /schedules qui est live à 10h max)
  - Plan gratuit : 50 résultats/requête — pagination via offset

IMPORTANT : ce script ne produit pas de données temps réel.
Il produit une structure de référence hebdomadaire (quelles routes,
quels jours, quelle fréquence) à croiser avec l'index Piste 2.

Usage :
  1. Créer un compte gratuit sur https://airlabs.co/signup
  2. Copier la clé API depuis https://airlabs.co/account
  3. Remplacer YOUR_API_KEY_HERE ci-dessous (ou passer via variable d'env)
  4. python3 piste1_routes.py

Sortie : ozeroute_routes_piste1.csv
"""

import os
import csv
import time
import json
from datetime import datetime

try:
    import requests
except ImportError:
    raise SystemExit("pip install requests --break-system-packages")

# ── Configuration ─────────────────────────────────────────────
API_KEY = os.environ.get("AIRLABS_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://airlabs.co/api/v9"
from pathlib import Path as _Path
OUTPUT_PATH = str(_Path(__file__).parent.parent / "output" / "ozeroute_routes_piste1.csv")

# Aéroports cibles OzeRoute (IATA)
TARGET_AIRPORTS = {
    "CDG": "Paris Charles de Gaulle",
    "ORY": "Paris Orly",
    "BVA": "Paris Beauvais",
}

# Marchés sources OzeRoute → pays IATA
# Utilisé pour filtrer les routes pertinentes dans les résultats
SOURCE_COUNTRIES = {
    "IT": "Italie",
    "GB": "UK",
    "ES": "Espagne",
    "FR": "France",   # domestique — vols intérieurs vers Paris
}

# Compagnies low-cost prioritaires sur Beauvais (cf. document de cadrage)
LOWCOST_CARRIERS_BVA = {"FR", "W6", "V7"}  # Ryanair, Wizz Air, Volotea

# Champs à récupérer (économise des appels et de la bande passante)
FIELDS = "airline_iata,flight_iata,dep_iata,arr_iata,dep_time,arr_time,days"

# Rate limiting : plan gratuit AirLabs = 1000 appels/mois, pas de limite/seconde documentée
# On reste conservateur à 1 appel/seconde pour éviter les 429
REQUEST_DELAY = 1.0


# ── Fonctions utilitaires ──────────────────────────────────────

def fetch_routes(dep_iata: str = None, arr_iata: str = None,
                 airline_iata: str = None, offset: int = 0) -> dict:
    """
    Appel à l'endpoint /routes d'AirLabs.
    Retourne le JSON brut ou lève une exception si l'API répond une erreur.
    """
    params = {
        "api_key": API_KEY,
        "_fields": FIELDS,
        "limit": 50,   # max plan gratuit
        "offset": offset,
    }
    if dep_iata:
        params["dep_iata"] = dep_iata
    if arr_iata:
        params["arr_iata"] = arr_iata
    if airline_iata:
        params["airline_iata"] = airline_iata

    resp = requests.get(f"{BASE_URL}/routes", params=params, timeout=15)

    if resp.status_code == 401:
        raise SystemExit("❌ Clé API invalide ou expirée. Vérifier sur https://airlabs.co/account")
    if resp.status_code == 429:
        raise SystemExit("❌ Rate limit atteint. Relancer demain ou passer au plan payant.")
    resp.raise_for_status()

    return resp.json()


def paginate_routes(dep_iata: str = None, arr_iata: str = None,
                    airline_iata: str = None) -> list:
    """
    Récupère toutes les pages de résultats pour une requête donnée.
    S'arrête quand request.has_more = False ou qu'on a ≥ 10 pages
    (sécurité pour le plan gratuit — 10 pages × 50 = 500 appels max par requête).
    """
    all_routes = []
    offset = 0
    max_pages = 10

    for page in range(max_pages):
        data = fetch_routes(dep_iata=dep_iata, arr_iata=arr_iata,
                            airline_iata=airline_iata, offset=offset)

        routes = data.get("response", [])
        request_meta = data.get("request", {})

        if not routes:
            break

        all_routes.extend(routes)
        print(f"  Page {page+1} : {len(routes)} routes récupérées (total : {len(all_routes)})")

        if not request_meta.get("has_more", False):
            break

        offset += 50
        time.sleep(REQUEST_DELAY)

    return all_routes


def is_source_market_route(route: dict, source_airport_countries: dict) -> bool:
    """
    Filtre : garde seulement les routes dont l'aéroport de départ
    est dans un pays marché source OzeRoute.
    Nécessite d'avoir chargé le mapping airport→country au préalable.
    """
    dep = route.get("dep_iata", "")
    return dep in source_airport_countries


def parse_days(days_raw) -> str:
    """
    AirLabs renvoie les jours d'opération sous différentes formes :
    - liste d'entiers [1,2,3,4,5] (1=lundi, 7=dimanche)
    - string "1234567"
    - null/None si tous les jours
    Normalise en string lisible "Lun-Mar-Mer-Jeu-Ven" ou "Quotidien".
    """
    DAY_NAMES = {1:"Lun", 2:"Mar", 3:"Mer", 4:"Jeu", 5:"Ven", 6:"Sam", 7:"Dim"}

    if not days_raw:
        return "Quotidien"

    if isinstance(days_raw, list):
        day_nums = [int(d) for d in days_raw if str(d).isdigit()]
    elif isinstance(days_raw, str):
        day_nums = [int(c) for c in days_raw if c.isdigit()]
    else:
        return "?"

    if len(day_nums) == 7:
        return "Quotidien"

    return "-".join(DAY_NAMES.get(d, str(d)) for d in sorted(day_nums))


def classify_route(dep_iata: str, arr_iata: str, airline_iata: str,
                   airport_country_map: dict) -> dict:
    """
    Ajoute des métadonnées OzeRoute à une route :
    - marché source
    - catégorie de compagnie (low-cost / réseau / charter)
    - aéroport cible OzeRoute
    """
    arr_label = TARGET_AIRPORTS.get(arr_iata, arr_iata)
    dep_country = airport_country_map.get(dep_iata, "??")
    source_market = SOURCE_COUNTRIES.get(dep_country, None)

    if airline_iata in LOWCOST_CARRIERS_BVA and arr_iata == "BVA":
        carrier_type = "low-cost Beauvais"
    elif airline_iata in {"BA", "IB", "AZ", "AF", "LH", "KL", "VY", "U2"}:
        carrier_type = "réseau/hybride"
    else:
        carrier_type = "autre"

    return {
        "source_market": source_market or "Autre",
        "source_country": dep_country,
        "target_airport": arr_label,
        "carrier_type": carrier_type,
    }


def load_airport_country_map(api_key: str) -> dict:
    """
    Charge un mapping IATA code → pays (country_code) depuis l'Airports DB AirLabs.
    On télécharge les aéroports des pays sources en plusieurs requêtes.
    Retourne un dict { "LGW": "GB", "FCO": "IT", ... }
    """
    mapping = {}
    countries_to_fetch = list(SOURCE_COUNTRIES.keys())

    for country_code in countries_to_fetch:
        print(f"  Chargement airports DB pour {country_code}...")
        params = {
            "api_key": api_key,
            "country_code": country_code,
            "_fields": "iata_code,country_code",
            "limit": 200,
        }
        resp = requests.get(f"{BASE_URL}/airports", params=params, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠️  Impossible de charger airports pour {country_code}: {resp.status_code}")
            continue

        airports = resp.json().get("response", [])
        for ap in airports:
            iata = ap.get("iata_code")
            country = ap.get("country_code")
            if iata and country:
                mapping[iata] = country

        print(f"  → {len(airports)} aéroports chargés pour {country_code}")
        time.sleep(REQUEST_DELAY)

    return mapping


# ── Pipeline principal ─────────────────────────────────────────

def main():
    if API_KEY == "YOUR_API_KEY_HERE":
        print("⚠️  Clé API non configurée.")
        print("   1. Créer un compte sur https://airlabs.co/signup (gratuit)")
        print("   2. Récupérer la clé sur https://airlabs.co/account")
        print("   3. Lancer : AIRLABS_API_KEY=ta_cle python3 piste1_routes.py")
        print("\n   En attendant, voici la structure du CSV qui sera produit :\n")
        print_csv_schema()
        return

    print(f"\n{'='*60}")
    print("OzeRoute — Piste 1 : Collecte routes aériennes")
    print(f"Aéroports cibles : {', '.join(TARGET_AIRPORTS.keys())}")
    print(f"Marchés sources  : {', '.join(SOURCE_COUNTRIES.values())}")
    print(f"{'='*60}\n")

    # Étape 1 : charger le mapping airports → pays
    print("→ Étape 1/3 : Chargement mapping aéroports → pays...")
    airport_country_map = load_airport_country_map(API_KEY)
    print(f"  {len(airport_country_map)} aéroports indexés\n")

    # Étape 2 : collecter les routes arrivant dans les 3 aéroports OzeRoute
    all_routes_raw = []
    print("→ Étape 2/3 : Collecte des routes entrantes CDG / ORY / BVA...")

    for iata_code, airport_name in TARGET_AIRPORTS.items():
        print(f"\n  [{iata_code}] {airport_name}")
        routes = paginate_routes(arr_iata=iata_code)
        for r in routes:
            r["_target_airport_iata"] = iata_code  # tag pour traçabilité
        all_routes_raw.extend(routes)
        time.sleep(REQUEST_DELAY)

    print(f"\n  Total brut : {len(all_routes_raw)} routes collectées")

    # Étape 3 : filtrer les routes depuis marchés sources et enrichir
    print("\n→ Étape 3/3 : Filtrage et enrichissement...")

    rows_out = []
    for route in all_routes_raw:
        dep = route.get("dep_iata", "")
        arr = route.get("arr_iata", route.get("_target_airport_iata", ""))
        dep_country = airport_country_map.get(dep, "??")

        # Garder seulement les routes depuis les marchés sources
        if dep_country not in SOURCE_COUNTRIES:
            continue

        meta = classify_route(dep, arr, route.get("airline_iata", ""), airport_country_map)

        rows_out.append({
            "dep_iata": dep,
            "dep_country": dep_country,
            "source_market": meta["source_market"],
            "carrier_type": meta["carrier_type"],
            "arr_iata": arr,
            "target_airport": meta["target_airport"],
            "airline_iata": route.get("airline_iata", ""),
            "flight_iata": route.get("flight_iata", ""),
            "dep_time": route.get("dep_time", ""),
            "arr_time": route.get("arr_time", ""),
            "jours_operation": parse_days(route.get("days")),
        })

    print(f"  {len(rows_out)} routes retenues (marchés sources uniquement)")

    # Écriture CSV
    if not rows_out:
        print("\n⚠️  Aucune route retenue — vérifier les filtres ou la clé API.")
        return

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows_out[0].keys())
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\n✅ CSV écrit : {OUTPUT_PATH}")
    print(f"   {len(rows_out)} routes — {len(set(r['dep_iata'] for r in rows_out))} aéroports de départ")
    print_summary(rows_out)


def print_summary(rows: list):
    """Affiche un résumé par marché source et par aéroport cible."""
    from collections import Counter
    print("\n── Résumé par marché source ──")
    market_counts = Counter(r["source_market"] for r in rows)
    for market, count in sorted(market_counts.items(), key=lambda x: -x[1]):
        print(f"  {market:<12} : {count:>4} routes")

    print("\n── Résumé par aéroport cible ──")
    airport_counts = Counter(r["arr_iata"] for r in rows)
    for airport, count in sorted(airport_counts.items(), key=lambda x: -x[1]):
        label = TARGET_AIRPORTS.get(airport, airport)
        print(f"  {label:<30} : {count:>4} routes")

    print("\n── Low-cost Beauvais (priorité signal IT/ES) ──")
    bva_lc = [r for r in rows if r["arr_iata"] == "BVA" and r["carrier_type"] == "low-cost Beauvais"]
    if bva_lc:
        for r in sorted(bva_lc, key=lambda x: x["dep_time"]):
            print(f"  {r['airline_iata']} {r['flight_iata']:<10} {r['dep_iata']} → BVA  "
                  f"{r['dep_time']} [{r['jours_operation']}]  ({r['source_market']})")
    else:
        print("  Aucune route low-cost Beauvais dans le marché sources (normal si clé non configurée)")


def print_csv_schema():
    """Affiche la structure du CSV en mode dry-run."""
    headers = [
        "dep_iata", "dep_country", "source_market", "carrier_type",
        "arr_iata", "target_airport", "airline_iata", "flight_iata",
        "dep_time", "arr_time", "jours_operation"
    ]
    print("Colonnes du CSV de sortie :")
    for h in headers:
        print(f"  - {h}")
    print("\nExemple de ligne attendue :")
    print("  FCO | IT | Italie | réseau/hybride | CDG | Paris Charles de Gaulle | AZ | AZ318 | 08:15 | 10:25 | Lun-Mer-Ven-Sam")
    print("  BGY | IT | Italie | low-cost Beauvais | BVA | Paris Beauvais | FR | FR1234 | 06:45 | 09:00 | Quotidien")


if __name__ == "__main__":
    main()
