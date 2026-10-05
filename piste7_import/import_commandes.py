"""
OzeRoute — Piste 7 : Import Données Réelles & Calibration
==========================================================
Importe les commandes réelles hebdomadaires OzeRoute, les croise avec
l'indice prédit (signal_combine) et calcule les métriques de calibration
pour valider le modèle en mode shadow.

Format CSV attendu (colonnes minimales obligatoires) :
  semaine_debut, nb_courses
  [+ optionnels : semaine_fin, segment, aeroport, marche_source, nb_passagers, notes]

Usage CLI :
  python3 import_commandes.py --file mon_export.csv   # importer un fichier
  python3 import_commandes.py --demo                  # données de démo
  python3 import_commandes.py --template              # générer un template vide
  python3 import_commandes.py --calibrate             # recalculer la calibration seule
"""

import argparse
import csv
import json
import math
import random
from datetime import datetime
from pathlib import Path

OUTPUT_DIR   = Path(__file__).parent.parent / "output"
IMPORT_FILE  = OUTPUT_DIR / "ozeroute_commandes_reelles.csv"
SIGNAL_FILE  = OUTPUT_DIR / "ozeroute_signal_combine.csv"
CALIB_FILE   = OUTPUT_DIR / "ozeroute_calibration.json"
TEMPLATE_FILE = OUTPUT_DIR / "template_import_commandes.csv"

FIELDNAMES = [
    "semaine_debut", "semaine_fin", "nb_courses",
    "segment", "aeroport", "marche_source", "nb_passagers", "notes",
]


# ── Validation ─────────────────────────────────────────────────────────────

