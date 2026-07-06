"""
OzeRoute — Piste 2 : Calendriers scolaires des 4 marchés sources
==================================================================
Sources vérifiées (web search, juin 2026) :
- France   : ministère Éducation nationale, zone C (Paris/Créteil/Versailles)
- Italie   : calendari regionali 2026 — agrégation par macro-zone (Nord/Centre/Sud)
- UK       : England & Wales (gov.uk + agrégateurs council-level), zone dominante du flux touristique
- Espagne  : Comunidades Autónomas — agrégation par grandes zones (Madrid/Catalogne/National)

Granularité : semaine ISO. Période couverte : 1 juin -> 30 septembre 2026.
Chaque marché peut avoir plusieurs "zones" avec des dates différentes (ex: France A/B/C,
Italie Nord/Sud, Espagne Madrid/Catalogne/Baléares, UK Angleterre/Écosse).

Cadrage du document source : un signal scolaire seul est une "borne de possibilité"
("peuvent venir"), pas une décision ("viennent"). Il sera combiné à la Piste 1 (vols)
pour la confirmation.
"""

from datetime import date

# ──────────────────────────────────────────────────────────────
# Chaque entrée : (marché, zone, libellé, début vacances, fin vacances, poids_marché)
# poids_marché = poids relatif approximatif du marché source dans le flux touristique
# OzeRoute Paris (à calibrer plus tard avec données internes réelles — ici valeur de
# départ raisonnable basée sur la taille du marché émetteur vers Paris/IDF)
# ──────────────────────────────────────────────────────────────

MARKET_WEIGHTS = {
    "France": 0.40,    # marché domestique, plus gros volume mais paniers plus courts
    "Italie": 0.20,
    "Espagne": 0.18,
    "UK": 0.22,
}

# Le poids de chaque marché est réparti entre ses sous-zones, proportionnellement
# à une estimation de poids démographique/touristique de la zone (à calibrer plus tard
# avec les données internes réelles). Valeurs de départ raisonnables.
ZONE_WEIGHT_SHARE = {
    # France — zones A/B/C n'existent QUE pour hiver/printemps ; l'été est groupé
    # donc une seule zone porte 100% du poids France
    ("France", "Toutes zones"): 1.0,

    # Italie — Nord part avant, Sud/Centre suit, Nord-Est (Alto Adige) très tardif
    ("Italie", "Nord (Emilia-Romagna)"): 0.35,
    ("Italie", "Centre/Sud (majorité régions)"): 0.50,
    ("Italie", "Nord-Est (South Tyrol)"): 0.15,

    # Espagne — Madrid/Catalogne = gros volumes simultanés, Baléares plus petit mais tardif
    ("Espagne", "Madrid"): 0.40,
    ("Espagne", "Catalogne"): 0.40,
    ("Espagne", "Baléares (départ tardif)"): 0.20,

    # UK — Angleterre/Galles = écrasante majorité du flux vers Paris, Écosse minoritaire
    ("UK", "England & Wales"): 0.85,
    ("UK", "Écosse (départ précoce)"): 0.15,
}

SUMMER_HOLIDAYS_2026 = [
    # FRANCE — zones A/B/C, dates officielles communes pour l'été (toutes zones)
    dict(market="France", zone="Toutes zones", start=date(2026, 7, 4), end=date(2026, 8, 31),
         source="education.gouv.fr / vacances-scolaires-education.fr — arrêté officiel"),

    # ITALIE — 3 fenêtres de départ échelonnées par macro-région
    dict(market="Italie", zone="Nord (Emilia-Romagna)", start=date(2026, 6, 7), end=date(2026, 9, 6),
         source="calendarglobe.com — calendrier régional Emilia-Romagna 2026"),
    dict(market="Italie", zone="Centre/Sud (majorité régions)", start=date(2026, 6, 8), end=date(2026, 9, 6),
         source="calendarglobe.com — moyenne régions Sicile/Calabre/Campanie/Vénétie 2026"),
    dict(market="Italie", zone="Nord-Est (South Tyrol)", start=date(2026, 6, 17), end=date(2026, 9, 6),
         source="calendarglobe.com — calendrier régional South Tyrol 2026"),

    # ESPAGNE — 3 fenêtres
    dict(market="Espagne", zone="Madrid", start=date(2026, 6, 20), end=date(2026, 9, 6),
         source="calendarglobe.com / idealista.com — Comunidad de Madrid 2026"),
    dict(market="Espagne", zone="Catalogne", start=date(2026, 6, 20), end=date(2026, 9, 6),
         source="calendarglobe.com / ucranianos.uno — Catalunya 2026"),
    dict(market="Espagne", zone="Baléares (départ tardif)", start=date(2026, 6, 20), end=date(2026, 9, 11),
         source="calendarglobe.com — Illes Balears 2026"),

    # UK — England/Wales (flux dominant vers Paris) + Écosse (flux secondaire, départ précoce)
    dict(market="UK", zone="England & Wales", start=date(2026, 7, 23), end=date(2026, 9, 1),
         source="localpage.uk / ukcalculator.com — agrégation council-level 2026"),
    dict(market="UK", zone="Écosse (départ précoce)", start=date(2026, 6, 29), end=date(2026, 8, 14),
         source="ukcalculator.com — agrégation councils écossais 2026"),
]

# Vacances additionnelles pertinentes hors été (mentionnées dans le document de cadrage —
# notamment la Toussaint française qui chevauche le half-term britannique)
SHOULDER_HOLIDAYS_2026 = [
    dict(market="France", zone="Toussaint (toutes zones)", start=date(2026, 10, 17), end=date(2026, 11, 2),
         source="education.gouv.fr — confirmée"),
    dict(market="UK", zone="October half-term England/Wales", start=date(2026, 10, 26), end=date(2026, 10, 30),
         source="ukcalculator.com 2026"),
    dict(market="UK", zone="October half-term Écosse (précoce)", start=date(2026, 10, 13), end=date(2026, 10, 17),
         source="ukcalculator.com 2026"),
]

if __name__ == "__main__":
    print(f"France/Italie/Espagne/UK — {len(SUMMER_HOLIDAYS_2026)} entrées été 2026 chargées")
    print(f"Poids marchés : {MARKET_WEIGHTS}")
