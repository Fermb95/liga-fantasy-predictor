"""Bloque 3b — App Streamlit del predictor de LaLiga Fantasy Oficial.

Capa fina de presentación sobre módulos ya testeados:
  datos (db/ingest) -> motor (engine) -> recomendador (recommender).

Ejecutar:  streamlit run app.py
Actualizar datos: botón 🔄 dentro de la app (llama a ingest.run_ingest).
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd
import streamlit as st

from src import account, auth, db, engine, ingest, recommender

POS = {1: "POR", 2: "DEF", 3: "MED", 4: "DEL", 5: "ENT"}
SIGNAL_EMOJI = {"CHOLLO": "🟢", "MANTENER": "🟡", "VENDER": "🔴"}

st.set_page_config(page_title="Predictor LaLiga Fantasy", page_icon="⚽",
                   layout="wide", initial_sidebar_state="auto",
                   menu_items={"about": "Predictor de LaLiga Fantasy Oficial · datos oficiales"})

# CSS responsive: móvil cómodo (tipografía, espaciado) y tablas con scroll.
st.markdown(
    """
    <style>
      [data-testid="stDataFrame"] { overflow-x: auto; }
      .stButton > button { border-radius: 10px; }
      @media (max-width: 640px) {
        .block-container { padding: 1.1rem 0.8rem 3rem 0.8rem; }
        h1 { font-size: 1.7rem !important; line-height: 1.15; }
        h2 { font-size: 1.25rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.6rem; }
        /* Pestañas legibles y deslizables en móvil */
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 0.25rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---- Utilidades ----------------------------------------------------------
def fmt_eur(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f} M€"
    if v >= 1_000:
        return f"{v/1_000:.0f} k€"
    return f"{v:.0f} €"


def hace_cuanto(iso: str | None) -> str:
    if not iso:
        return "nunca"
    try:
        t = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    delta = dt.datetime.now() - t
    horas = delta.total_seconds() / 3600
    if horas < 1:
        return f"hace {int(delta.total_seconds()/60)} min"
    if horas < 24:
        return f"hace {int(horas)} h"
    return f"hace {int(horas/24)} días"


@st.cache_data(show_spinner=False)
def cargar_datos(version: str):
    """Carga jugadores/calendario/equipos. Cacheado por marca de última ingesta."""
    conn = db.connect()
    try:
        players = db.get_players(conn)
        fixtures = db.get_fixtures(conn)
        teams = {t.id: t for t in db.get_teams(conn)}
        last = db.get_meta(conn, "last_ingest")
    finally:
        conn.close()
    return players, fixtures, teams, last


@st.cache_data(show_spinner=False)
def calcular_scores(version: str, pesos: tuple[float, float, float, float]):
    players, fixtures, _teams, _last = cargar_datos(version)
    w = engine.Weights(*pesos)
    return engine.score_players(players, fixtures, w)


def version_token() -> str:
    conn = db.connect()
    try:
        return db.get_meta(conn, "last_ingest") or "vacio"
    finally:
        conn.close()


def scores_to_df(scores, teams) -> pd.DataFrame:
    filas = []
    for s in scores:
        p = s.player
        filas.append({
            "Señal": SIGNAL_EMOJI.get(s.signal, "") + " " + s.signal,
            "Jugador": p.nickname,
            "Pos": POS.get(p.position_id, "?"),
            "Equipo": teams[p.team_id].name if p.team_id in teams else "?",
            "Precio": p.market_value,
            "Score": s.score,
            "Forma": s.forma,
            "Pts/M€": s.rentabilidad,
            "Titular": round(s.titularidad * 100),
            "Calendario": round(s.facilidad_calendario * 100),
            "Estado": p.status_es,
        })
    return pd.DataFrame(filas)


# ---- Cabecera + botón de actualización -----------------------------------
version = version_token()
players, fixtures, teams, last_ingest = cargar_datos(version)

c1, c2, c3 = st.columns([6, 3, 2])
with c1:
    st.title("⚽ Predictor LaLiga Fantasy")
    st.caption("Datos oficiales de LaLiga Fantasy · comprar / vender / ignorar")
with c2:
    st.metric("Jugadores en BD", len(players))
    st.caption(f"🕑 Última actualización: **{hace_cuanto(last_ingest)}**")
with c3:
    st.write("")
    st.write("")
    if st.button("🔄 Actualizar datos", type="primary", use_container_width=True):
        with st.spinner("Descargando datos oficiales (jugadores + calendario)…"):
            resumen = ingest.run_ingest()
        st.cache_data.clear()
        st.success(f"✅ {resumen['players']} jugadores, {resumen['fixtures']} partidos")
        st.rerun()

# Aviso si los datos están viejos.
if last_ingest:
    try:
        dias = (dt.datetime.now() - dt.datetime.fromisoformat(last_ingest)).days
        if dias >= 2:
            st.warning(f"Han pasado {dias} días desde la última actualización. "
                       "Pulsa 🔄 tras cada jornada para tener precios y puntos al día.")
    except ValueError:
        pass

if not players:
    st.info("La base de datos está vacía. Pulsa **🔄 Actualizar datos** para descargar "
            "los datos oficiales por primera vez.")
    st.stop()


# ---- Barra lateral: cuenta oficial (opcional) ----------------------------
def token_provider() -> str:
    tb: auth.TokenBundle = st.session_state["token"]
    if tb.is_expired and tb.refresh_token:
        tb = auth.refresh(tb.refresh_token)
        st.session_state["token"] = tb
    return tb.access_token


st.sidebar.header("🔐 Cuenta oficial")
conectado = "token" in st.session_state
mercado_liga = None  # entradas del mercado de tu liga (si estás conectado)

if not conectado:
    st.sidebar.caption("Conéctate para cargar tu dinero, tu plantilla y el mercado "
                       "de tu liga automáticamente. Tu contraseña va solo a LaLiga.")
    with st.sidebar.form("login"):
        email = st.text_input("Email de LaLiga Fantasy")
        pwd = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Iniciar sesión", use_container_width=True)
    if entrar:
        try:
            st.session_state["token"] = auth.login(email, pwd)
            st.rerun()
        except auth.AuthError as e:
            st.sidebar.error(str(e))
    with st.sidebar.expander("¿Entras con Google? Pega tu token"):
        st.caption("Inicia sesión en la web oficial, abre las herramientas de "
                   "desarrollador (F12) → Network → copia el token 'Bearer'.")
        tok = st.text_area("Bearer token", height=80)
        if st.button("Usar token") and tok.strip():
            st.session_state["token"] = auth.TokenBundle(tok.strip(), None, time.time() + 3300)
            st.rerun()
else:
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        for k in ("token", "leagues", "league_key", "my_team", "my_market"):
            st.session_state.pop(k, None)
        st.rerun()

# Datos personales si hay sesión.
presupuesto_auto = None
squad_auto: set[int] = set()
if conectado:
    try:
        client = account.AccountClient(token_provider=token_provider)
        if "leagues" not in st.session_state:
            st.session_state["leagues"] = client.get_leagues()
        ligas = st.session_state["leagues"]
        if not ligas:
            st.sidebar.warning("No se han encontrado ligas en tu cuenta.")
        else:
            nombres = {f"{lg.name} ({lg.managers} mánagers)": lg for lg in ligas}
            elegido = st.sidebar.selectbox("Tu liga", list(nombres.keys()))
            lg = nombres[elegido]
            team = client.get_team(lg.id, lg.team_id)
            mercado_liga = client.get_market(lg.id)
            presupuesto_auto = team.money or lg.money
            squad_auto = set(team.player_ids)
            st.sidebar.success(
                f"✅ {lg.name}\n\n💰 {fmt_eur(presupuesto_auto)} · "
                f"👥 {len(squad_auto)} jugadores · 🛒 {len(mercado_liga)} en mercado")
    except account.AccountError as e:
        st.sidebar.error(str(e))
        st.sidebar.info("Si el error persiste, cierra sesión y vuelve a entrar.")

# ---- Barra lateral: tu situación (manual si no hay sesión) ---------------
st.sidebar.header("💼 Tu situación")

if presupuesto_auto is not None:
    presupuesto = presupuesto_auto
    st.sidebar.metric("Dinero disponible (oficial)", fmt_eur(presupuesto))
else:
    presupuesto = st.sidebar.number_input(
        "Dinero disponible (€)", min_value=0, value=5_000_000, step=500_000, format="%d")
    st.sidebar.caption(f"= {fmt_eur(presupuesto)}")

opciones = {f"{p.nickname} · {teams[p.team_id].name if p.team_id in teams else '?'} "
            f"({POS.get(p.position_id,'?')})": p.id
            for p in sorted(players, key=lambda x: x.nickname)}
etiquetas_por_id = {v: k for k, v in opciones.items()}
default_squad = [etiquetas_por_id[i] for i in squad_auto if i in etiquetas_por_id]
sel = st.sidebar.multiselect(
    "Tu plantilla (los jugadores que tienes)", list(opciones.keys()),
    default=default_squad,
    help="Se autocompleta si te conectas con tu cuenta oficial.")
squad_ids = {opciones[s] for s in sel}

with st.sidebar.expander("⚙️ Ajustar pesos del análisis"):
    w_rent = st.slider("Rentabilidad (pts/M€)", 0.0, 1.0, 0.30, 0.05)
    w_forma = st.slider("Forma reciente", 0.0, 1.0, 0.30, 0.05)
    w_titu = st.slider("Titularidad", 0.0, 1.0, 0.20, 0.05)
    w_cal = st.slider("Calendario", 0.0, 1.0, 0.20, 0.05)

pesos = (w_rent, w_forma, w_titu, w_cal)
if sum(pesos) == 0:
    pesos = (0.30, 0.30, 0.20, 0.20)

scores = calcular_scores(version, pesos)
rec = recommender.recommend(scores, budget=presupuesto, squad_ids=squad_ids)


# ---- Tarjeta de jugador --------------------------------------------------
def tarjeta(s):
    p = s.player
    eq = teams[p.team_id].name if p.team_id in teams else "?"
    st.markdown(
        f"**{p.nickname}**  ·  {POS.get(p.position_id,'?')} · {eq}  \n"
        f"💰 {fmt_eur(p.market_value)}  ·  ⭐ Score **{s.score}**  \n"
        f"📈 Forma {s.forma}  ·  💸 {s.rentabilidad} pts/M€  ·  {p.status_es}")


# ---- Pestañas ------------------------------------------------------------
tab_rec, tab_mercado, tab_expl, tab_plantilla = st.tabs(
    ["🎯 Recomendaciones", "🛒 Mercado de tu liga", "📋 Explorar jugadores", "🧮 Tu plantilla"])

with tab_rec:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader(f"🟢 COMPRAR ({len(rec.comprar)})")
        st.caption("Rinden y caben en tu presupuesto")
        if not rec.comprar:
            st.write("_Sin fichajes dentro de tu presupuesto. Sube el dinero disponible._")
        for s in rec.comprar:
            tarjeta(s); st.divider()
    with col2:
        st.subheader(f"🔴 VENDER ({len(rec.vender)})")
        st.caption("De tu plantilla: lesión, bajón o poco valor")
        if not rec.vender:
            st.write("_Marca tu plantilla en la barra lateral para ver qué soltar._")
        for s in rec.vender:
            tarjeta(s); st.divider()
    with col3:
        st.subheader(f"⚪ IGNORAR ({len(rec.ignorar)})")
        st.caption("Nombres caros que NO están rindiendo")
        for s in rec.ignorar:
            tarjeta(s); st.divider()

with tab_mercado:
    st.subheader("Jugadores en el mercado de tu liga ahora")
    if not conectado:
        st.info("Conéctate con tu cuenta oficial (barra lateral) para ver los "
                "jugadores concretos que tienes hoy en tu mercado y a cuáles pujar.")
    elif not mercado_liga:
        st.write("_No hay jugadores en tu mercado en este momento._")
    else:
        score_por_id = {s.player.id: s for s in scores}
        filas = []
        for m in mercado_liga:
            s = score_por_id.get(m.player_id)
            asequible = m.sale_price <= presupuesto
            if s is None:
                veredicto = "❔ sin datos"
                score_val = None
            elif not asequible:
                veredicto = "⛔ no te llega"
                score_val = s.score
            elif s.score >= 60:
                veredicto = "🟢 PUJA"
                score_val = s.score
            elif s.score <= 35:
                veredicto = "🔴 evita"
                score_val = s.score
            else:
                veredicto = "🟡 dudoso"
                score_val = s.score
            filas.append({
                "Veredicto": veredicto,
                "Jugador": m.nickname,
                "Pos": POS.get(m.position_id, "?"),
                "Precio salida": m.sale_price,
                "Score": score_val if score_val is not None else 0,
                "Forma": s.forma if s else 0,
                "Pujas": m.num_bids,
                "Vende": "Mánager" if m.is_direct_sale else "Sistema",
            })
        dfm = pd.DataFrame(filas).sort_values("Score", ascending=False)
        dfm_show = dfm.copy()
        dfm_show["Precio salida"] = dfm_show["Precio salida"].map(fmt_eur)
        st.dataframe(dfm_show, use_container_width=True, hide_index=True,
                     column_config={"Score": st.column_config.ProgressColumn(
                         "Score", min_value=0, max_value=100, format="%.0f")})
        pujar = dfm[dfm["Veredicto"] == "🟢 PUJA"]
        if not pujar.empty:
            st.success("**Puja recomendada:** " + ", ".join(pujar["Jugador"].tolist()))

with tab_expl:
    st.subheader("Explorar todos los jugadores")
    f1, f2, f3, f4 = st.columns(4)
    pos_sel = f1.multiselect("Posición", list(POS.values()), default=[])
    precio_max = f2.slider("Precio máximo (M€)", 0, 150, 150)
    solo_ok = f3.checkbox("Solo disponibles", value=True)
    buscar = f4.text_input("Buscar jugador")

    df = scores_to_df(scores, teams)
    if pos_sel:
        df = df[df["Pos"].isin(pos_sel)]
    df = df[df["Precio"] <= precio_max * 1_000_000]
    if solo_ok:
        df = df[df["Estado"] == "Disponible"]
    if buscar:
        df = df[df["Jugador"].str.contains(buscar, case=False, na=False)]

    df_show = df.sort_values("Score", ascending=False).copy()
    df_show["Precio"] = df_show["Precio"].map(fmt_eur)
    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 column_config={"Score": st.column_config.ProgressColumn(
                     "Score", min_value=0, max_value=100, format="%.0f")})

with tab_plantilla:
    st.subheader("Análisis de tu plantilla")
    if not squad_ids:
        st.info("Selecciona tu plantilla en la barra lateral para analizarla.")
    else:
        tuyos = [s for s in scores if s.player.id in squad_ids]
        tuyos.sort(key=lambda s: s.score, reverse=True)
        valor_total = sum(s.player.market_value for s in tuyos)
        m1, m2, m3 = st.columns(3)
        m1.metric("Valor de tu plantilla", fmt_eur(valor_total))
        m2.metric("A vender", len(rec.vender))
        m3.metric("Score medio", round(sum(s.score for s in tuyos) / len(tuyos), 1))
        st.dataframe(scores_to_df(tuyos, teams), use_container_width=True, hide_index=True)
