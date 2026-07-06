# OzeRoute — Système de Prédiction de Demande

Système modulaire de prévision de la demande transport aéroportuaire.
Chaque piste est un module indépendant. On branche les pistes au fur et à mesure.

## Architecture

```
ozeroute_demand/
│
├── main.py                          ← orchestrateur principal
│
├── piste1_vols/
│   └── piste1_routes.py             ✅ livré — nécessite AIRLABS_API_KEY
│
├── piste2_calendriers/
│   ├── calendar_data.py             ✅ livré — données scolaires vérifiées
│   └── overlap_index.py             ✅ livré — index superposition pondéré
│
├── piste3_hotels/
│   └── hotel_availability.py        ⏳ à venir
│
├── piste4_trends/
│   └── google_trends.py             ⏳ à venir
│
└── output/                          ← tous les CSV sont écrits ici
    ├── ozeroute_overlap_index_semaine_2026.csv   (Piste 2)
    ├── ozeroute_routes_piste1.csv                (Piste 1 — après clé API)
    └── ozeroute_signal_combine.csv               (signal fusionné)
```

## Pistes

| # | Piste | Statut | Clé requise | Signal |
|---|---|---|---|---|
| 1 | Programmes de vols (AirLabs) | ✅ Livré | AIRLABS_API_KEY | Quotidien/horaire |
| 2 | Calendriers scolaires 4 marchés | ✅ Livré | Aucune | Hebdomadaire |
| 3 | Disponibilité hôtelière | ⏳ À venir | Aucune | Hebdomadaire |
| 4 | Google Trends | ⏳ À venir | Aucune | Hebdomadaire |
| — | Uber/Bolt surge pricing | 🅿️ Parké | — | Diagnostic seulement |

## Setup

### Prérequis
```bash
pip install requests pandas --break-system-packages
```

### Lancer toutes les pistes actives
```bash
python3 main.py
```

### Lancer une piste spécifique
```bash
python3 main.py --piste 2
```

### Vérifier la config sans appeler les APIs
```bash
python3 main.py --dry-run
```

### Piste 1 — avec clé AirLabs
```bash
# 1. Créer compte gratuit : https://airlabs.co/signup
# 2. Récupérer la clé : https://airlabs.co/account
AIRLABS_API_KEY=ta_cle_ici python3 main.py --piste 1
```

## Marchés sources et pondérations

| Marché | Poids | Zones internes |
|---|---|---|
| France | 0.40 | Toutes zones (été unifié) |
| UK | 0.22 | England/Wales (0.85) + Écosse (0.15) |
| Italie | 0.20 | Nord/Centre-Sud/Nord-Est |
| Espagne | 0.18 | Madrid/Catalogne/Baléares |

> ⚠️ Ces poids sont des estimations de départ. À calibrer avec les données
> internes OzeRoute (conversion par marché source) dès disponibilité.

## Lecture de l'output principal (Piste 2)

`output/ozeroute_overlap_index_semaine_2026.csv` — 18 semaines juin → sept 2026

| Index | Intensité | Lecture |
|---|---|---|
| ≥ 0.85 | Pic | 4 marchés pleinement alignés |
| ≥ 0.60 | Fort | 3 marchés alignés |
| ≥ 0.35 | Modéré | 2 marchés alignés |
| > 0 | Faible | 1 marché actif |
| 0 | Hors saison | Aucun marché en vacances |

> Signal de POSSIBILITÉ, pas de décision. Combine avec Piste 1 pour obtenir
> la granularité quotidienne/horaire qui confirme la demande réelle.

## Sources vérifiées

- France : education.gouv.fr
- Italie : calendarglobe.com (par région)
- Espagne : calendarglobe.com, idealista.com
- UK : ukcalculator.com (agrégation council-level)
- Vols : airlabs.co Routes Database
