"""
OzeRoute — Dashboard de prédiction demande
4 Pistes intégrées : Vols / Calendriers / Hôtels / Trends
"""

import os, sys, subprocess
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

ROOT       = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"

st.set_page_config(page_title="OzeRoute — Demand Pipeline", page_icon="✈️", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { background:#0d1117; }
.metric-box { background:#1e2130; border-radius:10px; padding:14px 18px;
               border-left:4px solid #4f8ef7; margin-bottom:8px; }
.badge { padding:2px 10px; border-radius:20px; font-size:11px;
         font-weight:600; display:inline-block; margin:2px 0; }
.badge-red    { background:#e74c3c; color:#fff; }
.badge-orange { background:#e67e22; color:#fff; }
.badge-yellow { background:#f1c40f; color:#000; }
.badge-green  { background:#27ae60; color:#fff; }
.badge-grey   { background:#7f8c8d; color:#fff; }
</style>
""", unsafe_allow_html=True)

DARK = {"paper_bgcolor":"#0e1117","plot_bgcolor":"#0e1117","font_color":"#fafafa"}
INTENSITY_COLORS = {"Pic":"#e74c3c","Fort":"#e67e22","Modéré":"#f1c40f",
                    "Faible":"#2ecc71","Hors saison":"#95a5a6"}
SIGNAL_COLORS    = {"Saturé":"#e74c3c","Tendu":"#e67e22","Actif":"#3498db",
                    "Modéré":"#f1c40f","Creux":"#95a5a6"}
TRENDS_COLORS    = {"Très fort":"#e74c3c","Fort":"#e67e22","Modéré":"#f1c40f",
                    "Faible":"#2ecc71","Hors saison":"#95a5a6"}
MARKET_COLORS    = {"UK":"#3498db","Espagne":"#e74c3c","Italie":"#2ecc71","France":"#9b59b6"}


# ── Loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def load_piste2():
    p = OUTPUT_DIR / "ozeroute_overlap_index_semaine_2026.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut","semaine_fin"])
    df["intensite_court"] = df["intensite"].str.split("—").str[0].str.strip()
    df["label_semaine"]   = df["semaine_debut"].dt.strftime("%d %b") + " – " + df["semaine_fin"].dt.strftime("%d %b")
    return df

@st.cache_data(ttl=10)
def load_piste1():
    p = OUTPUT_DIR / "ozeroute_routes_piste1.csv"
    if not p.exists(): return None
    return pd.read_csv(p)

@st.cache_data(ttl=10)
def load_piste3():
    p = OUTPUT_DIR / "ozeroute_hotel_availability.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut","semaine_fin"])
    df["label_semaine"] = df["semaine_debut"].dt.strftime("%d %b") + " – " + df["semaine_fin"].dt.strftime("%d %b")
    return df

@st.cache_data(ttl=10)
def load_piste4():
    p = OUTPUT_DIR / "ozeroute_google_trends.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut","semaine_fin"])
    df["label_semaine"] = df["semaine_debut"].dt.strftime("%d %b") + " – " + df["semaine_fin"].dt.strftime("%d %b")
    return df


# ── Sidebar ───────────────────────────────────────────────────────────────

with st.sidebar:
    logo_path = ROOT / "logo_oz.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=200)
    st.title("Prédiction de la Demande")

    st.markdown("### ⚙️ Lancer le pipeline")
    # Pre-fill from Streamlit Cloud secrets / env vars if available
    api_key = st.text_input("Clé AirLabs (optionnelle)", type="password",
                            value=os.environ.get("AIRLABS_API_KEY", ""),
                            placeholder="sk-airlabs-...")
    rapidapi_key = st.text_input("Clé RapidAPI (optionnelle)", type="password",
                                 value=os.environ.get("RAPIDAPI_KEY", ""),
                                 placeholder="rapidapi-key...")
    col_p3, col_p4 = st.columns(2)
    use_live_hotels = col_p3.toggle("Hôtels live", value=False, help="Nécessite RAPIDAPI_KEY")
    use_live_trends = col_p4.toggle("Trends live", value=False,
                                    help="Lancer localement — Google bloque les datacenters")

    if st.button("▶  Lancer", use_container_width=True, type="primary"):
        # Set env vars in-process so imported modules pick them up
        if api_key:      os.environ["AIRLABS_API_KEY"] = api_key
        if rapidapi_key: os.environ["RAPIDAPI_KEY"]    = rapidapi_key

        log_lines = []
        errors     = []

        def run_piste(module_path, label):
            import importlib.util, traceback
            try:
                spec = importlib.util.spec_from_file_location("_piste", ROOT / module_path)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.main()
                log_lines.append(f"✅ {label} terminée")
            except Exception as e:
                errors.append(f"❌ {label} : {e}")
                log_lines.append(traceback.format_exc())

        with st.spinner("Pipeline en cours…"):
            if api_key:
                run_piste("piste1_vols/piste1_routes.py",          "Piste 1 — Vols")
            else:
                log_lines.append("⚠️  Piste 1 ignorée — clé AirLabs absente")
            run_piste("piste2_calendriers/overlap_index.py",    "Piste 2 — Calendriers")
            run_piste("piste3_hotels/hotel_availability.py",    "Piste 3 — Hôtels")
            run_piste("piste4_trends/google_trends.py",         "Piste 4 — Trends")

            # Combiner
            try:
                import importlib.util, traceback
                spec = importlib.util.spec_from_file_location("_main", ROOT / "main.py")
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.run_combiner()
                log_lines.append("✅ Signal combiné")
            except Exception as e:
                log_lines.append(f"⚠️  Combineur : {e}")

        if errors:
            st.error("\n".join(errors))
        else:
            st.success("✅ Pipeline terminé")
        st.cache_data.clear()
        with st.expander("Log"):
            st.code("\n".join(log_lines))

    st.divider()
    st.markdown("### 🔍 Filtres")

    df2_raw = load_piste2()
    if df2_raw is not None:
        min_d = df2_raw["semaine_debut"].min().date()
        max_d = df2_raw["semaine_fin"].max().date()
        st.markdown("**📆 Période d'analyse**")
        date_range = st.date_input(
            "Sélectionner une plage de dates",
            value=(min_d, max_d),
            min_value=min_d,
            max_value=max_d,
            help="Filtrer toutes les pistes sur cette période",
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            st.caption(f"Du **{date_range[0].strftime('%d %b %Y')}** au **{date_range[1].strftime('%d %b %Y')}**")
    else:
        date_range = None

    intensity_filter = st.multiselect("Intensité (P2)",
        ["Pic","Fort","Modéré","Faible","Hors saison"],
        default=["Pic","Fort","Modéré","Faible","Hors saison"])

    airport_filter = st.multiselect("Aéroport",
        ["CDG","ORY","BVA"], default=["CDG","ORY","BVA"],
        format_func=lambda x: {"CDG":"Paris CDG","ORY":"Paris Orly","BVA":"Beauvais"}[x])

    zone_filter = st.multiselect("Zone hôtelière (P3)",
        ["paris_centre","cdg_zone","orly_zone","disneyland_zone","beauvais_zone"],
        default=["paris_centre","cdg_zone","orly_zone","disneyland_zone","beauvais_zone"],
        format_func=lambda x: x.replace("_"," ").title())

    st.divider()
    st.markdown("### 📊 Statut Pistes")
    def piste_badge(n, label, ok):
        icon = "✅" if ok else "⏳"
        st.markdown(f"{icon} **P{n}** {label}")

    piste_badge(1, "Vols", load_piste1() is not None)
    piste_badge(2, "Calendriers", df2_raw is not None)
    piste_badge(3, "Hôtels", load_piste3() is not None)
    piste_badge(4, "Trends", load_piste4() is not None)


# ── KPIs globaux ─────────────────────────────────────────────────────────

st.title("✈️ OzeRoute — Prédiction de Demande")

df2 = df2_raw.copy() if df2_raw is not None else None
df1 = load_piste1()
df3 = load_piste3()
df4 = load_piste4()

if df2 is None:
    st.info("Aucune donnée — lancez le pipeline via le panneau de gauche.")
    st.stop()

# Apply filters
if date_range and len(date_range) == 2:
    s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    df2 = df2[(df2["semaine_debut"] >= s) & (df2["semaine_fin"] <= e)]

df2 = df2[df2["intensite_court"].isin(intensity_filter)]

if df1 is not None:
    df1 = df1[df1["arr_iata"].isin(airport_filter)]

if df3 is not None:
    df3_filtered = df3[df3["zone_key"].isin(zone_filter)]
    if date_range and len(date_range) == 2:
        df3_filtered = df3_filtered[
            (df3_filtered["semaine_debut"] >= pd.Timestamp(date_range[0])) &
            (df3_filtered["semaine_fin"] <= pd.Timestamp(date_range[1]))
        ]
else:
    df3_filtered = None

if df4 is not None:
    df4_synth = df4[df4["market_code"] == "SYNTHESE"]
else:
    df4_synth = None

# KPI row
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Semaines Pic 🔴",   len(df2[df2["intensite_court"]=="Pic"]))
k2.metric("Semaines Fort 🟠",  len(df2[df2["intensite_court"]=="Fort"]))
k3.metric("Index moyen P2",    f"{df2['index_superposition'].mean():.2f}" if len(df2) else "—")
k4.metric("Routes actives ✈️", len(df1) if df1 is not None else "—")
sat = len(df3_filtered[df3_filtered["signal_rarete"]=="Saturé"]) if df3_filtered is not None and len(df3_filtered) else 0
k5.metric("Sem. Saturées 🏨",  sat)

st.divider()


# ── Tabs ─────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🛫 P1 — Routes",
    "📅 P2 — Calendriers",
    "🏨 P3 — Hôtels",
    "📈 P4 — Trends",
    "📋 Données brutes",
])


# ══ TAB 1 — Piste 1 Routes ════════════════════════════════════════════════
with tab1:
    if df1 is None or df1.empty:
        st.info("Pas de données Piste 1 — lancez le pipeline avec AIRLABS_API_KEY.")
    else:
        r1, r2 = st.columns(2)
        mkt = df1.groupby("source_market").size().reset_index(name="routes")
        fig3 = px.bar(mkt, x="source_market", y="routes", color="source_market",
                      title="Routes par marché source", height=320,
                      labels={"source_market":"Marché","routes":"Nb routes"})
        fig3.update_layout(**DARK, showlegend=False)
        r1.plotly_chart(fig3, use_container_width=True)

        apt = df1.groupby("arr_iata").size().reset_index(name="routes")
        fig4 = px.pie(apt, names="arr_iata", values="routes",
                      title="Distribution par aéroport cible", height=320,
                      color_discrete_sequence=["#4f8ef7","#e74c3c","#2ecc71"])
        fig4.update_layout(**DARK)
        r2.plotly_chart(fig4, use_container_width=True)

        st.subheader("Low-cost vs Réseau par aéroport")
        ct = df1.groupby(["arr_iata","carrier_type"]).size().reset_index(name="routes")
        fig5 = px.bar(ct, x="arr_iata", y="routes", color="carrier_type", barmode="group",
                      height=300, title="Low-cost vs Réseau",
                      color_discrete_map={"low-cost Beauvais":"#e74c3c","réseau/hybride":"#4f8ef7","autre":"#95a5a6"})
        fig5.update_layout(**DARK)
        st.plotly_chart(fig5, use_container_width=True)

        st.subheader("Liste des routes")
        disp = ["dep_iata","source_market","carrier_type","arr_iata","airline_iata","flight_iata","dep_time"]
        st.dataframe(df1[disp].rename(columns={
            "dep_iata":"Départ","source_market":"Marché","carrier_type":"Type",
            "arr_iata":"Arrivée","airline_iata":"Cie","flight_iata":"Vol","dep_time":"Heure"}),
            use_container_width=True, height=350)


# ══ TAB 2 — Piste 2 Calendriers ══════════════════════════════════════════
with tab2:
    if df2.empty:
        st.warning("Aucune semaine — vérifier les filtres.")
    else:
        # Per-market zone contributions (market_weight × zone_share, normalized to [0,1])
        _ZONE_CONTRIB = {
            "France":  {"France": 0.40},
            "UK":      {"England & Wales": 0.187, "Écosse": 0.033},
            "Italie":  {"Nord (Emilia": 0.07, "Centre/Sud": 0.10, "Nord-Est": 0.03},
            "Espagne": {"Madrid": 0.072, "Catalogne": 0.072, "Baléares": 0.036},
        }
        _MARKET_MAX = {"France": 0.40, "UK": 0.22, "Italie": 0.20, "Espagne": 0.18}
        _MARKET_COLORS = {"France": "#4f8ef7", "UK": "#e74c3c", "Italie": "#2ecc71", "Espagne": "#e67e22"}

        def _mkt_idx(zones_str, market):
            if not zones_str or zones_str == "—":
                return 0.0
            total = sum(w for k, w in _ZONE_CONTRIB[market].items() if k in zones_str)
            return round(min(total / _MARKET_MAX[market], 1.0), 3)

        # Market selector cards
        _OPTIONS = ["🌐 Global", "🇫🇷 FR", "🇬🇧 UK", "🇮🇹 IT", "🇪🇸 ES"]
        _MKT_MAP  = {"🇫🇷 FR": "France", "🇬🇧 UK": "UK", "🇮🇹 IT": "Italie", "🇪🇸 ES": "Espagne"}
        try:
            market_sel = st.pills("Marché", options=_OPTIONS, default="🌐 Global",
                                  label_visibility="collapsed")
        except Exception:
            market_sel = st.radio("Marché", _OPTIONS, horizontal=True,
                                  label_visibility="collapsed")

        if market_sel == "🌐 Global" or market_sel is None:
            fig = go.Figure()
            for intensity in ["Pic","Fort","Modéré","Faible","Hors saison"]:
                sub = df2[df2["intensite_court"] == intensity]
                if sub.empty: continue
                fig.add_trace(go.Bar(
                    x=sub["label_semaine"], y=sub["index_superposition"],
                    name=intensity, marker_color=INTENSITY_COLORS[intensity],
                    hovertemplate="<b>%{x}</b><br>Index : %{y:.2f}<extra></extra>",
                ))
            fig.update_layout(**DARK, barmode="overlay",
                title="Index de superposition hebdomadaire — Global (Piste 2)",
                xaxis_title="Semaine", yaxis=dict(range=[0,1.05]), height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            _market = _MKT_MAP[market_sel]
            _color  = _MARKET_COLORS[_market]
            _vals   = [_mkt_idx(str(r.get("zones_detail","")), _market) for _, r in df2.iterrows()]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df2["label_semaine"], y=_vals,
                marker_color=_color, name=_market,
                hovertemplate="<b>%{x}</b><br>Index " + _market + " : %{y:.2f}<extra></extra>",
            ))
            fig.update_layout(**DARK,
                title=f"Contribution hebdomadaire — {_market} (Piste 2)",
                xaxis_title="Semaine",
                yaxis=dict(range=[0,1.05], title="Index [0 → 1]"),
                height=400)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Marchés actifs par semaine")
        hm_data = []
        for _, row in df2.iterrows():
            a = row.get("marches_actifs","") or ""
            hm_data.append({"Semaine":row["label_semaine"],
                "ES":1 if "Espagne" in a else 0, "FR":1 if "France" in a else 0,
                "IT":1 if "Italie" in a else 0,  "UK":1 if "UK" in a else 0})
        hm_df = pd.DataFrame(hm_data).set_index("Semaine")
        fig2 = px.imshow(hm_df.T, color_continuous_scale=[[0,"#1e2130"],[1,"#4f8ef7"]],
                         aspect="auto", height=180,
                         labels=dict(x="Semaine",y="Marché",color="Actif"))
        fig2.update_layout(**DARK, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Détail semaine par semaine")
        for _, row in df2.iterrows():
            ic = row["intensite_court"]
            color = INTENSITY_COLORS.get(ic, "#7f8c8d")
            c1, c2, c3 = st.columns([2,1,5])
            c1.markdown(f"**{row['label_semaine']}**")
            c2.markdown(f'<span class="badge" style="background:{color};color:{"#000" if ic=="Modéré" else "#fff"}">{ic}</span>',
                        unsafe_allow_html=True)
            z = str(row.get("zones_detail",""))
            c3.caption(z[:120]+("…" if len(z)>120 else ""))


# ══ TAB 3 — Piste 3 Hôtels ════════════════════════════════════════════════
with tab3:
    if df3_filtered is None or df3_filtered.empty:
        st.info("Pas de données Piste 3 — lancez le pipeline.")
    else:
        st.markdown("**Signal de rareté hôtelière** par zone et par semaine."
                    " Taux d'occupation estimé (mode calibré CRT IDF + événements).")

        # Heatmap occupation par zone × semaine
        pivot = df3_filtered.pivot_table(
            index="zone_label", columns="label_semaine",
            values="taux_occupation_estime", aggfunc="mean"
        )
        fig6 = px.imshow(pivot,
            color_continuous_scale=[[0,"#1a472a"],[0.5,"#f1c40f"],[1,"#e74c3c"]],
            zmin=0.4, zmax=1.0, aspect="auto", height=300,
            labels=dict(x="Semaine", y="Zone", color="Occupation"),
            title="Taux d'occupation estimé par zone hôtelière")
        fig6.update_layout(**DARK)
        st.plotly_chart(fig6, use_container_width=True)

        # Signal par zone — barres
        st.subheader("Signal de rareté par zone")
        signal_order = ["Saturé","Tendu","Actif","Modéré","Creux"]
        zone_signal = df3_filtered.groupby(["zone_label","signal_rarete"]).size().reset_index(name="semaines")
        zone_signal["signal_rarete"] = pd.Categorical(zone_signal["signal_rarete"], categories=signal_order, ordered=True)
        fig7 = px.bar(zone_signal.sort_values("signal_rarete"),
            x="zone_label", y="semaines", color="signal_rarete", barmode="stack",
            color_discrete_map=SIGNAL_COLORS, height=320,
            labels={"zone_label":"Zone","semaines":"Semaines","signal_rarete":"Signal"},
            title="Distribution du signal de rareté par zone")
        fig7.update_layout(**DARK)
        st.plotly_chart(fig7, use_container_width=True)

        # Événements actifs
        st.subheader("Événements à fort impact hôtelier")
        events_rows = df3_filtered[df3_filtered["evenements_actifs"] != "—"][
            ["semaine_debut","label_semaine","zone_label","taux_occupation_estime","signal_rarete","evenements_actifs"]
        ].drop_duplicates().sort_values("semaine_debut").drop(columns=["semaine_debut"])
        if not events_rows.empty:
            st.dataframe(events_rows.rename(columns={
                "label_semaine":"Semaine","zone_label":"Zone",
                "taux_occupation_estime":"Occupation","signal_rarete":"Signal",
                "evenements_actifs":"Événements"}),
                use_container_width=True, height=280)
        else:
            st.caption("Aucun événement boosting dans la période sélectionnée.")

        # Action recommandée par zone (paris_centre focus)
        st.subheader("Recommandations opérationnelles — Paris Centre")
        pc = df3_filtered[df3_filtered["zone_key"]=="paris_centre"].sort_values("semaine_debut")
        for _, row in pc.iterrows():
            sig = row["signal_rarete"]
            color = SIGNAL_COLORS.get(sig, "#7f8c8d")
            c1, c2, c3, c4 = st.columns([2,1,1,4])
            c1.markdown(f"**{row['label_semaine']}**")
            c2.markdown(f'<span class="badge" style="background:{color};color:{"#000" if sig=="Modéré" else "#fff"}">{sig}</span>',
                        unsafe_allow_html=True)
            c3.markdown(f"`{row['taux_occupation_estime']:.0%}`")
            c4.caption(row["action_recommandee"])


# ══ TAB 4 — Piste 4 Trends ════════════════════════════════════════════════
with tab4:
    if df4 is None or df4_synth is None or df4_synth.empty:
        st.info("Pas de données Piste 4 — lancez le pipeline.")
    else:
        st.markdown("**Indice Google Trends** par marché source (mode offline calibré 2022-2025)."
                    " Signal d'intention de voyage 2-4 semaines avant le départ.")

        # Ligne synthèse + par marché
        df4_markets = df4[df4["market_code"] != "SYNTHESE"]

        fig8 = go.Figure()
        for market_label, color in MARKET_COLORS.items():
            sub = df4_markets[df4_markets["market_label"]==market_label]
            if sub.empty: continue
            fig8.add_trace(go.Scatter(
                x=sub["label_semaine"], y=sub["trends_index"],
                name=market_label, line=dict(color=color, width=1.5, dash="dot"),
                mode="lines", opacity=0.7))

        fig8.add_trace(go.Scatter(
            x=df4_synth["label_semaine"], y=df4_synth["trends_index"],
            name="Synthèse pondérée", line=dict(color="#fff", width=2.5),
            mode="lines+markers", marker=dict(size=5)))

        fig8.update_layout(**DARK, title="Indice Google Trends par marché source",
            xaxis_title="Semaine de VOYAGE (index décalé du lead time marché)",
            yaxis_title="Indice (0-100)", height=400)
        st.plotly_chart(fig8, use_container_width=True)

        # Lead time explication
        with st.expander("ℹ️ Comment lire ce graphique ?"):
            st.markdown("""
Le graphique montre l'indice Trends **ramené à la semaine de voyage**, pas à la semaine de recherche.

**Lead time par marché :**
- 🇫🇷 France : 2 semaines (réserve tard)
- 🇬🇧 UK : 4 semaines (réserve tôt)
- 🇮🇹 Italie : 3 semaines
- 🇪🇸 Espagne : 3 semaines

**Lecture :** un index de 90 semaine du 27 juil pour le UK signifie que les Britanniques
cherchaient activement "Paris airport transfer" autour de la semaine du 29 juin.

**Limite :** en mode offline, ces données sont calibrées sur le pattern historique 2022-2025
(vérifiable sur trends.google.com). Pour le live, lancer `python3 google_trends.py --live`
**depuis ta machine locale** — Google bloque les datacenters.
            """)

        # Tableau synthèse
        st.subheader("Synthèse hebdomadaire")
        display_synth = df4_synth[["label_semaine","trends_index","signal_trends"]].copy()
        display_synth.columns = ["Semaine","Index Trends","Signal"]
        st.dataframe(display_synth, use_container_width=True, height=400, hide_index=True)


# ══ TAB 5 — Données brutes ════════════════════════════════════════════════
with tab5:
    tabs_data = st.tabs(["P2 Calendrier","P1 Routes","P3 Hôtels","P4 Trends"])

    with tabs_data[0]:
        st.dataframe(df2, use_container_width=True)
        st.download_button("⬇ Télécharger", df2.to_csv(index=False),
                           "p2_calendrier.csv", "text/csv")

    with tabs_data[1]:
        if df1 is not None:
            st.dataframe(df1, use_container_width=True)
            st.download_button("⬇ Télécharger", df1.to_csv(index=False),
                               "p1_routes.csv", "text/csv")
        else:
            st.info("Piste 1 non disponible.")

    with tabs_data[2]:
        if df3 is not None:
            st.dataframe(df3, use_container_width=True)
            st.download_button("⬇ Télécharger", df3.to_csv(index=False),
                               "p3_hotels.csv", "text/csv")
        else:
            st.info("Piste 3 non disponible.")

    with tabs_data[3]:
        if df4 is not None:
            st.dataframe(df4, use_container_width=True)
            st.download_button("⬇ Télécharger", df4.to_csv(index=False),
                               "p4_trends.csv", "text/csv")
        else:
            st.info("Piste 4 non disponible.")
