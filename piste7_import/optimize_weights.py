"""
OzeRoute — Optimisation automatique des poids des Pistes
=========================================================
Après import de données réelles, recalibre les pondérations P1-P6
pour minimiser le MAPE sur les semaines historiques connues.

Contraintes :
  - Σ wi = 1.0
  - 0.0 ≤ wi ≤ 0.65   (éviter la surconcentration sur 1 piste)
  - wi ≥ 0.02 pour les pistes actives (plancher minimal)

Méthode : SLSQP (scipy.optimize) avec fallback recherche aléatoire.
Minimum 6 semaines réelles requises pour une optimisation fiable.

Sorties :
  output/ozeroute_poids_optimises.json
"""

import csv
import json
import random
from pathlib import Path
from datetime import datetime

OUTPUT_DIR   = Path(__file__).parent.parent / "output"
WEIGHTS_FILE = OUTPUT_DIR / "ozeroute_poids_optimises.json"

MIN_SEMAINES = 6  # seuil minimum avant d'optimiser

# Poids par défaut (document de cadrage OzeRoute)
DEFAULT_TACTIQUE    = {"P1": 0.35, "P2": 0.20, "P3": 0.25, "P4": 0.15, "P6": 0.05}
DEFAULT_STRATEGIQUE = {"P1": 0.35, "P2": 0.40, "P3": 0.07, "P4": 0.03, "P5": 0.15}

# Bornes par piste [min, max]
BOUNDS_TACTIQUE    = {"P1": (0.10, 0.55), "P2": (0.05, 0.50),
                      "P3": (0.05, 0.50), "P4": (0.02, 0.40), "P6": (0.01, 0.20)}
BOUNDS_STRATEGIQUE = {"P1": (0.10, 0.55), "P2": (0.15, 0.65),
                      "P3": (0.01, 0.20), "P4": (0.01, 0.15), "P5": (0.05, 0.35)}


# ── Chargement des signaux semaine par semaine ─────────────────────────────

