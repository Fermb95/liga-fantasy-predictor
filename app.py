"""App Streamlit del predictor de LaLiga Fantasy Oficial.

Capa de presentación sobre módulos ya testeados:
  datos (db/ingest) → motor (engine) → recomendador (recommender)
  → estado del equipo (team_state) → alineación (lineup) → mercado (market).

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from src import (account, auth, db, engine, ingest, lineup, market,
                 recommender, team_state)

POS = {1: "POR", 2: "DEF", 3: "MED", 4: "DEL", 5: "ENT"}
SIGNAL_EMOJI = {"CHOLLO": "🟢", "MANTENER": "🟡", "VENDER": "🔴"}

st.set_page_config(page_title="Predictor LaLiga Fantasy", page_icon="⚽",
                   layout="wide", initial_sidebar_state="auto",
                   menu_items={"about": "Predictor de LaLiga Fantasy Oficial · datos oficiales"})

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
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 0.25rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---- Utilidades ----------------------------------------------------------
def fmt_eur(v: float) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f} M€"
    if abs(v) >= 1_000:
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
    return engine.score_players(players, fixtures, engine.Weights(*pesos))


def version_token() -> str:
    conn = db.connect()
    try:
        return db.get_meta(conn, "last_ingest") or "vacio"
    finally:
        conn.close()


def team_name(teams, tid):
    return teams[tid].name if tid in teams else "?"


def scores_to_df(scores, teams, en_plantilla: set[int]) -> pd.DataFrame:
    filas = []
    for s in scores:
        p = s.player
        adv = market.price_advice(s)
        tuyo = p.id in en_plantilla
        filas.append({
            "Señal": SIGNAL_EMOJI.get(s.signal, "") + " " + s.signal,
            "Jugador": p.nickname,
            "Pos": POS.get(p.position_id, "?"),
            "Equipo": team_name(teams, p.team_id),
            "Precio": p.market_value,
            "Score": s.score,
            "Pts esp.": lineup.expected_points(s),
            "Comprar hasta": adv.max_buy,
            "Vender por": adv.sell_ask,
            "Forma": s.forma,
            "Estado": p.status_es,
            "En tu equipo": "✅" if tuyo else "",
        })
    return pd.DataFrame(filas)


# ---- Carga de datos + cabecera ------------------------------------------
version = version_token()
players, fixtures, teams, last_ingest = cargar_datos(version)
players_by_id = {p.id: p for p in players}

c1, c2, c3 = st.columns([6, 3, 2])
with c1:
    st.title("⚽ Predictor LaLiga Fantasy")
    st.caption("Datos oficiales · comprar / vender / ignorar · capitán · once ideal")
with c2:
    st.metric("Jugadores en BD", len(players))
    st.caption(f"🕑 Última actualización: **{hace_cuanto(last_ingest)}**")
with c3:
    st.write("")
    st.write("")
    if st.button("🔄 Actualizar datos", type="primary", use_container_width=True):
        with st.spinner("Descargando datos oficiales…"):
            resumen = ingest.run_ingest()
        st.cache_data.clear()
        st.success(f"✅ {resumen['players']} jugadores, {resumen['fixtures']} partidos")
        st.rerun()

if last_ingest:
    try:
        dias = (dt.datetime.now() - dt.datetime.fromisoformat(last_ingest)).days
        if dias >= 2:
            st.warning(f"Han pasado {dias} días desde la última actualización. "
                       "Pulsa 🔄 tras cada jornada.")
    except ValueError:
        pass

if not players:
    st.info("La base de datos está vacía. Pulsa **🔄 Actualizar datos** para descargarla.")
    st.stop()


# ---- Estado del equipo (persistente) ------------------------------------
conn = db.connect()
roster_ids = team_state.get_roster_ids(conn)
budget_saved = team_state.get_budget(conn)
conn.close()

# ---- Barra lateral: tu situación ----------------------------------------
st.sidebar.header("💼 Tu situación")

budget = st.sidebar.number_input(
    "Dinero disponible (€)", min_value=0, value=int(budget_saved), step=250_000,
    format="%d", key=f"budget_{budget_saved}")
st.sidebar.caption(f"= {fmt_eur(budget)}")

opciones = {f"{p.nickname} · {team_name(teams, p.team_id)} ({POS.get(p.position_id,'?')})": p.id
            for p in sorted(players, key=lambda x: x.nickname)}
id_a_label = {v: k for k, v in opciones.items()}
default_squad = [id_a_label[i] for i in roster_ids if i in id_a_label]
sel = st.sidebar.multiselect(
    "Tu plantilla", list(opciones.keys()), default=default_squad,
    key=f"squad_{hash(frozenset(roster_ids))}",
    help="Selecciónala una vez y pulsa Guardar. Se recuerda entre sesiones.")
sel_ids = {opciones[s] for s in sel}

if st.sidebar.button("💾 Guardar plantilla y presupuesto", use_container_width=True):
    c = db.connect()
    team_state.set_roster(c, sel_ids)
    team_state.set_budget(c, budget)
    c.close()
    st.sidebar.success("Guardado ✅")
    st.rerun()

# La plantilla "oficial" para el análisis es la guardada; si aún no has guardado,
# se usa lo que tengas seleccionado.
squad_ids = roster_ids if roster_ids else sel_ids

with st.sidebar.expander("⚙️ Ajustar pesos del análisis"):
    w_rent = st.slider("Rentabilidad (pts/M€)", 0.0, 1.0, 0.30, 0.05)
    w_forma = st.slider("Forma reciente", 0.0, 1.0, 0.30, 0.05)
    w_titu = st.slider("Titularidad", 0.0, 1.0, 0.20, 0.05)
    w_cal = st.slider("Calendario", 0.0, 1.0, 0.20, 0.05)
pesos = (w_rent, w_forma, w_titu, w_cal)
if sum(pesos) == 0:
    pesos = (0.30, 0.30, 0.20, 0.20)

with st.sidebar.expander("🔐 Cuenta oficial (email y contraseña)"):
    st.caption("Solo si tu cuenta tiene contraseña propia. Con Google no es posible "
               "por restricciones de LaLiga (ver README).")
    with st.form("login"):
        email = st.text_input("Email")
        pwd = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Iniciar sesión") and email and pwd:
            try:
                tb = auth.login(email, pwd)
                cl = account.AccountClient(token=tb.access_token)
                ligas = cl.get_leagues()
                if ligas:
                    lg = ligas[0]
                    team = cl.get_team(lg.id, lg.team_id)
                    c = db.connect()
                    team_state.set_roster(c, set(team.player_ids))
                    team_state.set_budget(c, team.money or lg.money)
                    c.close()
                    st.success(f"Cargado de '{lg.name}' ✅")
                    st.rerun()
            except (auth.AuthError, account.AccountError) as e:
                st.error(str(e))

scores = calcular_scores(version, pesos)
score_por_id = {s.player.id: s for s in scores}
squad_scores = [score_por_id[i] for i in squad_ids if i in score_por_id]
rec = recommender.recommend(scores, budget=budget, squad_ids=squad_ids)


# ---- Tarjeta -------------------------------------------------------------
def tarjeta(s):
    p = s.player
    adv = market.price_advice(s)
    st.markdown(
        f"**{p.nickname}** · {POS.get(p.position_id,'?')} · {team_name(teams, p.team_id)}  \n"
        f"💰 {fmt_eur(p.market_value)} · ⭐ **{s.score}** · 📈 {s.forma} · {p.status_es}  \n"
        f"🛒 comprar hasta **{fmt_eur(adv.max_buy)}** · 🏷️ vender por **{fmt_eur(adv.sell_ask)}**")


# ---- Pestañas ------------------------------------------------------------
tabs = st.tabs(["🎯 Recomendaciones", "🧢 Alineación", "🔎 Fichajes",
                "📋 Explorar", "🧮 Tu plantilla"])
tab_rec, tab_11, tab_fich, tab_expl, tab_plant = tabs

# --- Recomendaciones ---
with tab_rec:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader(f"🟢 COMPRAR ({len(rec.comprar)})")
        st.caption("Rinden y caben en tu presupuesto")
        if not rec.comprar:
            st.write("_Sube tu presupuesto o actualiza datos._")
        for s in rec.comprar:
            tarjeta(s); st.divider()
    with col2:
        st.subheader(f"🔴 VENDER ({len(rec.vender)})")
        st.caption("De tu plantilla: lesión, bajón o poco valor")
        if not rec.vender:
            st.write("_Guarda tu plantilla para ver qué soltar._")
        for s in rec.vender:
            tarjeta(s); st.divider()
    with col3:
        st.subheader(f"⚪ IGNORAR ({len(rec.ignorar)})")
        st.caption("Caros que NO están rindiendo")
        for s in rec.ignorar:
            tarjeta(s); st.divider()

# --- Alineación (capitán + once ideal) ---
with tab_11:
    st.subheader("Tu mejor alineación para la próxima jornada")
    if not squad_scores:
        st.info("Guarda tu plantilla en la barra lateral para calcular tu once.")
    else:
        res = lineup.optimal_lineup(squad_scores)
        cap = lineup.best_captain(squad_scores)
        if cap:
            st.success(f"🧢 **Capitán recomendado: {cap.player.nickname}** "
                       f"({POS.get(cap.player.position_id,'?')}) · "
                       f"{lineup.expected_points(cap)} pts esperados (¡doblan!)")
        if res is None:
            st.warning("No hay jugadores suficientes (¿falta portero?) para un once completo. "
                       "Aun así tienes arriba tu capitán recomendado.")
        else:
            d, m, f = res.formation
            st.caption(f"Formación óptima **{d}-{m}-{f}** · "
                       f"{res.total_expected} pts esperados (capitán incluido)")

            def fila_xi(s):
                es_cap = res.captain and s.player.id == res.captain.player.id
                return {
                    "": "🧢" if es_cap else "",
                    "Jugador": s.player.nickname,
                    "Pos": POS.get(s.player.position_id, "?"),
                    "Equipo": team_name(teams, s.player.team_id),
                    "Pts esp.": lineup.expected_points(s),
                    "Estado": s.player.status_es,
                }
            orden = {1: 0, 2: 1, 3: 2, 4: 3}
            xi_sorted = sorted(res.xi, key=lambda s: orden.get(s.player.position_id, 9))
            st.markdown("**Once titular**")
            st.dataframe(pd.DataFrame([fila_xi(s) for s in xi_sorted]),
                         use_container_width=True, hide_index=True)
            if res.bench:
                st.markdown("**Suplentes**")
                st.dataframe(pd.DataFrame([fila_xi(s) for s in res.bench]),
                             use_container_width=True, hide_index=True)

# --- Fichajes (simulador) ---
with tab_fich:
    st.subheader("Simulador de fichaje")
    st.caption("Elige a quién quieres fichar y te digo si te llega, a quién vender y qué cláusula poner.")
    fuera = [s for s in scores if s.player.id not in squad_ids
             and s.player.status not in ("out_of_league",)]
    fuera.sort(key=lambda s: s.player.market_value, reverse=True)
    opts = {f"{s.player.nickname} · {team_name(teams, s.player.team_id)} "
            f"({POS.get(s.player.position_id,'?')}) — {fmt_eur(s.player.market_value)}": s
            for s in fuera}
    elegido = st.selectbox("Jugador objetivo", ["—"] + list(opts.keys()))
    if elegido != "—":
        target = opts[elegido]
        plan = market.financing_plan(target, budget, squad_scores)
        adv = market.price_advice(target)
        a, b, c = st.columns(3)
        a.metric("Precio (puja máx.)", fmt_eur(plan.price))
        b.metric("Tu dinero", fmt_eur(budget))
        c.metric("Cláusula a ponerle", fmt_eur(adv.suggested_clause))
        if plan.affordable_now:
            st.success(f"✅ Puedes ficharlo directamente. Te quedarían "
                       f"**{fmt_eur(plan.budget_after)}**.")
        elif plan.feasible:
            nombres = ", ".join(f"{s.player.nickname} (~{fmt_eur(market.price_advice(s).fair_value)})"
                                for s in plan.sells)
            st.warning(f"Te faltan **{fmt_eur(plan.shortfall)}**. "
                       f"Vende para financiarlo: **{nombres}**. "
                       f"Después te quedarían {fmt_eur(plan.budget_after)}.")
        else:
            st.error(f"No te llega ni vendiendo tu plantilla (te faltarían "
                     f"{fmt_eur(plan.price - (budget + sum(market.price_advice(s).fair_value for s in plan.sells)))}).")

        st.markdown("**Registrar este fichaje** (actualiza tu plantilla y tu dinero):")
        precio_real = st.number_input("Precio pagado", min_value=0, value=int(plan.price),
                                      step=100_000, format="%d")
        clausula = st.number_input("Cláusula que le pones (opcional)", min_value=0,
                                   value=int(adv.suggested_clause), step=100_000, format="%d")
        if st.button("✅ Registrar compra", type="primary"):
            c = db.connect()
            nuevo = team_state.buy_player(c, target.player.id, precio_real, clause=clausula or None)
            c.close()
            st.success(f"Fichado {target.player.nickname}. Dinero restante: {fmt_eur(nuevo)}")
            st.rerun()

# --- Explorar ---
with tab_expl:
    st.subheader("Explorar todos los jugadores")
    f1, f2, f3, f4 = st.columns(4)
    pos_sel = f1.multiselect("Posición", list(POS.values()))
    precio_max = f2.slider("Precio máximo (M€)", 0, 150, 150)
    solo_ok = f3.checkbox("Solo disponibles", value=True)
    buscar = f4.text_input("Buscar jugador")

    df = scores_to_df(scores, teams, squad_ids)
    if pos_sel:
        df = df[df["Pos"].isin(pos_sel)]
    df = df[df["Precio"] <= precio_max * 1_000_000]
    if solo_ok:
        df = df[df["Estado"] == "Disponible"]
    if buscar:
        df = df[df["Jugador"].str.contains(buscar, case=False, na=False)]

    df_show = df.sort_values("Score", ascending=False).copy()
    for col in ("Precio", "Comprar hasta", "Vender por"):
        df_show[col] = df_show[col].map(fmt_eur)
    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 column_config={"Score": st.column_config.ProgressColumn(
                     "Score", min_value=0, max_value=100, format="%.0f")})

# --- Tu plantilla ---
with tab_plant:
    st.subheader("Tu plantilla")
    if not squad_scores:
        st.info("Guarda tu plantilla en la barra lateral para analizarla.")
    else:
        valor = sum(s.player.market_value for s in squad_scores)
        m1, m2, m3 = st.columns(3)
        m1.metric("Valor de tu plantilla", fmt_eur(valor))
        m2.metric("Dinero disponible", fmt_eur(budget))
        m3.metric("A vender (aviso)", len(rec.vender))

        filas = []
        for s in sorted(squad_scores, key=lambda x: x.score, reverse=True):
            adv = market.price_advice(s)
            filas.append({
                "Jugador": s.player.nickname,
                "Pos": POS.get(s.player.position_id, "?"),
                "Equipo": team_name(teams, s.player.team_id),
                "Valor": fmt_eur(s.player.market_value),
                "Score": s.score,
                "Pts esp.": lineup.expected_points(s),
                "Vender por": fmt_eur(adv.sell_ask),
                "Cláusula sug.": fmt_eur(adv.suggested_clause),
                "Estado": s.player.status_es,
                "Consejo": "🔴 VENDER" if s in rec.vender else "🟢 Mantener",
            })
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

        st.markdown("**Registrar una venta** (actualiza tu plantilla y tu dinero):")
        vopts = {f"{s.player.nickname} — vender por ~{fmt_eur(market.price_advice(s).sell_ask)}": s
                 for s in squad_scores}
        velegido = st.selectbox("Jugador a vender", ["—"] + list(vopts.keys()))
        if velegido != "—":
            sv = vopts[velegido]
            precio_v = st.number_input("Precio de venta", min_value=0,
                                       value=int(market.price_advice(sv).sell_ask),
                                       step=100_000, format="%d")
            if st.button("🏷️ Registrar venta", type="primary"):
                c = db.connect()
                nuevo = team_state.sell_player(c, sv.player.id, precio_v)
                c.close()
                st.success(f"Vendido {sv.player.nickname}. Dinero: {fmt_eur(nuevo)}")
                st.rerun()
