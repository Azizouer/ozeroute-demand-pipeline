# OzeRoute v2 — Architecture & Guide d'utilisation

---

## Vue d'ensemble

OzeRoute est un **pipeline de prédiction de demande transport aéroportuaire** pour les aéroports parisiens (CDG, Orly, Beauvais). Il agrège 4 sources de signal indépendantes — les **Pistes** — pour estimer la demande entrante depuis 4 marchés européens 2 à 8 semaines à l'avance, puis expose les résultats dans un dashboard interactif.

**Marchés sources surveillés :**

| Marché | Poids | Rôle |
|--------|-------|------|
| France | 40 % | Marché domestique, plus gros volume |
| UK     | 22 % | Fort flux touristique vers Paris |
| Italie | 20 % | Deuxième marché européen entrant |
| Espagne| 18 % | Troisième marché européen entrant |

---

## Structure du projet

```
ozeroute_v2/
│
├── main.py                          ← Orchestrateur CLI — point d'entrée
├── dashboard.py                     ← Dashboard Streamlit interactif
├── ARCHITECTURE.md                  ← Ce document
│
├── piste1_vols/
│   └── piste1_routes.py             ✅ Routes aériennes via AirLabs API
│
├── piste2_calendriers/
│   ├── calendar_data.py             ✅ Données calendriers scolaires (statique)
│   └── overlap_index.py             ✅ Calcul index de superposition pondéré
│
├── piste3_hotels/
│   └── hotel_availability.py        ✅ Disponibilité hôtelière (live + calibré)
│
├── piste4_trends/
│   └── google_trends.py             ✅ Google Trends par marché (offline + live)
│
└── output/                          ← Tous les CSV produits par le pipeline
    ├── ozeroute_routes_piste1.csv
    ├── ozeroute_overlap_index_semaine_2026.csv
    ├── ozeroute_hotel_availability.csv
    ├── ozeroute_google_trends.csv
    └── ozeroute_signal_combine.csv
```

---

## Clés API nécessaires