def _load_week_signals() -> dict:
    """
    Charge les signaux de toutes les Pistes, indexés par semaine_debut.
    Retourne : { "2026-07-20": {"P1": 0.70, "P2": 1.0, "P3": 0.95, ...}, ... }
    """
    signals: dict[str, dict] = {}

    def _ensure(sd):
        if sd not in signals:
            signals[sd] = {}

    # P2 — index de superposition calendriers
    p2 = OUTPUT_DIR / "ozeroute_overlap_index_semaine_2026.csv"
    if p2.exists():
        with open(p2, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sd = row["semaine_debut"].strip()
                _ensure(sd)
                try:
                    signals[sd]["P2"] = float(row.get("index_superposition", 0) or 0)
                except (ValueError, TypeError):
                    pass

    # P3 — taux d'occupation hôtelier (moyenne toutes zones)
    p3 = OUTPUT_DIR / "ozeroute_hotel_availability.csv"
    if p3.exists():
        buf: dict[str, list] = {}
        with open(p3, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sd = row["semaine_debut"].strip()
                try:
                    buf.setdefault(sd, []).append(float(row.get("taux_occupation_estime", 0) or 0))
                except (ValueError, TypeError):
                    pass
        for sd, vals in buf.items():
            _ensure(sd)
            signals[sd]["P3"] = sum(vals) / len(vals)

    # P4 — Google Trends synthèse (normalisé 0-1)
    p4 = OUTPUT_DIR / "ozeroute_google_trends.csv"
    if p4.exists():
        # Cherche la ligne SYNTHESE ; fallback : moyenne pondérée des marchés
        synth: dict[str, float] = {}
        by_week: dict[str, list] = {}
        with open(p4, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sd = row.get("semaine_debut", "").strip()
                code = row.get("market_code", "").strip()
                try:
                    idx = float(row.get("trends_index", 0) or 0) / 100.0
                    w   = float(row.get("market_weight", 1) or 1)
                    if code == "SYNTHESE":
                        synth[sd] = idx
                    else:
                        by_week.setdefault(sd, []).append((idx, w))
                except (ValueError, TypeError):
                    pass
        for sd in set(list(synth.keys()) + list(by_week.keys())):
            _ensure(sd)
            if sd in synth:
                signals[sd]["P4"] = synth[sd]
            elif sd in by_week:
                tot_w = sum(w for _, w in by_week[sd])
                if tot_w > 0:
                    signals[sd]["P4"] = sum(v * w for v, w in by_week[sd]) / tot_w

    # P5 — saisonnalité historique (normalisé 0-1)
    p5 = OUTPUT_DIR / "ozeroute_saisonnalite_historique.csv"
    if p5.exists():
        with open(p5, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sd = row.get("semaine_debut", "").strip()
                if not sd:
                    continue
                _ensure(sd)
                try:
                    signals[sd]["P5"] = float(row.get("saison_index", 0) or 0)
                except (ValueError, TypeError):
                    pass

    # P6 — météo (moyenne aéroports, normalisée [−0.15,+0.15] → [0,1])
    p6 = OUTPUT_DIR / "ozeroute_meteo_prevue.csv"
    if p6.exists():
        buf6: dict[str, list] = {}
        with open(p6, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sd = row.get("semaine_debut", "").strip()
                if not sd:
                    continue
                try:
                    buf6.setdefault(sd, []).append(float(row.get("meteo_impact", 0) or 0))
                except (ValueError, TypeError):
                    pass
        for sd, vals in buf6.items():
            _ensure(sd)
            avg = sum(vals) / len(vals)
            signals[sd]["P6"] = min(max((avg + 0.15) / 0.30, 0.0), 1.0)

    # P1 — score fixe : 0.70 si le CSV routes existe, sinon 0
    p1_score = 0.70 if (OUTPUT_DIR / "ozeroute_routes_piste1.csv").exists() else 0.0
    for sd in signals:
        signals[sd]["P1"] = p1_score

    return signals


def _load_actuals() -> dict:
    """Charge les commandes réelles → { semaine_debut: nb_courses }."""
    try:
        from .import_commandes import load_commandes
    except ImportError:
        from import_commandes import load_commandes
    return {r["semaine_debut"]: r["nb_courses"]
            for r in load_commandes() if r.get("nb_courses", 0) > 0}


# ── Fonction objectif ──────────────────────────────────────────────────────

def _mape_for_weights(w_vals: list, keys: list,
                      week_signals: dict, actuals: dict) -> float:
    """
    Calcule le MAPE pour un vecteur de poids donné.
    Recalcule le facteur de conversion à chaque évaluation.
    """
    pairs = []
    for sd, actual in actuals.items():
        sig = week_signals.get(sd)
        if sig is None:
            continue
        idx = sum(w_vals[i] * sig.get(keys[i], 0.0) for i in range(len(keys)))
        pairs.append((idx, actual))

    if not pairs:
        return 1.0

    # Facteur de conversion (médiane)
    facteurs = sorted(actual / idx for idx, actual in pairs if idx > 0.01)
    if not facteurs:
        return 1.0
    mid = len(facteurs) // 2
    fc = facteurs[mid] if len(facteurs) % 2 else (facteurs[mid - 1] + facteurs[mid]) / 2

    # MAPE
    errs = []
    for idx, actual in pairs:
        pred = idx * fc
        errs.append(abs(pred - actual) / actual)

    return sum(errs) / len(errs)


# ── Optimisation ───────────────────────────────────────────────────────────

def _optimize_scipy(keys: list, bounds_map: dict,
                    week_signals: dict, actuals: dict,
                    default_w: dict) -> tuple[list, float]:
    """Optimisation SLSQP via scipy.optimize."""
    from scipy.optimize import minimize
    import numpy as np

    w0 = [default_w[k] for k in keys]
    bnds = [bounds_map[k] for k in keys]

    constraints = [{"type": "eq", "fun": lambda w: sum(w) - 1.0}]

    def obj(w):
        return _mape_for_weights(list(w), keys, week_signals, actuals)

    res = minimize(obj, w0, method="SLSQP", bounds=bnds,
                   constraints=constraints,
                   options={"maxiter": 500, "ftol": 1e-6})

    w_opt = list(res.x)
    # Re-normalise pour garantir sum=1 après clipping numérique
    s = sum(w_opt)
    w_opt = [v / s for v in w_opt]
    return w_opt, float(res.fun)


def _clip_project(w: list, keys: list, bounds_map: dict) -> list:
    """Clip to bounds then re-normalise so sum=1."""
    w = [min(max(w[i], bounds_map[keys[i]][0]), bounds_map[keys[i]][1])
         for i in range(len(keys))]
    s = sum(w)
    return [v / s for v in w] if s > 0 else w


def _optimize_random(keys: list, bounds_map: dict,
                     week_signals: dict, actuals: dict,
                     default_w: dict) -> tuple[list, float]:
    """
    Nelder-Mead simplex sur le simplexe borné + phase d'exploration aléatoire.
    Aucune dépendance externe.
    """
    random.seed(0)
    n = len(keys)

    def obj(w):
        return _mape_for_weights(w, keys, week_signals, actuals)

    def rnd():
        w = [random.uniform(bounds_map[k][0], bounds_map[k][1]) for k in keys]
        return _clip_project(w, keys, bounds_map)

    # ── Phase 1 : recherche aléatoire globale (2 000 candidats) ──────
    best_w    = _clip_project([default_w[k] for k in keys], keys, bounds_map)
    best_mape = obj(best_w)

    pool = [rnd() for _ in range(2000)]
    pool.append(best_w)
    for w in pool:
        m = obj(w)
        if m < best_mape:
            best_mape, best_w = m, list(w)

    # ── Phase 2 : Nelder-Mead simplex ────────────────────────────────
    # Construire le simplexe initial autour du meilleur point
    simplex = [list(best_w)]
    for i in range(n):
        p = list(best_w)
        step = (bounds_map[keys[i]][1] - bounds_map[keys[i]][0]) * 0.15
        p[i] = min(max(p[i] + step, bounds_map[keys[i]][0]), bounds_map[keys[i]][1])
        simplex.append(_clip_project(p, keys, bounds_map))

    scores = [obj(w) for w in simplex]

    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5

    for _ in range(1500):
        # Tri
        order   = sorted(range(n + 1), key=lambda i: scores[i])
        simplex = [simplex[i] for i in order]
        scores  = [scores[i]  for i in order]

        if scores[0] < best_mape:
            best_mape, best_w = scores[0], list(simplex[0])

        # Centroïde (sans le pire)
        centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]

        # Réflexion
        worst = simplex[-1]
        refl  = _clip_project(
            [centroid[j] + alpha * (centroid[j] - worst[j]) for j in range(n)],
            keys, bounds_map)
        s_refl = obj(refl)

        if s_refl < scores[0]:
            # Expansion
            exp   = _clip_project(
                [centroid[j] + gamma * (refl[j] - centroid[j]) for j in range(n)],
                keys, bounds_map)
            s_exp = obj(exp)
            if s_exp < s_refl:
                simplex[-1], scores[-1] = exp, s_exp
            else:
                simplex[-1], scores[-1] = refl, s_refl
        elif s_refl < scores[-2]:
            simplex[-1], scores[-1] = refl, s_refl
        else:
            # Contraction
            cont   = _clip_project(
                [centroid[j] + rho * (worst[j] - centroid[j]) for j in range(n)],
                keys, bounds_map)
            s_cont = obj(cont)
            if s_cont < scores[-1]:
                simplex[-1], scores[-1] = cont, s_cont
            else:
                # Réduction
                best0 = simplex[0]
                simplex = [best0] + [
                    _clip_project(
                        [best0[j] + sigma * (simplex[i][j] - best0[j]) for j in range(n)],
                        keys, bounds_map)
                    for i in range(1, n + 1)
                ]
                scores = [obj(w) for w in simplex]

    # ── Phase 3 : hill-climbing fin autour du meilleur ───────────────
    cur_w, cur_mape = list(best_w), best_mape
    for step in [0.02, 0.01, 0.005]:
        for _ in range(400):
            i, j = random.sample(range(n), 2)
            delta = random.uniform(-step, step)
            new_w = list(cur_w)
            new_w[i] += delta
            new_w[j] -= delta
            new_w = _clip_project(new_w, keys, bounds_map)
            m = obj(new_w)
            if m < cur_mape:
                cur_mape, cur_w = m, new_w
                if m < best_mape:
                    best_mape, best_w = m, list(cur_w)

    return best_w, best_mape


def _run_for_horizon(keys: list, bounds_map: dict, default_w: dict,
                     week_signals: dict, actuals: dict) -> tuple[dict, float, str]:
    """Lance l'optimisation pour un horizon (tactique ou stratégique)."""
    mape_before = _mape_for_weights(
        [default_w[k] for k in keys], keys, week_signals, actuals)

    method = "random_search"
    try:
        w_opt, mape_after = _optimize_scipy(keys, bounds_map, week_signals, actuals, default_w)
        method = "SLSQP"
    except Exception:
        w_opt, mape_after = _optimize_random(keys, bounds_map, week_signals, actuals, default_w)

    weights_opt = {k: round(w_opt[i], 4) for i, k in enumerate(keys)}

    # Sécurité : si l'optimisation dégrade le MAPE, on garde les défauts
    if mape_after >= mape_before:
        return default_w, mape_before, method + " (défauts conservés)"

    return weights_opt, mape_after, method


# ── API publique ───────────────────────────────────────────────────────────

def run_optimization() -> dict:
    """
    Point d'entrée principal.
    Charge signaux + commandes, optimise les 2 horizons, sauvegarde le JSON.
    Retourne le résultat complet (dict).
    """
    week_signals = _load_week_signals()
    actuals      = _load_actuals()

    result: dict = {
        "nb_semaines_reelles": len(actuals),
        "derniere_optimisation": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "statut": "insuffisant",
        "message": f"Données insuffisantes — {len(actuals)}/{MIN_SEMAINES} semaines requises",
    }

    if len(actuals) < MIN_SEMAINES:
        WEIGHTS_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        return result

    # ── Horizon tactique (P1, P2, P3, P4, P6) ──────────────────────
    tact_keys = ["P1", "P2", "P3", "P4", "P6"]
    w_tact, mape_t_after, method_t = _run_for_horizon(
        tact_keys, BOUNDS_TACTIQUE, DEFAULT_TACTIQUE, week_signals, actuals)
    mape_t_before = round(_mape_for_weights(
        [DEFAULT_TACTIQUE[k] for k in tact_keys], tact_keys, week_signals, actuals) * 100, 1)
    mape_t_after_pct = round(mape_t_after * 100, 1)

    # ── Horizon stratégique (P1, P2, P3, P4, P5) ──────────────────
    strat_keys = ["P1", "P2", "P3", "P4", "P5"]
    w_strat, mape_s_after, method_s = _run_for_horizon(
        strat_keys, BOUNDS_STRATEGIQUE, DEFAULT_STRATEGIQUE, week_signals, actuals)
    mape_s_before = round(_mape_for_weights(
        [DEFAULT_STRATEGIQUE[k] for k in strat_keys], strat_keys, week_signals, actuals) * 100, 1)
    mape_s_after_pct = round(mape_s_after * 100, 1)

    result.update({
        "statut": "calibre",
        "message": f"Optimisé sur {len(actuals)} semaines",
        "tactique": {k: round(w_tact.get(k, DEFAULT_TACTIQUE[k]), 4) for k in tact_keys},
        "tactique_defaut": DEFAULT_TACTIQUE,
        "mape_tactique_avant": mape_t_before,
        "mape_tactique_apres": mape_t_after_pct,
        "gain_tactique_pts": round(mape_t_before - mape_t_after_pct, 1),
        "methode_tactique": method_t,
        "strategique": {k: round(w_strat.get(k, DEFAULT_STRATEGIQUE[k]), 4) for k in strat_keys},
        "strategique_defaut": DEFAULT_STRATEGIQUE,
        "mape_strategique_avant": mape_s_before,
        "mape_strategique_apres": mape_s_after_pct,
        "gain_strategique_pts": round(mape_s_before - mape_s_after_pct, 1),
        "methode_strategique": method_s,
    })

    OUTPUT_DIR.mkdir(exist_ok=True)
    WEIGHTS_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def load_optimized_weights() -> dict:
    """Charge le JSON de poids optimisés. Retourne {} si absent ou insuffisant."""
    if not WEIGHTS_FILE.exists():
        return {}
    try:
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        if data.get("statut") != "calibre":
            return {}
        return data
    except Exception:
        return {}


def reset_to_defaults() -> None:
    """Supprime le fichier de poids optimisés (retour aux défauts)."""
    if WEIGHTS_FILE.exists():
        WEIGHTS_FILE.unlink()


if __name__ == "__main__":
    print("\n" + "=" * 58)
    print("  OzeRoute — Optimisation des poids des Pistes")
    print("=" * 58)
    res = run_optimization()
    print(f"  Statut     : {res['statut']}")
    print(f"  Semaines   : {res['nb_semaines_reelles']}")
    if res.get("tactique"):
        print(f"  [Tactique]  MAPE {res['mape_tactique_avant']}% → {res['mape_tactique_apres']}%"
              f"  (−{res['gain_tactique_pts']} pts)  via {res['methode_tactique']}")
        print(f"  Poids : {res['tactique']}")
    if res.get("strategique"):
        print(f"  [Stratégique] MAPE {res['mape_strategique_avant']}% → {res['mape_strategique_apres']}%"
              f"  (−{res['gain_strategique_pts']} pts)  via {res['methode_strategique']}")
        print(f"  Poids : {res['strategique']}")
    print()
