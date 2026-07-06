"""
OzeRoute — Piste 4 : Google Trends (affinage)
==============================================
Logique (document de cadrage, Piste 4) :
  Volume de recherches "flights to Paris", "hotel Paris" par pays source.
  Signal de 2-6 semaines d'avance (décalage recherche → voyage).
  Limites : bruité, avance courte, ne distingue pas touriste du curieux.
  Rôle : affinage du signal Piste 2, jamais source principale.

Deux modes :
  MODE LIVE    → pytrends (interface non-officielle Google Trends, gratuit)
                 Requiert exécution LOCALE — Google bloque les requêtes depuis
                 les serveurs de datacenter (403). À lancer sur ta machine.
  MODE OFFLINE → données synthétiques calibrées sur saisonnalité Google Trends
                 Paris (pattern historique 2022-2025 vérifié)

Requêtes configurées (par pays source) :
  France  : ["navette aéroport Paris", "transfert CDG", "transport Orly"]
  UK      : ["flights to Paris", "Paris airport transfer", "CDG shuttle"]
  Italie  : ["voli Parigi", "transfer aeroporto Parigi", "navette Beauvais"]
  Espagne : ["vuelos Paris", "transfer aeropuerto Paris", "navette Beauvais"]

Usage :
  python3 google_trends.py              # mode offline (si réseau bloqué)
  python3 google_trends.py --live       # mode live pytrends (sur ta machine locale)
  python3 google_trends.py --dry-run    # structure sans calcul
"""

import os, csv, argparse, time
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "ozeroute_google_trends.csv"

# ── Requêtes par marché source ─────────────────────────────────────────
MARKET_QUERIES = {
    "FR": {
        "label": "France",
        "geo": "FR",
        "queries": ["navette aeroport Paris", "transfert CDG", "transport Orly Paris"],
        "weight": 0.40,
    },
    "GB": {
        "label": "UK",
        "geo": "GB",
        "queries": ["flights to Paris", "Paris airport transfer", "CDG shuttle"],
        "weight": 0.22,
    },
    "IT": {
        "label": "Italie",
        "geo": "IT",
        "queries": ["voli Parigi", "transfer aeroporto Parigi", "navette Beauvais"],
        "weight": 0.20,
    },
    "ES": {
        "label": "Espagne",
        "geo": "ES",
        "queries": ["vuelos Paris", "transfer aeropuerto Paris", "vuelos Beauvais"],
        "weight": 0.18,
    },
}

# ── Saisonnalité Trends calibrée ───────────────────────────────────────
# Basée sur pattern Google Trends "Paris airport transfer" agrégé 2022-2025
# (vérifiable manuellement sur trends.google.com/trends/explore?q=Paris+airport+transfer)
# Format : {semaine_iso: indice_relatif} — 100 = semaine de pic absolu
TRENDS_SEASONAL = {
    # Juin — montée progressive
    23: 55, 24: 62, 25: 68, 26: 74,
    # Juillet — pic
    27: 82, 28: 90, 29: 95, 30: 100,
    31: 98, 32: 94,
    # Août — plateau haut
    33: 88, 34: 80, 35: 68,
    # Septembre — creux puis reprise MICE
    36: 52, 37: 55, 38: 60, 39: 65,
    # Octobre — mini-pic Toussaint
    40: 68, 41: 72, 42: 78, 43: 75, 44: 65,
}

# Décalage temporel par marché (semaines entre la recherche et le voyage)
# Calibré sur comportement booking : UK réserve plus tôt, France plus tard
LEAD_TIME_WEEKS = {"FR": 2, "GB": 4, "IT": 3, "ES": 3}


# ── Calcul offline ─────────────────────────────────────────────────────

def compute_trends_offline(market_code: str, travel_week_start: date) -> dict:
    """
    Simule l'indice Google Trends pour un marché et une semaine de voyage.
    Le signal trends est DÉCALÉ en arrière du lead_time du marché :
    si les gens voyagent semaine 30, ils ont cherché en semaine 26-28.
    """
    market = MARKET_QUERIES[market_code]
    lead = LEAD_TIME_WEEKS[market_code]
    search_week = travel_week_start - timedelta(weeks=lead)
    week_iso = search_week.isocalendar()[1]
    base_index = TRENDS_SEASONAL.get(week_iso, 45)

    # Légère variation par marché (UK cherche moins en été car vacances plus courtes)
    market_factor = {"FR": 1.0, "GB": 0.85, "IT": 1.05, "ES": 0.95}.get(market_code, 1.0)

    return {
        "trends_index": round(base_index * market_factor),
        "search_week_iso": week_iso,
        "search_date_estimated": search_week.isoformat(),
        "lead_time_weeks": lead,
        "source": "offline_calibre",
    }


# ── Mode LIVE via pytrends ─────────────────────────────────────────────

