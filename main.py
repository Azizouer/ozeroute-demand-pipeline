"""
OzeRoute — Pipeline Prédiction Demande
=======================================
Orchestrateur principal. Lance les pistes complétées et combine leurs signaux.

Usage :
  python3 main.py                    # lance toutes les pistes actives
  python3 main.py --piste 2          # lance une piste spécifique
  python3 main.py --dry-run          # vérifie la config sans appeler les APIs

Pistes :
  Piste 1 — Programmes de vols (AirLabs)       [nécessite AIRLABS_API_KEY]
  Piste 2 — Calendriers scolaires 4 marchés    [gratuit, aucune clé]
  Piste 3 — Disponibilité hôtelière            [à venir]
  Piste 4 — Google Trends                      [à venir]
"""

import os
import sys
import argparse
import importlib.util
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

PISTES = {
    1: {
        "label": "Programmes de vols (AirLabs Routes DB)",
        "module": "piste1_vols/piste1_routes.py",
        "status": "active",        # active | pending | parked
        "requires_key": "AIRLABS_API_KEY",
        "output": "ozeroute_routes_piste1.csv",
    },
    2: {
        "label": "Calendriers scolaires 4 marchés",
        "module": "piste2_calendriers/overlap_index.py",
        "status": "active",
        "requires_key": None,
        "output": "ozeroute_overlap_index_semaine_2026.csv",
    },
    3: {
        "label": "Disponibilité hôtelière (proxy indirect)",
        "module": "piste3_hotels/hotel_availability.py",
        "status": "active",
        "requires_key": None,
        "output": "ozeroute_hotel_availability.csv",
    },
    4: {
        "label": "Google Trends (affinage)",
        "module": "piste4_trends/google_trends.py",
        "status": "active",
        "requires_key": None,
        "output": "ozeroute_google_trends.csv",
    },
}


# ── Helpers ────────────────────────────────────────────────────

def print_banner():
    print("\n" + "="*60)
    print("  OzeRoute — Pipeline Prédiction Demande")
    print(f"  Exécution : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)


def print_status():
    print("\n┌─ État des Pistes ──────────────────────────────────────")
    for num, p in PISTES.items():
        icon = {"active": "✅", "pending": "⏳", "parked": "🅿️"}.get(p["status"], "?")
        key_info = ""
        if p["requires_key"]:
            has_key = bool(os.environ.get(p["requires_key"]))
            key_info = f"  [clé: {'✓' if has_key else '✗ ' + p['requires_key']}]"
        print(f"│  Piste {num} {icon}  {p['label']}{key_info}")
    print("└───────────────────────────────────────────────────────\n")


def load_module(path_rel: str):
    """Charge dynamiquement un module Python depuis son chemin relatif au projet."""
    root = Path(__file__).parent
    full_path = root / path_rel
    if not full_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("piste_module", full_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_output_exists(output_file: str) -> bool:
    return (OUTPUT_DIR / output_file).exists()


# ── Runners ────────────────────────────────────────────────────

def run_piste(num: int, dry_run: bool = False) -> bool:
    """
    Lance une piste. Retourne True si succès ou déjà disponible.
    """
    p = PISTES[num]

    if p["status"] == "pending":
        print(f"  ⏳ Piste {num} non encore implémentée — skipping")
        return False

    if p["status"] == "parked":
        print(f"  🅿️  Piste {num} parkée — skipping")
        return False

    if p["requires_key"]:
        key_val = os.environ.get(p["requires_key"])
        if not key_val:
            print(f"  ⚠️  Piste {num} : clé manquante ({p['requires_key']}) — skipping")
            return False

    if dry_run:
        print(f"  🔍 [dry-run] Piste {num} : {p['label']} — OK (module présent)")
        return True

    print(f"\n▶ Lancement Piste {num} : {p['label']}")
    mod = load_module(p["module"])
    if mod is None:
        print(f"  ❌ Module introuvable : {p['module']}")
        return False

    try:
        mod.main()
        print(f"  ✅ Piste {num} terminée → {p['output']}")
        return True
    except Exception as e:
        print(f"  ❌ Piste {num} erreur : {e}")
        return False


def run_combiner():
    """
    Combine les sorties des pistes actives en un signal consolidé.
    Actuellement : Piste 2 seule (Piste 1 viendra compléter dès que le CSV est disponible).
    """
    print("\n▶ Combinaison des signaux...")

    p2_output = OUTPUT_DIR / "ozeroute_overlap_index_semaine_2026.csv"
    p1_output = OUTPUT_DIR / "ozeroute_routes_piste1.csv"

    if not p2_output.exists():
        print("  ⚠️  Signal Piste 2 absent — combinaison impossible")
        return

    import csv

    # Lire index Piste 2
    with open(p2_output, encoding="utf-8") as f:
        p2_rows = list(csv.DictReader(f))

    # Si Piste 1 disponible, enrichir (placeholder pour la logique de croisement)
    p1_available = p1_output.exists()
    if p1_available:
        print("  📡 Piste 1 disponible — croisement routes × calendrier activé")
        # TODO: logique de croisement quand Piste 1 CSV est produit
    else:
        print("  📡 Piste 1 non disponible — signal calendrier seul")

    # Écriture signal consolidé
    combined_path = OUTPUT_DIR / "ozeroute_signal_combine.csv"
    with open(combined_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(p2_rows[0].keys()) + ["piste1_disponible", "signal_consolide"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in p2_rows:
            row["piste1_disponible"] = "oui" if p1_available else "non"
            # Signal consolidé = index Piste 2 pour l'instant
            # Sera enrichi quand Piste 1 + 3 + 4 seront branchées
            row["signal_consolide"] = row["index_superposition"]
            writer.writerow(row)

    print(f"  ✅ Signal consolidé → {combined_path.name}")


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OzeRoute Demand Pipeline")
    parser.add_argument("--piste", type=int, choices=PISTES.keys(),
                        help="Lancer une piste spécifique uniquement")
    parser.add_argument("--dry-run", action="store_true",
                        help="Vérifier la config sans appeler les APIs")
    args = parser.parse_args()

    print_banner()
    print_status()

    if args.piste:
        run_piste(args.piste, dry_run=args.dry_run)
    else:
        results = {}
        for num in PISTES:
            results[num] = run_piste(num, dry_run=args.dry_run)

        if not args.dry_run:
            run_combiner()

    print("\n" + "="*60)
    print("  Pipeline terminé")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