| Clé | Piste | Obtention | Obligatoire |
|-----|-------|-----------|-------------|
| `AIRLABS_API_KEY` | Piste 1 — Vols | [airlabs.co/signup](https://airlabs.co/signup) — gratuit | Non (Piste 1 skippée si absente) |
| `RAPIDAPI_KEY` | Piste 3 — Hôtels live | [rapidapi.com](https://rapidapi.com) — abonnement Booking.com | Non (fallback calibré si absente) |

Sans aucune clé, le pipeline tourne quand même : Piste 2 (calendriers) et Piste 4 (Trends offline) fonctionnent sans clé.

---

## Comment utiliser — CLI

### 1. Installer les dépendances

```bash
pip install requests pandas streamlit plotly --break-system-packages
```

### 2. Lancer tout le pipeline

```bash
cd ozeroute_v2
python3 main.py
```

### 3. Lancer avec les clés API (recommandé)

```bash
AIRLABS_API_KEY=ta_cle_airlabs \
RAPIDAPI_KEY=ta_cle_rapidapi \
python3 main.py
```

### 4. Lancer une piste spécifique

```bash
python3 main.py --piste 2          # Piste 2 uniquement
python3 main.py --piste 3          # Piste 3 uniquement
```

### 5. Vérifier la config sans appeler les APIs

```bash
python3 main.py --dry-run
```

---

## Comment utiliser — Dashboard

### Lancer le dashboard

```bash
cd ozeroute_v2
~/.local/bin/streamlit run dashboard.py --server.port 8502
```

Ouvrir dans le navigateur : **http://localhost:8502**

### Panneau gauche (Sidebar)

| Élément | Description |
|---------|-------------|
| **Clé AirLabs** | Saisir la clé pour activer Piste 1 lors du run depuis l'UI |
| **▶ Lancer** | Relance le pipeline complet et rafraîchit les données automatiquement |
| **Log** | Affiche la sortie complète du pipeline après exécution |
| **Période** | Filtre les semaines affichées dans tous les onglets |
| **Intensité (P2)** | Filtre par niveau de demande calendaire (Pic / Fort / Modéré / Faible / Hors saison) |
| **Aéroport** | Filtre les routes Piste 1 par aéroport cible (CDG / ORY / BVA) |
| **Zone hôtelière (P3)** | Filtre les données hôtelières par zone géographique |
| **Statut Pistes** | Indicateur vert/orange selon disponibilité des données |

### Onglets du dashboard

#### 📅 P2 — Calendriers
- Graphique barres : index de superposition hebdomadaire coloré par intensité
- Heatmap : marchés actifs (ES / FR / IT / UK) par semaine
- Détail semaine par semaine : marchés, intensité, zones géographiques actives

#### 🛫 P1 — Routes
- Graphique : nombre de routes par marché source
- Camembert : distribution par aéroport cible
- Graphique groupé : Low-cost vs Réseau par aéroport
- Tableau filtrable de toutes les routes avec départ, compagnie, horaire

#### 🏨 P3 — Hôtels
- Heatmap : taux d'occupation estimé par zone × semaine (vert → jaune → rouge)
- Barres empilées : distribution du signal de rareté par zone
- Tableau événements à fort impact (14 juillet, SIAL, Toussaint…)
- Recommandations opérationnelles semaine par semaine pour Paris Centre

#### 📈 P4 — Trends
- Courbes Google Trends par marché source + synthèse pondérée
- Lead time appliqué par marché (France -2 sem, UK -4 sem, IT/ES -3 sem)
- Tableau synthèse hebdomadaire avec signal (Très fort / Fort / Modéré…)

#### 📋 Données brutes
- Tables complètes pour chaque piste
- Boutons de téléchargement CSV pour chaque dataset

---

## Flux de données

```
  AIRLABS_API_KEY          (statique)           RAPIDAPI_KEY         (offline)
       │                       │                      │                   │
       ▼                       ▼                      ▼                   ▼
  ┌─────────┐           ┌──────────┐           ┌──────────┐        ┌──────────┐
  │ Piste 1 │           │ Piste 2  │           │ Piste 3  │        │ Piste 4  │
  │  Vols   │           │Calendrier│           │  Hôtels  │        │  Trends  │
  └────┬────┘           └────┬─────┘           └────┬─────┘        └────┬─────┘
       │                     │                      │                   │
       ▼                     ▼                      ▼                   ▼
  routes_p1.csv    overlap_index.csv     hotel_availability.csv  google_trends.csv
       │                     │
       └──────────┬──────────┘
                  ▼
           run_combiner()
                  │
                  ▼
         signal_combine.csv
                  │
                  ▼
            dashboard.py
         (Streamlit :8502)
```

---

## Détail des Pistes

### Piste 1 — Programmes de vols

**Fichier :** `piste1_vols/piste1_routes.py`  
**API :** AirLabs Routes Database (`/airports` + `/routes`)  
**Signal :** Structure hebdomadaire de référence (routes récurrentes, pas temps réel)

Étapes internes :
1. Charge le mapping `aéroport IATA → pays` pour IT, GB, ES, FR
2. Pagine l'endpoint `/routes` pour CDG, ORY, BVA (50 résultats/page)
3. Filtre les routes dont le départ est dans un pays marché source
4. Enrichit chaque route : marché source, type transporteur (low-cost / réseau), jours d'opération

**Sortie CSV :** `dep_iata`, `source_market`, `carrier_type`, `arr_iata`, `target_airport`, `airline_iata`, `flight_iata`, `dep_time`, `jours_operation`

---

### Piste 2 — Calendriers scolaires

**Fichiers :** `piste2_calendriers/calendar_data.py` + `overlap_index.py`  
**API :** Aucune — données statiques vérifiées (sources officielles)  
**Signal :** Index hebdomadaire de superposition des vacances (0.0 → 1.0)

Fonctionnement :
- `calendar_data.py` contient toutes les périodes de vacances par marché **et par zone interne** (ex: Italie Nord vs Centre/Sud vs Nord-Est)
- `overlap_index.py` calcule pour chaque semaine ISO la somme pondérée des zones en vacances : `poids_marché × part_zone`
- L'index est plafonné à 1.0 et classé en 5 bandes d'intensité

| Index | Intensité | Signification |
|-------|-----------|---------------|
| ≥ 0.85 | Pic | 4 marchés pleinement alignés |
| ≥ 0.60 | Fort | 3 marchés alignés |
| ≥ 0.35 | Modéré | 2 marchés alignés |
| > 0 | Faible | 1 marché actif |
| 0 | Hors saison | Aucun marché en vacances |

> Signal de **possibilité** ("peuvent venir"), pas de confirmation. À croiser avec Piste 1.

---

### Piste 3 — Disponibilité hôtelière

**Fichier :** `piste3_hotels/hotel_availability.py`  
**API :** RapidAPI `apidojo-booking-v1.p.rapidapi.com` / `properties/list-by-map`  
**Signal :** Taux d'occupation estimé par zone (2-8 semaines d'avance)

Deux modes :
- **Mode LIVE** (si `RAPIDAPI_KEY` défini) : appelle Booking.com par bounding box géographique pour chaque zone, calcule le taux d'occupation à partir de `count/unfiltered_count`, `has_low_availability`, et proportion d'hôtels `soldout`
- **Mode CALIBRÉ** (fallback) : modèle synthétique basé sur saisonnalité CRT Île-de-France 2022-2024 + boosts événementiels vérifiés

Zones couvertes :

| Zone | Bounding box | Aéroports |
|------|-------------|-----------|
| Paris Centre (1er-8e) | 2.28,48.83 → 2.42,48.91 | CDG, ORY |
| Zone CDG (Roissy) | 2.48,48.97 → 2.63,49.05 | CDG |
| Zone Orly (Rungis) | 2.33,48.69 → 2.45,48.77 | ORY |
| Zone Disneyland | 2.74,48.83 → 2.84,48.90 | CDG, ORY |
| Zone Beauvais | 2.04,49.42 → 2.16,49.48 | BVA |

Niveaux de signal :

| Occupation | Signal | Action |
|-----------|--------|--------|
| ≥ 92 % | Saturé | Activer capacité max + tarif premium |
| ≥ 82 % | Tendu | Renforcer flotte — demande confirmée |
| ≥ 70 % | Actif | Niveau nominal — surveiller |
| ≥ 55 % | Modéré | Demande normale |
| < 55 % | Creux | Hors saison — promo possible |

---

### Piste 4 — Google Trends

**Fichier :** `piste4_trends/google_trends.py`  
**API :** `pytrends` (interface non-officielle Google Trends, gratuit) — mode offline par défaut  
**Signal :** Indice d'intention de voyage 2-4 semaines avant le départ

Deux modes :
- **Mode OFFLINE** (défaut) : données calibrées sur le pattern historique Google Trends 2022-2025 pour "Paris airport transfer" — vérifiable sur trends.google.com
- **Mode LIVE** (`--live`) : pytrends en temps réel — **à lancer uniquement en local** (Google bloque les datacenters)

Requêtes configurées par marché :

| Marché | Termes recherchés | Lead time |
|--------|------------------|-----------|
| France | "navette aeroport Paris", "transfert CDG", "transport Orly Paris" | 2 semaines |
| UK | "flights to Paris", "Paris airport transfer", "CDG shuttle" | 4 semaines |
| Italie | "voli Parigi", "transfer aeroporto Parigi", "navette Beauvais" | 3 semaines |
| Espagne | "vuelos Paris", "transfer aeropuerto Paris", "vuelos Beauvais" | 3 semaines |

L'index de chaque marché est **ramené à la semaine de voyage** (pas de recherche) en appliquant le lead time. La synthèse finale est la moyenne pondérée des 4 marchés.

---

## Orchestrateur — `main.py`

Charge dynamiquement chaque module Piste via `importlib` et appelle sa fonction `main()`. La configuration de chaque Piste (statut, clé requise, fichier de sortie) est centralisée dans le dictionnaire `PISTES`. Pour brancher une nouvelle Piste, ajouter une entrée dans ce dictionnaire et créer le module avec une fonction `main()`.

Statuts possibles : `active` | `pending` | `parked`

---

## Dépendances

```bash
pip install requests pandas streamlit plotly --break-system-packages

# Optionnel — Piste 4 live uniquement (à lancer en local)
pip install pytrends --break-system-packages
```

| Paquet | Usage |
|--------|-------|
| `requests` | Appels API AirLabs et RapidAPI |
| `pandas` | Manipulation et export CSV |
| `streamlit` | Dashboard web interactif |
| `plotly` | Graphiques interactifs |
| `pytrends` | Google Trends live (optionnel) |

---

## Variables d'environnement

| Variable | Piste | Comportement si absente |
|----------|-------|------------------------|
| `AIRLABS_API_KEY` | Piste 1 | Piste 1 skippée, warning affiché |
| `RAPIDAPI_KEY` | Piste 3 | Fallback sur modèle calibré CRT IDF |

---

## Fichiers de sortie

| Fichier | Piste | Colonnes clés |
|---------|-------|---------------|
| `ozeroute_routes_piste1.csv` | P1 | dep_iata, source_market, carrier_type, arr_iata, dep_time |
| `ozeroute_overlap_index_semaine_2026.csv` | P2 | semaine_debut, index_superposition, intensite, marches_actifs |
| `ozeroute_hotel_availability.csv` | P3 | zone_label, taux_occupation_estime, signal_rarete, source_donnee |
| `ozeroute_google_trends.csv` | P4 | market_label, trends_index, signal_trends, lead_time_weeks |
| `ozeroute_signal_combine.csv` | Combiné | index_superposition + piste1_disponible + signal_consolide |

---

## Roadmap

| Priorité | Tâche |
|----------|-------|
| 🔴 Court terme | Implémenter la logique de croisement routes × calendrier dans `run_combiner()` |
| 🟠 Moyen terme | Activer Piste 4 live (pytrends) depuis un serveur local ou proxy résidentiel |
| 🟡 Moyen terme | Calibrer les poids marchés avec données internes OzeRoute (conversion réelle) |
| 🟢 Long terme | Étendre à d'autres aéroports / marchés |
| 🟢 Long terme | Alertes automatiques quand l'index franchit un seuil (email / Slack) |