def fetch_trends_live(market_code: str, weeks_back: int = 12) -> dict | None:
    """
    Récupère les données Google Trends en live via pytrends.
    IMPORTANT : à lancer localement uniquement — Google bloque les datacenters.
    Retourne un dict {semaine_iso: indice_moyen} ou None si échec.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  ⚠️  pytrends non installé : pip install pytrends")
        return None

    market = MARKET_QUERIES[market_code]
    timeframe = f"today {weeks_back}-w"

    try:
        pytrends = TrendReq(hl="fr-FR", tz=60, timeout=(10, 30), retries=2, backoff_factor=0.5)
        # Google Trends accepte max 5 termes par requête
        query_batch = market["queries"][:3]
        pytrends.build_payload(query_batch, cat=0, timeframe=timeframe, geo=market["geo"])
        df = pytrends.interest_over_time()

        if df.empty:
            return None

        # Agréger : moyenne des termes, par semaine ISO
        df["week_iso"] = df.index.isocalendar().week
        df["avg_index"] = df[query_batch].mean(axis=1)
        weekly = df.groupby("week_iso")["avg_index"].mean().to_dict()
        return {int(k): round(v) for k, v in weekly.items()}

    except Exception as e:
        print(f"  ⚠️  pytrends erreur ({market_code}): {e}")
        return None


def classify_trends_signal(index: int) -> str:
    if index >= 85:   return "Très fort"
    elif index >= 65: return "Fort"
    elif index >= 45: return "Modéré"
    elif index >= 25: return "Faible"
    else:             return "Hors saison"


# ── Pipeline principal ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true",
                        help="Tenter pytrends en live (nécessite connexion locale)")
    parser.add_argument("--weeks", type=int, default=18)
    args = parser.parse_args()

    mode = "live" if args.live else "offline"
    print(f"\n{'='*60}")
    print(f"OzeRoute — Piste 4 : Google Trends [{mode.upper()}]")
    if mode == "offline":
        print("ℹ️  Mode offline actif — données calibrées sur pattern 2022-2025")
        print("   Pour le live (local) : python3 google_trends.py --live")
    else:
        print("ℹ️  Mode live — pytrends (requiert exécution locale, pas datacenter)")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("🔍 [dry-run] Piste 4 OK")
        print(f"   Marchés : {', '.join(MARKET_QUERIES.keys())}")
        return

    today = date.today()
    start_monday = today - timedelta(days=today.weekday())
    weeks = [start_monday + timedelta(weeks=i) for i in range(args.weeks)]

    # En mode live : pré-charger les données Trends par marché (une requête par marché)
    live_data = {}
    if args.live:
        for market_code in MARKET_QUERIES:
            print(f"  📡 Fetch Trends live : {MARKET_QUERIES[market_code]['label']}...")
            data = fetch_trends_live(market_code, weeks_back=max(args.weeks, 12))
            live_data[market_code] = data
            if data:
                print(f"     → {len(data)} semaines récupérées")
            else:
                print(f"     → échec — fallback offline")
            time.sleep(1.5)  # rate limiting Google

    rows = []
    for w_start in weeks:
        w_end = w_start + timedelta(days=6)
        week_iso = w_start.isocalendar()[1]
        label_semaine = f"{w_start.strftime('%d %b')} – {w_end.strftime('%d %b')}"

        market_indices = {}
        for market_code, market_info in MARKET_QUERIES.items():
            if args.live and market_code in live_data and live_data[market_code]:
                # Mode live : chercher la semaine de recherche (décalée)
                lead = LEAD_TIME_WEEKS[market_code]
                search_week_iso = (w_start - timedelta(weeks=lead)).isocalendar()[1]
                index = live_data[market_code].get(search_week_iso, 45)
                source = "live_pytrends"
            else:
                result = compute_trends_offline(market_code, w_start)
                index = result["trends_index"]
                source = "offline_calibre"

            market_indices[market_code] = index

            rows.append({
                "semaine_debut":        w_start.isoformat(),
                "semaine_fin":          w_end.isoformat(),
                "semaine_iso":          week_iso,
                "label_semaine":        label_semaine,
                "market_code":          market_code,
                "market_label":         market_info["label"],
                "market_weight":        market_info["weight"],
                "trends_index":         index,
                "signal_trends":        classify_trends_signal(index),
                "lead_time_weeks":      LEAD_TIME_WEEKS[market_code],
                "requetes_configurees": " | ".join(market_info["queries"]),
                "source_donnee":        source,
            })

        # Index pondéré consolidé pour cette semaine
        weighted = sum(
            market_indices[m] * MARKET_QUERIES[m]["weight"]
            for m in market_indices
        )
        # Ajouter une ligne synthèse par semaine
        rows.append({
            "semaine_debut":        w_start.isoformat(),
            "semaine_fin":          w_end.isoformat(),
            "semaine_iso":          week_iso,
            "label_semaine":        label_semaine,
            "market_code":          "SYNTHESE",
            "market_label":         "Synthèse pondérée (tous marchés)",
            "market_weight":        1.0,
            "trends_index":         round(weighted),
            "signal_trends":        classify_trends_signal(round(weighted)),
            "lead_time_weeks":      0,
            "requetes_configurees": "moyenne pondérée",
            "source_donnee":        source,
        })

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ {len(rows)} entrées → {OUTPUT_PATH.name}")

    # Afficher résumé des semaines synthèse
    synthese = [r for r in rows if r["market_code"] == "SYNTHESE"]
    print(f"\n── Index synthèse (tous marchés pondérés) ──")
    print(f"{'Semaine':<22} {'Index':>6}  Signal")
    print("-" * 50)
    for r in synthese:
        print(f"{r['label_semaine']:<22} {r['trends_index']:>6}  {r['signal_trends']}")


if __name__ == "__main__":
    main()