def _validate_row(row: dict, line_num: int) -> list[str]:
    errors = []
    sd = row.get("semaine_debut", "").strip()
    if not sd:
        errors.append(f"Ligne {line_num} : semaine_debut manquante")
    else:
        try:
            datetime.strptime(sd, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Ligne {line_num} : semaine_debut format invalide — attendu YYYY-MM-DD, reçu «{sd}»")

    nc = row.get("nb_courses", "").strip()
    if not nc:
        errors.append(f"Ligne {line_num} : nb_courses manquant")
    else:
        try:
            v = float(nc)
            if v < 0:
                errors.append(f"Ligne {line_num} : nb_courses ne peut pas être négatif")
        except ValueError:
            errors.append(f"Ligne {line_num} : nb_courses doit être un nombre, reçu «{nc}»")

    return errors


# ── Loaders ────────────────────────────────────────────────────────────────

def load_signal() -> dict:
    """Charge le signal consolidé → dict keyed by semaine_debut."""
    if not SIGNAL_FILE.exists():
        return {}
    signal = {}
    with open(SIGNAL_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sd = row.get("semaine_debut", "").strip()
            try:
                signal[sd] = {
                    "semaine_debut":   sd,
                    "semaine_fin":     row.get("semaine_fin", "").strip(),
                    "signal_consolide": float(row.get("signal_consolide", 0) or 0),
                    "intensite":       row.get("intensite", "").strip(),
                }
            except (ValueError, TypeError):
                pass
    return signal


def load_commandes() -> list[dict]:
    """Charge les commandes réelles importées."""
    if not IMPORT_FILE.exists():
        return []
    rows = []
    with open(IMPORT_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "semaine_debut":  row.get("semaine_debut", "").strip(),
                    "semaine_fin":    row.get("semaine_fin", "").strip(),
                    "nb_courses":     float(row.get("nb_courses") or 0),
                    "segment":        row.get("segment", "").strip(),
                    "aeroport":       row.get("aeroport", "").strip(),
                    "marche_source":  row.get("marche_source", "").strip(),
                    "nb_passagers":   float(row["nb_passagers"]) if row.get("nb_passagers") else None,
                    "notes":          row.get("notes", "").strip(),
                })
            except (ValueError, TypeError):
                pass
    return rows


def load_calibration() -> dict:
    """Charge les métriques de calibration calculées."""
    if not CALIB_FILE.exists():
        return {}
    with open(CALIB_FILE, encoding="utf-8") as f:
        return json.load(f)


# ── Calibration ────────────────────────────────────────────────────────────

def compute_calibration(commandes: list[dict], signal: dict) -> dict:
    """
    Croise commandes réelles × signal prédit et calcule :
      - facteur_conversion  (courses / indice-unit)
      - MAPE                (Mean Absolute Percentage Error)
      - MAE                 (Mean Absolute Error en courses)
      - R²                  (coefficient de détermination)

    Retourne aussi la table croisée enrichie (champ 'table').
    """
    table = []
    for cmd in commandes:
        sd  = cmd["semaine_debut"]
        sig = signal.get(sd)
        table.append({
            "semaine_debut":    sd,
            "semaine_fin":      cmd.get("semaine_fin") or (sig["semaine_fin"] if sig else ""),
            "nb_courses":       cmd["nb_courses"],
            "signal_consolide": sig["signal_consolide"] if sig else None,
            "intensite":        sig["intensite"]        if sig else "—",
            "segment":          cmd.get("segment", ""),
            "aeroport":         cmd.get("aeroport", ""),
            "marche_source":    cmd.get("marche_source", ""),
            "nb_passagers":     cmd.get("nb_passagers"),
            "notes":            cmd.get("notes", ""),
        })

    # Seulement les semaines avec signal ET commandes non nulles
    valid = [r for r in table if r["signal_consolide"] is not None and r["nb_courses"] > 0]

    metrics: dict = {
        "facteur_conversion": None,
        "mape":  None,
        "mae":   None,
        "r2":    None,
        "nb_semaines_calibrees": len(valid),
        "nb_semaines_total":     len(table),
        "derniere_mise_a_jour":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "table": table,
    }

    if not valid:
        return metrics

    # Facteur de conversion = médiane(courses / signal)  [signal in 0-1]
    facteurs = []
    for r in valid:
        idx = r["signal_consolide"]
        if idx > 0.01:
            facteurs.append(r["nb_courses"] / idx)
    if not facteurs:
        return metrics

    facteurs.sort()
    mid = len(facteurs) // 2
    facteur = facteurs[mid] if len(facteurs) % 2 else (facteurs[mid-1] + facteurs[mid]) / 2
    metrics["facteur_conversion"] = round(facteur, 1)

    # Prédictions et erreurs
    errs_abs = []
    errs_pct = []
    for r in valid:
        pred = r["signal_consolide"] * facteur
        actual = r["nb_courses"]
        err_abs = abs(pred - actual)
        errs_abs.append(err_abs)
        errs_pct.append(err_abs / actual * 100)
        r["courses_predites"] = round(pred, 1)
        r["erreur_absolue"]   = round(err_abs, 1)
        r["erreur_pct"]       = round(err_abs / actual * 100, 1)
        r["ecart_signe"]      = round(pred - actual, 1)

    metrics["mape"] = round(sum(errs_pct) / len(errs_pct), 1)
    metrics["mae"]  = round(sum(errs_abs) / len(errs_abs), 1)

    # R²
    if len(valid) >= 2:
        actuals    = [r["nb_courses"] for r in valid]
        mean_a     = sum(actuals) / len(actuals)
        ss_tot     = sum((a - mean_a) ** 2 for a in actuals)
        ss_res     = sum((r["nb_courses"] - r.get("courses_predites", 0)) ** 2 for r in valid)
        metrics["r2"] = round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else None

    return metrics


def save_calibration(metrics: dict) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    payload = {k: v for k, v in metrics.items() if k != "table"}
    with open(CALIB_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Import ─────────────────────────────────────────────────────────────────

def import_from_path(csv_path: str | Path) -> tuple[bool, list[str]]:
    """
    Importe un CSV, valide, fusionne avec l'existant, recalcule la calibration.
    Retourne (succès, liste_erreurs).
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return False, [f"Fichier introuvable : {csv_path}"]

    new_rows = []
    errors   = []

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return False, ["Fichier CSV vide ou sans en-têtes"]
        for i, row in enumerate(reader, start=2):
            row_errors = _validate_row(row, i)
            if row_errors:
                errors.extend(row_errors)
            else:
                new_rows.append({
                    "semaine_debut":  row["semaine_debut"].strip(),
                    "semaine_fin":    row.get("semaine_fin", "").strip(),
                    "nb_courses":     float(row["nb_courses"]),
                    "segment":        row.get("segment", "").strip(),
                    "aeroport":       row.get("aeroport", "").strip(),
                    "marche_source":  row.get("marche_source", "").strip(),
                    "nb_passagers":   float(row["nb_passagers"]) if row.get("nb_passagers") else None,
                    "notes":          row.get("notes", "").strip(),
                })

    if not new_rows:
        return False, errors or ["Aucune ligne valide dans le fichier"]

    # Merge with existing (new rows override by semaine_debut)
    existing = {r["semaine_debut"]: r for r in load_commandes()}
    for r in new_rows:
        existing[r["semaine_debut"]] = r

    merged = sorted(existing.values(), key=lambda r: r["semaine_debut"])

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(IMPORT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for r in merged:
            writer.writerow(r)

    # Recompute calibration
    signal  = load_signal()
    metrics = compute_calibration(merged, signal)
    save_calibration(metrics)

    # Auto-optimize piste weights if enough data
    if len(merged) >= 6:
        try:
            try:
                from .optimize_weights import run_optimization
            except ImportError:
                from optimize_weights import run_optimization
            run_optimization()
        except Exception:
            pass

    return True, errors


def import_from_bytes(content: bytes, filename: str = "upload.csv") -> tuple[bool, list[str]]:
    """Import depuis des bytes (upload Streamlit)."""
    tmp = OUTPUT_DIR / f"_tmp_{filename}"
    OUTPUT_DIR.mkdir(exist_ok=True)
    tmp.write_bytes(content)
    ok, errors = import_from_path(tmp)
    tmp.unlink(missing_ok=True)
    return ok, errors


# ── Demo & Template ────────────────────────────────────────────────────────

def generate_demo() -> bool:
    """Génère des données de démonstration basées sur le signal prédit (+bruit réaliste)."""
    signal = load_signal()
    if not signal:
        print("  ❌ Signal non disponible — lancez d'abord le pipeline principal")
        return False

    random.seed(42)
    rows = []
    for sd, sig in sorted(signal.items()):
        idx = sig["signal_consolide"]
        # ~120 courses au pic (index=1.0), bruit ±15 %, plus forte variance en basse saison
        base  = 120.0 * idx
        noise = base * random.gauss(0, 0.12)
        nb    = max(0, round(base + noise))
        rows.append({
            "semaine_debut":  sd,
            "semaine_fin":    sig["semaine_fin"],
            "nb_courses":     nb,
            "segment":        "navette",
            "aeroport":       "CDG+ORY",
            "marche_source":  "",
            "nb_passagers":   round(nb * 2.3) if nb else 0,
            "notes":          "DEMO",
        })

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(IMPORT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    metrics = compute_calibration(rows, signal)
    save_calibration(metrics)

    print(f"  ✅ {len(rows)} semaines de démonstration → {IMPORT_FILE.name}")
    print(f"  📊 MAPE={metrics.get('mape')}%  |  Facteur={metrics.get('facteur_conversion')}  |  R²={metrics.get('r2')}")

    # Auto-optimize weights
    try:
        try:
            from .optimize_weights import run_optimization
        except ImportError:
            from optimize_weights import run_optimization
        run_optimization()
    except Exception:
        pass

    return True


def generate_template() -> Path:
    """Génère un template CSV pré-rempli avec les semaines du signal."""
    signal = load_signal()
    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(TEMPLATE_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDNAMES)
        for sd, sig in sorted(signal.items()):
            writer.writerow([sd, sig["semaine_fin"], "", "navette", "CDG+ORY", "", "", ""])

    print(f"  ✅ Template → {TEMPLATE_FILE.name}  ({len(signal)} semaines)")
    return TEMPLATE_FILE


def recalibrate() -> dict:
    """Recalcule la calibration à partir des données existantes."""
    commandes = load_commandes()
    signal    = load_signal()
    metrics   = compute_calibration(commandes, signal)
    save_calibration(metrics)
    return metrics


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OzeRoute — Import Données Réelles (Piste 7)")
    parser.add_argument("--file",      help="CSV de commandes réelles à importer")
    parser.add_argument("--demo",      action="store_true", help="Générer des données de démonstration")
    parser.add_argument("--template",  action="store_true", help="Générer un template CSV vide")
    parser.add_argument("--calibrate", action="store_true", help="Recalculer la calibration seule")
    args = parser.parse_args()

    print("\n" + "="*58)
    print("  OzeRoute — Import Données Réelles (Piste 7)")
    print("="*58)

    if args.template:
        generate_template()
    elif args.demo:
        generate_demo()
    elif args.calibrate:
        m = recalibrate()
        if m.get("nb_semaines_calibrees"):
            print(f"  📊 MAPE={m.get('mape')}%  |  Facteur={m.get('facteur_conversion')}  |  R²={m.get('r2')}")
        else:
            print("  ⚠️  Pas de données — importez d'abord avec --file ou --demo")
    elif args.file:
        ok, errors = import_from_path(args.file)
        for e in errors:
            print(f"  ⚠️  {e}")
        if ok:
            m = load_calibration()
            print(f"  📊 MAPE={m.get('mape')}%  |  Facteur={m.get('facteur_conversion')}  |  R²={m.get('r2')}")
    else:
        parser.print_help()

    print()


if __name__ == "__main__":
    main()
