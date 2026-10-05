"""
OzeRoute — Dashboard de prédiction demande
4 Pistes intégrées : Vols / Calendriers / Hôtels / Trends
"""

import io, os, sys, subprocess
from datetime import date as _date
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
.metric-box { border-radius:10px; padding:14px 18px;
               border-left:4px solid #4f8ef7; margin-bottom:8px; }
.badge { padding:2px 10px; border-radius:20px; font-size:11px;
         font-weight:600; display:inline-block; margin:2px 0; }
[data-testid="stDateInput"] input {
    border: 1.5px solid #4f8ef7 !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
.badge-red    { background:#e74c3c; color:#fff; }
.badge-orange { background:#e67e22; color:#fff; }
.badge-yellow { background:#f1c40f; color:#000; }
.badge-green  { background:#27ae60; color:#fff; }
.badge-grey   { background:#7f8c8d; color:#fff; }
</style>
""", unsafe_allow_html=True)

DARK = {"paper_bgcolor":"rgba(0,0,0,0)", "plot_bgcolor":"rgba(0,0,0,0)"}
INTENSITY_COLORS = {"Pic":"#e74c3c","Fort":"#e67e22","Modéré":"#f1c40f",
                    "Faible":"#2ecc71","Hors saison":"#95a5a6"}
SIGNAL_COLORS    = {"Saturé":"#e74c3c","Tendu":"#e67e22","Actif":"#3498db",
                    "Modéré":"#f1c40f","Creux":"#95a5a6"}
TRENDS_COLORS    = {"Très fort":"#e74c3c","Fort":"#e67e22","Modéré":"#f1c40f",
                    "Faible":"#2ecc71","Hors saison":"#95a5a6"}
MARKET_COLORS    = {"France":"#4f8ef7","UK":"#e74c3c","Italie":"#2ecc71","Espagne":"#e67e22"}
AIRPORT_COLORS   = {"CDG":"#6b7fa8","BVA":"#9aaacf","ORY":"#3d5275"}


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

@st.cache_data(ttl=10)
def load_piste5():
    p = OUTPUT_DIR / "ozeroute_saisonnalite_historique.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut","semaine_fin"])
    df["label_semaine"] = df["semaine_debut"].dt.strftime("%d %b") + " – " + df["semaine_fin"].dt.strftime("%d %b")
    return df

@st.cache_data(ttl=10)
def load_piste6():
    p = OUTPUT_DIR / "ozeroute_meteo_prevue.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut","semaine_fin"])
    df["label_semaine"] = df["semaine_debut"].dt.strftime("%d %b") + " – " + df["semaine_fin"].dt.strftime("%d %b")
    return df

@st.cache_data(ttl=5)
def load_commandes():
    p = OUTPUT_DIR / "ozeroute_commandes_reelles.csv"
    if not p.exists(): return None
    df = pd.read_csv(p, parse_dates=["semaine_debut"])
    df["label_semaine"] = df["semaine_debut"].dt.strftime("%d %b")
    return df

@st.cache_data(ttl=5)
def load_calibration():
    import json
    p = OUTPUT_DIR / "ozeroute_calibration.json"
    if not p.exists(): return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

@st.cache_data(ttl=5)
def load_optimized_weights():
    import json
    p = OUTPUT_DIR / "ozeroute_poids_optimises.json"
    if not p.exists(): return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if data.get("statut") == "calibre" else {}
    except Exception:
        return {}


# ── Sidebar ───────────────────────────────────────────────────────────────

with st.sidebar:
    logo_path = ROOT / "logo_oz.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=200)
    st.title("Prédiction de la Demande")

    st.markdown("### ⚙️ Lancer le pipeline")
    # Pre-fill from Streamlit Cloud secrets / env vars if available
    # Read keys: st.secrets (Streamlit Cloud) → os.environ → empty
    def _get_secret(key):
        try:
            return st.secrets.get(key, os.environ.get(key, ""))
        except Exception:
            return os.environ.get(key, "")

    api_key = st.text_input("Clé AirLabs (optionnelle)", type="password",
                            value=_get_secret("AIRLABS_API_KEY"),
                            placeholder="sk-airlabs-...")
    rapidapi_key = st.text_input("Clé RapidAPI (optionnelle)", type="password",
                                 value=_get_secret("RAPIDAPI_KEY"),
                                 placeholder="rapidapi-key...")
    col_p3, col_p4 = st.columns(2)
    use_live_hotels = col_p3.toggle("Hôtels live", value=False, help="Nécessite RAPIDAPI_KEY")
    use_live_trends = col_p4.toggle("Trends live", value=False,
                                    help="Lancer localement — Google bloque les datacenters")

    if st.button("▶  Lancer", use_container_width=True, type="primary"):
        # Resolve effective keys: input field → secrets → env
        eff_airlabs  = api_key      or _get_secret("AIRLABS_API_KEY")
        eff_rapidapi = rapidapi_key or _get_secret("RAPIDAPI_KEY")

        if eff_airlabs:  os.environ["AIRLABS_API_KEY"] = eff_airlabs
        if eff_rapidapi: os.environ["RAPIDAPI_KEY"]    = eff_rapidapi

        log_lines = []
        errors    = []

        def run_piste(module_path, label, timeout=60):
            import importlib.util, traceback, threading
            holder = [None]  # [exception | "ok" | None=timeout]

            def _run():
                try:
                    spec = importlib.util.spec_from_file_location("_piste", ROOT / module_path)
                    mod  = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.main()
                    holder[0] = "ok"
                except Exception as e:
                    holder[0] = (e, traceback.format_exc())

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=timeout)

            if t.is_alive():
                log_lines.append(f"⏱️ {label} : timeout ({timeout}s) — résultat partiel possible")
            elif holder[0] == "ok":
                log_lines.append(f"✅ {label} terminée")
            elif holder[0] is not None:
                e, tb = holder[0]
                errors.append(f"❌ {label} : {e}")
                log_lines.append(tb)

        with st.spinner("Pipeline en cours…"):
            if eff_airlabs:
                run_piste("piste1_vols/piste1_routes.py",       "Piste 1 — Vols")
            else:
                log_lines.append("⚠️  Piste 1 ignorée — clé AirLabs absente")
            run_piste("piste2_calendriers/overlap_index.py",        "Piste 2 — Calendriers")
            run_piste("piste3_hotels/hotel_availability.py",        "Piste 3 — Hôtels")
            run_piste("piste4_trends/google_trends.py",             "Piste 4 — Trends")
            run_piste("piste5_saisonnalite/historical_seasonality.py", "Piste 5 — Saisonnalité")
            run_piste("piste6_meteo/weather_forecast.py",           "Piste 6 — Météo")

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

        st.cache_data.clear()
        if errors:
            st.error("\n".join(errors))
        else:
            st.success("✅ Pipeline terminé — rechargement…")
        with st.expander("Log"):
            st.code("\n".join(log_lines))
        st.rerun()

    st.divider()
    st.markdown("### 🔍 Filtres")

    df2_raw = load_piste2()
    if df2_raw is not None:
        min_d   = df2_raw["semaine_debut"].min().date()
        max_d   = df2_raw["semaine_fin"].max().date()
        today   = _date.today()
        st.markdown("""
<div style="border:1.5px solid #4f8ef7;border-radius:10px;
            padding:12px 14px 6px 14px;margin-bottom:8px;">
<span style="color:#4f8ef7;font-size:13px;font-weight:700;letter-spacing:.5px;">
📆 PÉRIODE D'ANALYSE</span>
</div>""", unsafe_allow_html=True)

        start_d = st.date_input("Du", value=min_d, min_value=min_d, max_value=max_d)
        end_d   = st.date_input("Au", value=max_d, min_value=min_d, max_value=max_d)
        if end_d < start_d:
            st.error("La date de fin doit être après la date de début.")
            end_d = max_d
        date_range = (start_d, end_d)
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
    piste_badge(5, "Saisonnalité", load_piste5() is not None)
    piste_badge(6, "Météo", load_piste6() is not None)
    piste_badge(7, "Import Réel", load_commandes() is not None)


# ── KPIs globaux ─────────────────────────────────────────────────────────

st.title("✈️ OzeRoute — Prédiction de la Demande")

df2 = df2_raw.copy() if df2_raw is not None else None
df1 = load_piste1()
df3 = load_piste3()
df4 = load_piste4()
df5 = load_piste5()
df6 = load_piste6()

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

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "🛫 P1 — Routes",
    "📅 P2 — Calendriers",
    "🏨 P3 — Hôtels",
    "📈 P4 — Trends",
    "📊 P5 — Saisonnalité",
    "🌤 P6 — Météo",
    "🎯 Synthèse Prédictive",
    "📋 Données brutes",
    "📥 Import Réel & Calibration",
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
                      color_discrete_map=MARKET_COLORS,
                      labels={"source_market":"Marché","routes":"Nb routes"})
        fig3.update_layout(**DARK, showlegend=False)
        r1.plotly_chart(fig3, use_container_width=True)

        apt = df1.groupby("arr_iata").size().reset_index(name="routes")
        apt["pct"] = (apt["routes"] / apt["routes"].sum() * 100).round(1)
        apt = apt.sort_values("routes", ascending=True)
        fig4 = go.Figure(go.Bar(
            x=apt["routes"], y=apt["arr_iata"], orientation="h",
            marker_color="#4f8ef7",
            text=[f"{r}  ({p}%)" for r, p in zip(apt["routes"], apt["pct"])],
            textposition="outside", cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} routes<extra></extra>",
        ))
        fig4.update_layout(**DARK,
            title="Distribution par aéroport cible",
            xaxis=dict(visible=False), yaxis=dict(tickfont=dict(size=14, color="#fafafa")),
            height=320, margin=dict(r=80))
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
            _color  = MARKET_COLORS[_market]
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
        fig2 = px.imshow(hm_df.T, color_continuous_scale=[[0,"#d0d8f0"],[1,"#4f8ef7"]],
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
        st.markdown("**Pression hôtelière** par zone et par semaine."
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
        st.subheader("Pression hôtelière par zone")
        signal_order = ["Saturé","Tendu","Actif","Modéré","Creux"]
        zone_signal = df3_filtered.groupby(["zone_label","signal_rarete"]).size().reset_index(name="semaines")
        zone_signal["signal_rarete"] = pd.Categorical(zone_signal["signal_rarete"], categories=signal_order, ordered=True)
        fig7 = px.bar(zone_signal.sort_values("signal_rarete"),
            x="zone_label", y="semaines", color="signal_rarete", barmode="stack",
            color_discrete_map=SIGNAL_COLORS, height=320,
            labels={"zone_label":"Zone","semaines":"Semaines","signal_rarete":"Signal"},
            title="Pression hôtelière par zone")
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


# ══ TAB 5 — P5 Saisonnalité ══════════════════════════════════════════════
with tab5:
    if df5 is None or df5.empty:
        st.info("Pas de données Piste 5 — lancez le pipeline.")
    else:
        st.markdown("**Indice de saisonnalité historique** calibré sur le trafic passagers ADP 2022-2024. "
                    "Signal de fond (15 % dans l'horizon stratégique 3-6 mois).")
        df5_f = df5.copy()
        if date_range and len(date_range) == 2:
            s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
            df5_f = df5_f[(df5_f["semaine_debut"] >= s) & (df5_f["semaine_fin"] <= e)]

        SAISON_COLORS = {
            "Pic saisonnier":      "#e74c3c",
            "Haute saison":        "#e67e22",
            "Saison intermédiaire":"#f1c40f",
            "Basse saison":        "#2ecc71",
            "Creux":               "#95a5a6",
        }
        fig_s5 = go.Figure()
        for label, color in SAISON_COLORS.items():
            sub = df5_f[df5_f["label_saison"] == label]
            if sub.empty: continue
            fig_s5.add_trace(go.Bar(
                x=sub["label_semaine"], y=sub["saison_index"],
                name=label, marker_color=color,
                hovertemplate="<b>%{x}</b><br>Index : %{y:.2f}<extra></extra>",
            ))
        fig_s5.update_layout(**DARK, barmode="overlay",
            title="Indice de saisonnalité hebdomadaire (P5)",
            xaxis_title="Semaine", yaxis=dict(range=[0, 1.1]), height=380)
        st.plotly_chart(fig_s5, use_container_width=True)

        with st.expander("ℹ️ Source et méthode"):
            st.markdown("""
**Source :** Rapports mensuels de trafic passagers ADP (adp.aeroports.fr) — moyennes 2022-2024.

**Méthode :** Indice mensuel normalisé sur 1.0 = pic absolu (août), avec boost événementiel
sur les semaines à fort signal historique (Toussaint S43, fêtes S52).

**Usage :** Signal de tendance de fond — ne jamais utiliser seul. Croiser avec P2 (calendriers)
pour distinguer "les hôtels sont pleins parce que c'est l'été" vs "parce qu'un marché spécifique est en vacances".
""")

        st.subheader("Détail semaine par semaine")
        for _, row in df5_f.iterrows():
            c1, c2, c3 = st.columns([2, 2, 3])
            c1.markdown(f"**{row['label_semaine']}**")
            color = SAISON_COLORS.get(row["label_saison"], "#7f8c8d")
            c2.markdown(
                f'<span style="background:{color};color:#fff;padding:3px 10px;'
                f'border-radius:20px;font-size:12px;font-weight:700;">{row["label_saison"]}</span>',
                unsafe_allow_html=True)
            c3.caption(f"Index : {row['saison_index']:.2f}  —  S{row['iso_week']:02d}")


# ══ TAB 6 — P6 Météo ══════════════════════════════════════════════════════
with tab6:
    if df6 is None or df6.empty:
        st.info("Pas de données Piste 6 — lancez le pipeline.")
    else:
        st.markdown("**Prévision météo** par aéroport — signal d'affinage tactique (5 % horizon 1-4 semaines). "
                    "Données Live : Open-Meteo (gratuit, sans clé). Fallback calibré au-delà de J+14.")
        df6_f = df6.copy()
        if date_range and len(date_range) == 2:
            s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
            df6_f = df6_f[(df6_f["semaine_debut"] >= s) & (df6_f["semaine_fin"] <= e)]

        METEO_COLORS = {
            "Très favorable":  "#2ecc71",
            "Favorable":       "#3498db",
            "Neutre":          "#95a5a6",
            "Défavorable":     "#e67e22",
            "Très défavorable":"#e74c3c",
        }
        # Impact chart per airport
        fig_m = go.Figure()
        for apt in ["CDG", "ORY", "BVA"]:
            sub = df6_f[df6_f["airport"] == apt]
            if sub.empty: continue
            fig_m.add_trace(go.Bar(
                x=sub["label_semaine"], y=sub["meteo_impact"],
                name=apt, marker_color=AIRPORT_COLORS.get(apt, "#7f8c8d"),
                hovertemplate=f"<b>%{{x}}</b><br>{apt} impact : %{{y:+.2f}}<extra></extra>",
            ))
        fig_m.add_hline(y=0, line_color="#ffffff", line_width=1, line_dash="dot")
        fig_m.update_layout(**DARK, barmode="group",
            title="Impact météo par aéroport (−0.15 → +0.15)",
            xaxis_title="Semaine", yaxis_title="Impact", height=360)
        st.plotly_chart(fig_m, use_container_width=True)

        # Detail table
        st.subheader("Détail météo par semaine et aéroport")
        latest_week = df6_f["semaine_debut"].min()
        pivot_rows = []
        for lbl in df6_f["label_semaine"].unique():
            row_data = {"Semaine": lbl}
            for apt in ["CDG", "ORY", "BVA"]:
                sub = df6_f[(df6_f["label_semaine"] == lbl) & (df6_f["airport"] == apt)]
                if len(sub):
                    r = sub.iloc[0]
                    row_data[f"{apt} 🌧 mm"]  = r["rain_mm"]
                    row_data[f"{apt} 🌡 °C"]  = r["temp_c"]
                    row_data[f"{apt} impact"] = f"{r['meteo_impact']:+.2f}"
                    row_data[f"{apt} source"] = "🔴 Live" if "live" in r["source"].lower() else "⚪ Calibré"
            pivot_rows.append(row_data)
        st.dataframe(pd.DataFrame(pivot_rows), use_container_width=True, hide_index=True)


# ══ TAB 7 — Synthèse Prédictive ══════════════════════════════════════════════
with tab7:
    st.markdown(
        "Combinaison pondérée des 4 Pistes selon les horizons définis dans le document de cadrage OzeRoute. "
        "L'indice est relatif **(0 → 100)**, pas un nombre de courses."
    )

    # ── Horizon selector ────────────────────────────────────────────────
    try:
        horizon = st.pills(
            "Horizon",
            options=["⚡ Tactique (1-4 sem.)", "📅 Stratégique (3-6 mois)"],
            default="⚡ Tactique (1-4 sem.)",
        )
    except Exception:
        horizon = st.radio(
            "Horizon", ["⚡ Tactique (1-4 sem.)", "📅 Stratégique (3-6 mois)"],
            horizontal=True, label_visibility="collapsed",
        )

    is_tactique = horizon is None or "Tactique" in (horizon or "")

    opt = load_optimized_weights()
    using_optimized = bool(opt)

    DEFAULT_TACT  = {"P1": 0.35, "P2": 0.20, "P3": 0.25, "P4": 0.15, "P6": 0.05}
    DEFAULT_STRAT = {"P1": 0.35, "P2": 0.40, "P3": 0.07, "P4": 0.03, "P5": 0.15}

    if is_tactique:
        W = opt.get("tactique", DEFAULT_TACT) if using_optimized else DEFAULT_TACT
        NORM = 1.0
        weight_rows = [
            ("🛫 P1 — Programmes de vols",     f"{W.get('P1',0)*100:.0f} %", "Vols confirmés"),
            ("🏨 P3 — Disponibilité hôtelière", f"{W.get('P3',0)*100:.0f} %", "Signal 2-4 sem."),
            ("📅 P2 — Calendriers scolaires",   f"{W.get('P2',0)*100:.0f} %", "Superposition marchés"),
            ("📈 P4 — Google Trends",           f"{W.get('P4',0)*100:.0f} %", "Intention de voyage"),
            ("🌤 P6 — Météo prévue",            f"{W.get('P6',0)*100:.0f} %", "Open-Meteo live"),
        ]
    else:
        W = opt.get("strategique", DEFAULT_STRAT) if using_optimized else DEFAULT_STRAT
        NORM = 1.0
        weight_rows = [
            ("📅 P2 — Calendriers scolaires",   f"{W.get('P2',0)*100:.0f} %", "Le socle — 1 an à l'avance"),
            ("🛫 P1 — Programmes de vols",      f"{W.get('P1',0)*100:.0f} %", "Capacités planifiées"),
            ("📊 P5 — Saisonnalité historique", f"{W.get('P5',0)*100:.0f} %", "Tendance ADP 2022-2024"),
            ("🏨 P3 — Disponibilité hôtelière", f"{W.get('P3',0)*100:.0f} %", "Signal court terme"),
            ("📈 P4 — Google Trends",           f"{W.get('P4',0)*100:.0f} %", "Intention à long terme"),
        ]

    # Banner auto-calibration
    if using_optimized:
        horizon_key = "tactique" if is_tactique else "strategique"
        mape_before = opt.get(f"mape_{horizon_key}_avant", "?")
        mape_after  = opt.get(f"mape_{horizon_key}_apres", "?")
        nb_sem      = opt.get("nb_semaines_reelles", "?")
        st.success(
            f"✅ **Poids auto-calibrés** sur {nb_sem} semaines réelles — "
            f"MAPE {mape_before}% → **{mape_after}%** "
            f"(−{opt.get(f'gain_{horizon_key}_pts','?')} pts)  "
            f"| _Mis à jour : {opt.get('derniere_optimisation','?')}_"
        )
    else:
        st.info("ℹ️ Poids par défaut (document de cadrage). Importez des données réelles dans l'onglet **📥 Import Réel** pour calibrer automatiquement.")

    with st.expander("📐 Pondération appliquée (document de cadrage OzeRoute)", expanded=False):
        st.dataframe(
            pd.DataFrame(weight_rows, columns=["Facteur", "Poids", "Justification"]),
            use_container_width=True, hide_index=True,
        )

    # ── Consolidation per week ───────────────────────────────────────────
    if df2_raw is None or df2_raw.empty:
        st.warning("Lancez le pipeline pour générer les données (base de calcul : P2).")
    else:
        p1_score = 0.70 if (df1 is not None and not df1.empty) else 0.0

        def _signal_label(idx):
            if idx >= 80: return "Pic de demande",   "#e74c3c", "Activer capacité maximale — recruter chauffeurs temporaires"
            if idx >= 65: return "Demande forte",    "#e67e22", "Renforcer la flotte — demande confirmée"
            if idx >= 50: return "Demande active",   "#f1c40f", "Niveau nominal — surveiller l'évolution"
            if idx >= 30: return "Demande modérée",  "#3498db", "Pas d'action immédiate — préparer la montée"
            return              "Hors saison",       "#95a5a6", "Creux — campagnes promotionnelles possibles"

        rows_s = []
        for _, row in df2_raw.iterrows():
            lbl = row["label_semaine"]
            p2 = float(row["index_superposition"])

            p3 = 0.0
            if df3 is not None and not df3.empty:
                m3 = df3[df3["label_semaine"] == lbl]["taux_occupation_estime"]
                if len(m3): p3 = float(m3.mean())

            p4 = 0.0
            if df4_synth is not None and not df4_synth.empty:
                m4 = df4_synth[df4_synth["label_semaine"] == lbl]["trends_index"]
                if len(m4): p4 = float(m4.iloc[0]) / 100.0

            # P5 — saisonnalité (stratégique)
            p5 = 0.0
            if df5 is not None and not df5.empty:
                m5 = df5[df5["label_semaine"] == lbl]["saison_index"]
                if len(m5): p5 = float(m5.iloc[0])

            # P6 — météo (tactique) — average impact across airports, shifted to [0,1]
            p6 = 0.5
            if df6 is not None and not df6.empty:
                m6 = df6[df6["label_semaine"] == lbl]["meteo_impact"]
                if len(m6):
                    p6 = float(m6.mean())   # [-0.15, +0.15]
                    p6 = (p6 + 0.15) / 0.30  # normalize to [0, 1]

            raw = (W["P1"] * p1_score
                 + W["P2"] * p2
                 + W["P3"] * p3
                 + W["P4"] * p4
                 + W.get("P5", 0) * p5
                 + W.get("P6", 0) * p6)
            idx = round(min(raw / NORM * 100, 100), 1)
            signal, color, reco = _signal_label(idx)

            rows_s.append({
                "label_semaine": lbl, "semaine_debut": row["semaine_debut"],
                "index": idx, "signal": signal, "color": color, "reco": reco,
                "p1_pts": round(W["P1"]          * p1_score / NORM * 100, 1),
                "p2_pts": round(W["P2"]          * p2       / NORM * 100, 1),
                "p3_pts": round(W["P3"]          * p3       / NORM * 100, 1),
                "p4_pts": round(W["P4"]          * p4       / NORM * 100, 1),
                "p5_pts": round(W.get("P5", 0)  * p5       / NORM * 100, 1),
                "p6_pts": round(W.get("P6", 0)  * p6       / NORM * 100, 1),
            })

        df_cs = pd.DataFrame(rows_s)

        # Apply date filter
        if date_range and len(date_range) == 2:
            s, e = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
            df_cs = df_cs[(df_cs["semaine_debut"] >= s) & (df_cs["semaine_debut"] <= e)]

        if df_cs.empty:
            st.warning("Aucune semaine dans la période sélectionnée.")
        else:
            # KPIs
            cs1, cs2, cs3, cs4 = st.columns(4)
            cs1.metric("Indice moyen",       f"{df_cs['index'].mean():.0f} / 100")
            cs2.metric("Semaines Pic 🔴",    len(df_cs[df_cs['signal']=="Pic de demande"]))
            cs3.metric("Semaines Fortes 🟠", len(df_cs[df_cs['signal']=="Demande forte"]))
            cs4.metric("Semaines Creuses ⚪",len(df_cs[df_cs['signal']=="Hors saison"]))

            # Index bar chart
            fig_cs = go.Figure()
            fig_cs.add_hrect(y0=80, y1=105, fillcolor="rgba(231,76,60,0.07)",  line_width=0)
            fig_cs.add_hrect(y0=65, y1=80,  fillcolor="rgba(230,126,34,0.07)", line_width=0)
            fig_cs.add_hrect(y0=50, y1=65,  fillcolor="rgba(241,196,15,0.07)", line_width=0)
            fig_cs.add_trace(go.Bar(
                x=df_cs["label_semaine"], y=df_cs["index"],
                marker_color=df_cs["color"].tolist(),
                text=df_cs["index"].apply(lambda v: f"{v:.0f}"),
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Indice : %{y:.1f}/100<extra></extra>",
            ))
            for lvl, col, lbl in [(80,"#e74c3c","Pic≥80"), (65,"#e67e22","Fort≥65"), (50,"#f1c40f","Actif≥50")]:
                fig_cs.add_hline(y=lvl, line_dash="dot", line_color=col, line_width=1,
                                 annotation_text=lbl, annotation_position="top left",
                                 annotation_font_color=col)
            fig_cs.update_layout(**DARK,
                title=f"Indice de demande consolidé — {'Tactique' if is_tactique else 'Stratégique'} (0→100)",
                xaxis_title="Semaine", yaxis=dict(range=[0, 110], title="Indice"),
                showlegend=False, height=420,
            )
            st.plotly_chart(fig_cs, use_container_width=True)

            # Contribution stacked bar
            with st.expander("📊 Contribution de chaque Piste à l'indice"):
                fig_contrib = go.Figure()
                for col_key, color, name in [
                    ("p1_pts","#4f8ef7","P1 — Vols"),
                    ("p2_pts","#2ecc71","P2 — Calendriers"),
                    ("p3_pts","#e67e22","P3 — Hôtels"),
                    ("p4_pts","#9b59b6","P4 — Trends"),
                ]:
                    fig_contrib.add_trace(go.Bar(
                        x=df_cs["label_semaine"], y=df_cs[col_key],
                        name=name, marker_color=color,
                        hovertemplate=f"<b>%{{x}}</b><br>{name} : %{{y:.1f}} pts<extra></extra>",
                    ))
                fig_contrib.update_layout(**DARK, barmode="stack",
                    title="Décomposition de l'indice par Piste",
                    xaxis_title="Semaine", yaxis_title="Points contribués",
                    height=350,
                )
                st.plotly_chart(fig_contrib, use_container_width=True)

            # Recommendations table
            st.subheader("Recommandations opérationnelles semaine par semaine")
            for _, row in df_cs.iterrows():
                c1, c2, c3, c4 = st.columns([2, 1, 2, 5])
                c1.markdown(f"**{row['label_semaine']}**")
                c2.markdown(
                    f'<span style="background:{row["color"]};color:{"#000" if row["signal"] in ("Demande active","Demande modérée") else "#fff"};'
                    f'padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;">'
                    f'{row["index"]:.0f}</span>',
                    unsafe_allow_html=True,
                )
                c3.caption(row["signal"])
                c4.caption(row["reco"])

            # ── Export ──────────────────────────────────────────────────
            st.divider()
            export_df = df_cs[["label_semaine", "index", "signal", "reco",
                                "p1_pts", "p2_pts", "p3_pts", "p4_pts", "p5_pts", "p6_pts"]].copy()
            export_df.columns = ["Semaine", "Indice (0-100)", "Signal", "Recommandation",
                                  "P1 pts", "P2 pts", "P3 pts", "P4 pts", "P5 pts", "P6 pts"]
            horizon_lbl = "Tactique" if is_tactique else "Strategique"
            period_lbl  = f"{date_range[0].strftime('%Y%m%d')}_{date_range[1].strftime('%Y%m%d')}" if date_range else "all"
            fname_base  = f"ozeroute_synthese_{horizon_lbl}_{period_lbl}"

            # ── Excel ────────────────────────────────────────────────
            def _to_excel(df):
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Synthèse")
                    ws = writer.sheets["Synthèse"]
                    # Auto-width columns
                    for col in ws.columns:
                        max_len = max(len(str(cell.value or "")) for cell in col)
                        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)
                return buf.getvalue()

            # ── PDF ──────────────────────────────────────────────────
            def _ascii(text):
                return (str(text)
                    .replace("—", "-").replace("–", "-").replace("→", "->")
                    .replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
                    .replace("à", "a").replace("â", "a").replace("ä", "a")
                    .replace("î", "i").replace("ï", "i")
                    .replace("ô", "o").replace("ö", "o")
                    .replace("û", "u").replace("ù", "u").replace("ü", "u")
                    .replace("ç", "c").replace("ñ", "n")
                    .replace("É", "E").replace("È", "E").replace("Ê", "E")
                    .replace("À", "A").replace("Â", "A")
                    .replace("Î", "I").replace("Ô", "O").replace("Û", "U")
                    .replace("Ç", "C").replace("°", " deg")
                    .replace("✅", "OK").replace("⚠", "!").replace("🔴", "")
                    .replace("🟠", "").replace("🟡", "").replace("🔵", "").replace("⚪", "")
                    .encode("latin-1", errors="replace").decode("latin-1")
                )

            def _to_pdf(df, horizon, period):
                from fpdf import FPDF

                def _header(pdf, cols, widths, bg=(30, 40, 80)):
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_fill_color(*bg)
                    pdf.set_text_color(255, 255, 255)
                    for w, c in zip(widths, cols):
                        pdf.cell(w, 8, c, border=1, fill=True)
                    pdf.ln()
                    pdf.set_font("Helvetica", "", 8)
                    pdf.set_text_color(0, 0, 0)

                pdf = FPDF()
                pdf.add_page()

                # ── Title ────────────────────────────────────────────
                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 10, "OzeRoute - Synthese Predictive", ln=True)
                pdf.set_font("Helvetica", "", 10)
                pdf.cell(0, 7, f"Horizon : {horizon}   |   Periode : {period}", ln=True)
                pdf.ln(4)

                # ── Table 1 : main results ───────────────────────────
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 8, "Resultats par semaine", ln=True)
                cols1   = ["Semaine", "Indice", "Signal", "Recommandation"]
                widths1 = [38, 18, 36, 98]
                _header(pdf, cols1, widths1)
                fill = False
                for _, row in df.iterrows():
                    pdf.set_fill_color(240, 243, 255) if fill else pdf.set_fill_color(255, 255, 255)
                    vals = [_ascii(row["Semaine"]), _ascii(row["Indice (0-100)"]),
                            _ascii(row["Signal"]), _ascii(row["Recommandation"])[:65]]
                    for w, v in zip(widths1, vals):
                        pdf.cell(w, 7, v, border=1, fill=True)
                    pdf.ln()
                    fill = not fill

                # ── Table 2 : piste contributions ────────────────────
                pdf.ln(6)
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(0, 8, "Contribution de chaque Piste (points sur 100)", ln=True)
                cols2   = ["Semaine", "P1 Vols", "P2 Calendriers", "P3 Hotels", "P4 Trends", "P5 Saison", "P6 Meteo", "Total"]
                widths2 = [38, 20, 28, 22, 22, 22, 22, 16]
                _header(pdf, cols2, widths2, bg=(20, 60, 40))
                fill = False
                for _, row in df.iterrows():
                    pdf.set_fill_color(240, 255, 245) if fill else pdf.set_fill_color(255, 255, 255)
                    total = sum(float(row.get(c, 0) or 0)
                                for c in ["P1 pts", "P2 pts", "P3 pts", "P4 pts", "P5 pts", "P6 pts"])
                    vals = [
                        _ascii(row["Semaine"]),
                        str(row.get("P1 pts", 0)),
                        str(row.get("P2 pts", 0)),
                        str(row.get("P3 pts", 0)),
                        str(row.get("P4 pts", 0)),
                        str(row.get("P5 pts", 0)),
                        str(row.get("P6 pts", 0)),
                        str(round(total, 1)),
                    ]
                    for w, v in zip(widths2, vals):
                        pdf.cell(w, 7, v, border=1, fill=True)
                    pdf.ln()
                    fill = not fill

                return bytes(pdf.output())

            exp1, exp2, exp3 = st.columns(3)
            with exp1:
                st.download_button(
                    "⬇️ CSV",
                    data=export_df.to_csv(index=False, encoding="utf-8-sig"),
                    file_name=f"{fname_base}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with exp2:
                st.download_button(
                    "⬇️ Excel",
                    data=_to_excel(export_df),
                    file_name=f"{fname_base}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            with exp3:
                st.download_button(
                    "⬇️ PDF",
                    data=_to_pdf(export_df, horizon_lbl, period_lbl),
                    file_name=f"{fname_base}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )


# ══ TAB 9 — Import Réel & Calibration ════════════════════════════════════
with tab9:
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    from piste7_import.import_commandes import (
        import_from_bytes, generate_demo, generate_template,
        recalibrate, compute_calibration, load_signal as _load_signal,
        load_commandes as _load_cmd_raw, TEMPLATE_FILE, IMPORT_FILE,
    )

    st.markdown(
        "**Mode Shadow — Calibration du modèle.** "
        "Importez vos commandes réelles semaine par semaine pour mesurer la précision "
        "des prédictions et calculer le facteur de conversion *indice → nombre de courses*."
    )

    # ── Section 1 : Import / chargement ────────────────────────────────
    st.subheader("1. Importer les données réelles")

    col_upload, col_demo = st.columns([3, 1])

    with col_upload:
        uploaded = st.file_uploader(
            "Glissez votre CSV de commandes (colonnes : semaine_debut, nb_courses)",
            type=["csv"],
            help="Colonnes obligatoires : semaine_debut (YYYY-MM-DD), nb_courses.\n"
                 "Optionnelles : semaine_fin, segment, aeroport, marche_source, nb_passagers, notes.",
        )
        if uploaded is not None:
            ok, errors = import_from_bytes(uploaded.getvalue(), uploaded.name)
            if errors:
                for e in errors:
                    st.warning(e)
            if ok:
                st.success(f"✅ Fichier «{uploaded.name}» importé — calibration recalculée.")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Import échoué — vérifiez les erreurs ci-dessus.")

    with col_demo:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🎲 Données démo", use_container_width=True,
                     help="Génère des données simulées (bruit ±12 %) basées sur le signal prédit"):
            with st.spinner("Génération…"):
                generate_demo()
            st.cache_data.clear()
            st.success("Données de démonstration générées.")
            st.rerun()

    # Template download
    tpl_path = TEMPLATE_FILE
    if tpl_path.exists() or True:
        if st.button("📄 Générer & télécharger le template CSV", use_container_width=False):
            tpl = generate_template()
            st.cache_data.clear()
        if tpl_path.exists():
            with open(tpl_path, "rb") as _f:
                st.download_button(
                    "⬇ Télécharger template_import_commandes.csv",
                    _f.read(), "template_import_commandes.csv", "text/csv",
                    use_container_width=False,
                )

    st.divider()

    # ── Section 2 : Métriques de calibration ───────────────────────────
    df_cmd = load_commandes()
    calib  = load_calibration()

    if df_cmd is None or df_cmd.empty:
        st.info("Aucune donnée réelle importée — utilisez l'import ci-dessus ou les données démo.")
        st.stop()

    st.subheader("2. Métriques de calibration (mode shadow)")

    nb_cal = calib.get("nb_semaines_calibrees", 0)
    mape   = calib.get("mape")
    mae    = calib.get("mae")
    r2     = calib.get("r2")
    fc     = calib.get("facteur_conversion")
    maj    = calib.get("derniere_mise_a_jour", "—")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Semaines calibrées", nb_cal or "—")
    m2.metric("MAPE",  f"{mape:.1f} %" if mape is not None else "—",
              help="Mean Absolute Percentage Error — erreur relative moyenne")
    m3.metric("MAE",   f"{mae:.0f} courses" if mae is not None else "—",
              help="Mean Absolute Error — écart moyen absolu en nombre de courses")
    m4.metric("R²",    f"{r2:.3f}" if r2 is not None else "—",
              help="Coefficient de détermination — 1.0 = prédiction parfaite")
    m5.metric("Facteur conversion",
              f"{fc:.0f} c/u" if fc is not None else "—",
              help="Courses par unité d'indice (indice 0→1). Exemple : 120 c/u × index 0.8 = 96 courses prévues")

    # Interprétation MAPE
    if mape is not None:
        if mape < 10:
            st.success(f"✅ MAPE {mape:.1f} % — Excellent : le modèle prédit avec une précision de >{100-mape:.0f} %")
        elif mape < 20:
            st.info(f"📊 MAPE {mape:.1f} % — Acceptable : affinez avec plus de semaines réelles")
        elif mape < 35:
            st.warning(f"⚠️ MAPE {mape:.1f} % — Perfectible : vérifiez si des événements exceptionnels faussent le calcul")
        else:
            st.error(f"❌ MAPE {mape:.1f} % — Élevée : le modèle nécessite une recalibration ou des données supplémentaires")

    st.caption(f"Dernière mise à jour : {maj}  |  {calib.get('nb_semaines_total', '—')} semaines dans le fichier")

    # ── Section 2b : Poids optimisés ──────────────────────────────────
    st.subheader("2b. Poids des Pistes — auto-calibration")

    opt_w = load_optimized_weights()

    if not opt_w:
        nb_manquantes = max(0, 6 - (calib.get("nb_semaines_calibrees") or 0))
        st.warning(
            f"⏳ Optimisation non encore disponible — "
            f"il manque **{nb_manquantes} semaine(s)** de données réelles (minimum 6)."
        )
        if st.button("🔄 Forcer la recalibration des poids", disabled=(nb_manquantes > 0)):
            from piste7_import.optimize_weights import run_optimization
            with st.spinner("Optimisation en cours…"):
                run_optimization()
            st.cache_data.clear()
            st.rerun()
    else:
        opt_nb  = opt_w.get("nb_semaines_reelles", "?")
        opt_maj = opt_w.get("derniere_optimisation", "?")

        oc1, oc2 = st.columns(2)

        with oc1:
            st.markdown("**Horizon Tactique (1-4 sem.)**")
            tact = opt_w.get("tactique", {})
            tact_def = opt_w.get("tactique_defaut", {"P1":0.35,"P2":0.20,"P3":0.25,"P4":0.15,"P6":0.05})
            mape_tb = opt_w.get("mape_tactique_avant", "?")
            mape_ta = opt_w.get("mape_tactique_apres", "?")
            gain_t  = opt_w.get("gain_tactique_pts", 0)
            st.markdown(f"MAPE : **{mape_tb}%** → **{mape_ta}%**  (−{gain_t} pts)")
            tact_rows = []
            for piste in ["P1","P2","P3","P4","P6"]:
                before = tact_def.get(piste, 0)
                after  = tact.get(piste, before)
                delta  = round((after - before) * 100, 1)
                arrow  = "▲" if delta > 0.5 else ("▼" if delta < -0.5 else "=")
                tact_rows.append({
                    "Piste": piste,
                    "Avant": f"{before*100:.0f} %",
                    "Après": f"{after*100:.0f} %",
                    "Δ":    f"{arrow} {abs(delta):.1f} pts",
                })
            st.dataframe(pd.DataFrame(tact_rows), hide_index=True, use_container_width=True)

        with oc2:
            st.markdown("**Horizon Stratégique (3-6 mois)**")
            strat = opt_w.get("strategique", {})
            strat_def = opt_w.get("strategique_defaut", {"P1":0.35,"P2":0.40,"P3":0.07,"P4":0.03,"P5":0.15})
            mape_sb = opt_w.get("mape_strategique_avant", "?")
            mape_sa = opt_w.get("mape_strategique_apres", "?")
            gain_s  = opt_w.get("gain_strategique_pts", 0)
            st.markdown(f"MAPE : **{mape_sb}%** → **{mape_sa}%**  (−{gain_s} pts)")
            strat_rows = []
            for piste in ["P1","P2","P3","P4","P5"]:
                before = strat_def.get(piste, 0)
                after  = strat.get(piste, before)
                delta  = round((after - before) * 100, 1)
                arrow  = "▲" if delta > 0.5 else ("▼" if delta < -0.5 else "=")
                strat_rows.append({
                    "Piste": piste,
                    "Avant": f"{before*100:.0f} %",
                    "Après": f"{after*100:.0f} %",
                    "Δ":    f"{arrow} {abs(delta):.1f} pts",
                })
            st.dataframe(pd.DataFrame(strat_rows), hide_index=True, use_container_width=True)

        st.caption(f"Calibré sur {opt_nb} semaines · {opt_maj} · méthode : {opt_w.get('methode_tactique','?')}")

        col_reset, col_recal = st.columns([1, 1])
        if col_recal.button("🔄 Recalibrer maintenant", use_container_width=True):
            from piste7_import.optimize_weights import run_optimization
            with st.spinner("Optimisation en cours…"):
                run_optimization()
            st.cache_data.clear()
            st.success("Poids recalibrés.")
            st.rerun()
        if col_reset.button("↩ Remettre les poids par défaut", use_container_width=True):
            from piste7_import.optimize_weights import reset_to_defaults
            reset_to_defaults()
            st.cache_data.clear()
            st.info("Poids par défaut restaurés.")
            st.rerun()

    st.divider()

    # ── Section 3 : Graphique Prédit vs Réel ───────────────────────────
    st.subheader("3. Prédictions vs Commandes réelles")

    # Rebuild full comparison table inline
    signal_map = _load_signal()
    raw_cmds   = _load_cmd_raw()

    if fc and raw_cmds and signal_map:
        comp_rows = []
        for cmd in raw_cmds:
            sd  = cmd["semaine_debut"]
            sig = signal_map.get(sd)
            if sig is None:
                continue
            pred = sig["signal_consolide"] * fc
            comp_rows.append({
                "semaine_debut":    pd.Timestamp(sd),
                "label_semaine":    pd.Timestamp(sd).strftime("%d %b"),
                "nb_courses":       cmd["nb_courses"],
                "courses_predites": round(pred, 1),
                "signal_consolide": sig["signal_consolide"],
                "intensite":        sig["intensite"],
                "erreur_pct":       round(abs(pred - cmd["nb_courses"]) / cmd["nb_courses"] * 100, 1)
                                    if cmd["nb_courses"] > 0 else None,
                "ecart_signe":      round(pred - cmd["nb_courses"], 1),
            })
        df_comp = pd.DataFrame(comp_rows).sort_values("semaine_debut")

        if not df_comp.empty:
            fig_cmp = go.Figure()
            # Réel
            fig_cmp.add_trace(go.Bar(
                x=df_comp["label_semaine"], y=df_comp["nb_courses"],
                name="Réel", marker_color="#4f8ef7",
                hovertemplate="<b>%{x}</b><br>Réel : %{y} courses<extra></extra>",
            ))
            # Prédit
            fig_cmp.add_trace(go.Scatter(
                x=df_comp["label_semaine"], y=df_comp["courses_predites"],
                name="Prédit", line=dict(color="#e74c3c", width=2.5),
                mode="lines+markers", marker=dict(size=6),
                hovertemplate="<b>%{x}</b><br>Prédit : %{y:.0f} courses<extra></extra>",
            ))
            fig_cmp.update_layout(
                **DARK,
                title="Commandes réelles vs Prédictions du modèle",
                xaxis_title="Semaine",
                yaxis_title="Nombre de courses",
                height=400,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_cmp, use_container_width=True)

            # Erreur par semaine
            with st.expander("📊 Erreur relative semaine par semaine"):
                df_err = df_comp[df_comp["erreur_pct"].notna()].copy()
                colors_err = ["#2ecc71" if v <= 10 else "#f1c40f" if v <= 20 else "#e67e22" if v <= 35 else "#e74c3c"
                              for v in df_err["erreur_pct"]]
                fig_err = go.Figure(go.Bar(
                    x=df_err["label_semaine"], y=df_err["erreur_pct"],
                    marker_color=colors_err,
                    text=df_err["erreur_pct"].apply(lambda v: f"{v:.1f}%"),
                    textposition="outside",
                    hovertemplate="<b>%{x}</b><br>Erreur : %{y:.1f}%<extra></extra>",
                ))
                for lvl, col, lbl in [(10,"#2ecc71","<10 %"), (20,"#f1c40f","<20 %"), (35,"#e67e22","<35 %")]:
                    fig_err.add_hline(y=lvl, line_dash="dot", line_color=col, line_width=1,
                                      annotation_text=lbl, annotation_position="top right",
                                      annotation_font_color=col)
                fig_err.update_layout(**DARK, title="Erreur absolue relative par semaine (%)",
                                      yaxis_title="MAPE contribution (%)", height=320)
                st.plotly_chart(fig_err, use_container_width=True)

            # Écart signé
            with st.expander("↕ Écart signé (sur-estimation / sous-estimation)"):
                colors_ecart = ["#e74c3c" if v > 0 else "#4f8ef7" for v in df_comp["ecart_signe"]]
                fig_ecart = go.Figure(go.Bar(
                    x=df_comp["label_semaine"], y=df_comp["ecart_signe"],
                    marker_color=colors_ecart,
                    hovertemplate="<b>%{x}</b><br>Écart : %{y:+.0f} courses<extra></extra>",
                ))
                fig_ecart.add_hline(y=0, line_color="#ffffff", line_width=1)
                fig_ecart.update_layout(**DARK,
                    title="Écart signé — rouge = sur-estimation, bleu = sous-estimation",
                    yaxis_title="Prédit − Réel (courses)", height=300)
                st.plotly_chart(fig_ecart, use_container_width=True)

    st.divider()

    # ── Section 4 : Tableau détaillé ───────────────────────────────────
    st.subheader("4. Tableau de suivi semaine par semaine")

    if 'df_comp' in dir() and not df_comp.empty:
        display_cols = {
            "label_semaine":    "Semaine",
            "nb_courses":       "Réel (courses)",
            "courses_predites": "Prédit (courses)",
            "erreur_pct":       "Erreur %",
            "ecart_signe":      "Écart (P−R)",
            "intensite":        "Intensité prédite",
        }
        df_disp = df_comp[[c for c in display_cols if c in df_comp.columns]].rename(columns=display_cols)
        st.dataframe(df_disp, use_container_width=True, hide_index=True, height=400)
        st.download_button(
            "⬇ Exporter tableau prédit vs réel",
            df_disp.to_csv(index=False),
            "ozeroute_calibration_detail.csv",
            "text/csv",
        )
    else:
        st.dataframe(df_cmd, use_container_width=True, hide_index=True)

    st.divider()

    # ── Section 5 : Évolution du facteur de conversion ─────────────────
    if fc and raw_cmds and signal_map:
        with st.expander("📈 Évolution du facteur de conversion semaine par semaine"):
            fc_rows = []
            for cmd in sorted(raw_cmds, key=lambda r: r["semaine_debut"]):
                sd  = cmd["semaine_debut"]
                sig = signal_map.get(sd)
                if sig and sig["signal_consolide"] > 0.01 and cmd["nb_courses"] > 0:
                    fc_rows.append({
                        "label": pd.Timestamp(sd).strftime("%d %b"),
                        "facteur": round(cmd["nb_courses"] / sig["signal_consolide"], 1),
                    })
            if fc_rows:
                df_fc = pd.DataFrame(fc_rows)
                fig_fc = go.Figure()
                fig_fc.add_trace(go.Scatter(
                    x=df_fc["label"], y=df_fc["facteur"],
                    mode="lines+markers", line=dict(color="#9b59b6", width=2),
                    marker=dict(size=6),
                    hovertemplate="<b>%{x}</b><br>Facteur : %{y:.0f} c/u<extra></extra>",
                ))
                fig_fc.add_hline(y=fc, line_dash="dot", line_color="#ffffff", line_width=1.5,
                                 annotation_text=f"Médiane : {fc:.0f}", annotation_position="top right")
                fig_fc.update_layout(**DARK,
                    title="Facteur de conversion semaine par semaine (courses / indice-unit)",
                    yaxis_title="Facteur (courses / u)", height=300)
                st.plotly_chart(fig_fc, use_container_width=True)
                st.caption(
                    "Un facteur stable indique que le modèle est bien calibré. "
                    "Une forte variance suggère des événements non capturés par les pistes."
                )

    # ── Section 6 : Mode Shadow — explication ──────────────────────────
    with st.expander("ℹ️ Comment fonctionne le Mode Shadow ?"):
        st.markdown(f"""
**Mode Shadow** : le modèle tourne en parallèle des opérations réelles sans intervenir.
Chaque semaine, vous renseignez le nombre réel de courses, et le système calcule automatiquement :

| Métrique | Signification | Cible |
|----------|--------------|-------|
| **MAPE** | Erreur relative moyenne | < 15 % |
| **MAE**  | Écart moyen en courses  | < 15 courses/sem. |
| **R²**   | Qualité de corrélation  | > 0.80 |
| **Facteur** | courses au pic (indice = 1.0) | Stable sur 4+ sem. |

**Facteur de conversion actuel : {fc:.0f} courses / unité d'indice**
→ Exemple : indice prédit = 0.85 → prédiction = {fc:.0f} × 0.85 = **{round(fc * 0.85):.0f} courses**

**Procédure recommandée :**
1. Lancer le pipeline chaque lundi matin
2. Saisir les courses réelles de la semaine précédente dans le template CSV
3. Importer via cette interface — le MAPE se met à jour automatiquement
4. Après 8 semaines de données, le modèle est considéré **calibré** (facteur stable)
        """)

# ══ TAB 8 — Données brutes ════════════════════════════════════════════════
with tab8:
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
