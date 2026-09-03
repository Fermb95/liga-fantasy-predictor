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

from src import (account, advisor, auth, compare, db, engine, ingest, lineup,
                 market, recommender, team_state)

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
active_bids = team_state.get_bids(conn)
active_listings = team_state.get_listings(conn)
conn.close()
mv_by_id = {p.id: p.market_value for p in players}

# ---- Barra lateral: tu situación ----------------------------------------
st.sidebar.header("💼 Tu situación")

opciones = {f"{p.nickname} · {team_name(teams, p.team_id)} ({POS.get(p.position_id,'?')})": p.id
            for p in sorted(players, key=lambda x: x.nickname)}
id_a_label = {v: k for k, v in opciones.items()}
configurado = bool(roster_ids)

if not configurado:
    # ----- Configuración inicial (solo la primera vez) -----
    st.sidebar.info("Carga tu plantilla y tu dinero **una vez**. A partir de ahí, cada "
                    "compra o venta que registres actualiza todo solo.")
    budget = st.sidebar.number_input(
        "Dinero para gastar (€)", min_value=0, value=int(budget_saved or 0),
        step=250_000, format="%d",
        help="El dinero total que te da LaLiga para fichar (antes de restar tus pujas).")
    st.sidebar.caption(f"= {fmt_eur(budget)}")
    sel = st.sidebar.multiselect("Tu plantilla actual", list(opciones.keys()))
    sel_ids = {opciones[s] for s in sel}
    if st.sidebar.button("💾 Guardar configuración inicial", type="primary",
                         use_container_width=True, disabled=not sel_ids):
        c = db.connect()
        team_state.set_roster(c, sel_ids, prices={pid: mv_by_id.get(pid, 0) for pid in sel_ids})
        team_state.set_budget(c, budget)
        c.close()
        st.rerun()
    squad_ids = sel_ids
else:
    # ----- Modo automático: todo se actualiza con tus compras/ventas -----
    budget = budget_saved
    _disp = budget - sum(active_bids.values())
    st.sidebar.metric("💰 Dinero para gastar", fmt_eur(budget))
    st.sidebar.caption(f"✅ Disponible (menos pujas): **{fmt_eur(_disp)}** · "
                       f"👥 {len(roster_ids)} jugadores · se actualiza solo")
    squad_ids = roster_ids

    with st.sidebar.expander("✏️ Corregir plantilla o dinero (manual)"):
        st.caption("Solo para arreglar algo o meter ingresos de LaLiga. El día a día "
                   "se lleva registrando compras/ventas en sus pestañas.")
        default_squad = [id_a_label[i] for i in roster_ids if i in id_a_label]
        sel = st.multiselect("Plantilla", list(opciones.keys()), default=default_squad,
                             key=f"squad_edit_{hash(frozenset(roster_ids))}")
        nb = st.number_input("Dinero para gastar (€)", min_value=0, value=int(budget),
                             step=250_000, format="%d", key=f"budget_edit_{budget}")
        if st.button("Guardar cambios manuales", use_container_width=True):
            c = db.connect()
            team_state.set_roster(c, {opciones[s] for s in sel},
                                  prices={opciones[s]: mv_by_id.get(opciones[s], 0) for s in sel})
            team_state.set_budget(c, nb)
            c.close()
            st.rerun()
        if st.button("🗑️ Reiniciar todo", use_container_width=True):
            c = db.connect()
            team_state.set_roster(c, [])
            team_state.set_budget(c, 0)
            for pid in list(team_state.get_bids(c)):
                team_state.remove_bid(c, pid)
            for pid in list(team_state.get_listings(c)):
                team_state.remove_listing(c, pid)
            c.close()
            st.rerun()

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

# Modelo de dinero (idéntico a LaLiga): para_gastar - pujas = disponible.
valor_plantilla = sum(mv_by_id.get(pid, 0) for pid in squad_ids)
bv = team_state.budget_view(budget, active_bids, valor_plantilla)
disponible = bv.disponible

rec = recommender.recommend(scores, budget=disponible, squad_ids=squad_ids)


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
                "💰 Dinero", "📋 Explorar", "🧮 Tu plantilla"])
tab_rec, tab_11, tab_fich, tab_dinero, tab_expl, tab_plant = tabs

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

# --- Fichajes (asesor de puja) ---
with tab_fich:
    st.subheader("¿Fichar a este jugador?")
    st.caption("Busca al jugador (lo ves en tu mercado de LaLiga) y te digo si es chollo, "
               "hasta cuánto pujar, si te encaja y a quién vender.")
    fuera = [s for s in scores if s.player.id not in squad_ids
             and s.player.status != "out_of_league"]
    fuera.sort(key=lambda s: s.player.market_value, reverse=True)
    opts = {f"{s.player.nickname} · {team_name(teams, s.player.team_id)} "
            f"({POS.get(s.player.position_id,'?')}) — {fmt_eur(s.player.market_value)}": s
            for s in fuera}
    busca = st.text_input("Buscar jugador objetivo")
    lista = [k for k in opts if not busca or busca.lower() in k.lower()]
    elegido = st.selectbox("Jugador", ["—"] + lista)
    if elegido != "—":
        target = opts[elegido]
        adv = market.price_advice(target)
        fit, motivo = advisor.team_fit(target, squad_scores)

        veredicto = {"CHOLLO": "🟢 CHOLLO — fíchalo", "MANTENER": "🟡 Correcto",
                     "VENDER": "🔴 PASA — no rinde"}.get(target.signal, target.signal)
        fit_emoji = {"ENCAJA": "🟢", "MEJORA": "🟢", "NO_ENCAJA": "🟠"}.get(fit, "")
        a, b, c = st.columns(3)
        a.metric("Veredicto", veredicto.split(" ", 1)[0], help=veredicto)
        b.metric("Puja máxima", fmt_eur(adv.max_buy))
        c.metric("Cláusula a ponerle", fmt_eur(adv.suggested_clause))
        st.markdown(f"**Score {target.score}/100** · Pts esperados {lineup.expected_points(target)} · "
                    f"Encaje {fit_emoji} **{fit}** — {motivo}")
        if fit == "NO_ENCAJA":
            st.info("Puede ser buen jugador, pero **ahora mismo no te aporta**: ya vas cubierto "
                    "en esa posición. Fíchalo solo si vendes al que desplaza.")

        st.markdown("---")
        st.markdown("**Simula tu puja:**")
        bid = st.number_input("¿Cuánto vas a pujar?", min_value=0, value=int(adv.max_buy),
                              step=100_000, format="%d")
        if bid > adv.max_buy:
            st.warning(f"Ojo: estás por encima de la puja máxima recomendada ({fmt_eur(adv.max_buy)}).")
        plan = advisor.bid_plan(target, bid, disponible, squad_scores)

        if plan.substitute_out:
            st.write(f"↔️ En su puesto desplazaría a **{plan.substitute_out.player.nickname}** "
                     f"(score {plan.substitute_out.score}).")
        if plan.sell_substitute and plan.substitute_out:
            st.write(f"💡 Conviene **vender a {plan.substitute_out.player.nickname}** "
                     f"(mínimo a aceptar {fmt_eur(advisor.sell_advice(plan.substitute_out).min_accept)}).")
        if plan.extra_sells:
            extra = ", ".join(s.player.nickname for s in plan.extra_sells)
            st.write(f"➕ Aún faltaría dinero: vende además **{extra}**.")

        if plan.feasible:
            st.success(f"✅ Viable. Dinero que te quedaría: **{fmt_eur(plan.cash_final)}**"
                       + ("" if not (plan.sell_substitute or plan.extra_sells) else " (tras esas ventas)"))
        else:
            st.error(f"❌ No te llega ni vendiendo. Te faltarían {fmt_eur(-plan.cash_final)}.")

        st.markdown("**Registrar:**")
        r1, r2 = st.columns(2)
        if r1.button("📌 Anotar puja (dinero retenido)", use_container_width=True):
            c = db.connect(); team_state.add_bid(c, target.player.id, bid); c.close()
            st.success("Puja anotada."); st.rerun()
        clausula = st.number_input("Cláusula al comprarlo", min_value=0,
                                   value=int(adv.suggested_clause), step=100_000, format="%d")
        if r2.button("✅ Registrar compra efectuada", type="primary", use_container_width=True):
            c = db.connect()
            team_state.remove_bid(c, target.player.id)
            nuevo = team_state.buy_player(c, target.player.id, bid, clause=clausula or None)
            c.close()
            st.success(f"Fichado {target.player.nickname}. Dinero: {fmt_eur(nuevo)}")
            st.rerun()

# --- Dinero (escenarios + pujas + ventas) ---
with tab_dinero:
    st.subheader("Tu dinero")
    m1, m2 = st.columns(2)
    m1.metric("💼 Valor de tu plantilla", fmt_eur(bv.valor_plantilla),
              help="Suma del valor de mercado de todos tus jugadores y entrenador.")
    m2.metric("💰 Dinero para gastar", fmt_eur(bv.para_gastar),
              help="El total que te da LaLiga para fichar (lo que pones en la barra lateral).")
    m3, m4 = st.columns(2)
    m3.metric("📌 En pujas", ("− " + fmt_eur(bv.en_pujas)) if bv.en_pujas else "0 €",
              help="Suma de tus pujas activas (dinero retenido).")
    m4.metric("✅ Disponible", fmt_eur(bv.disponible),
              help="Dinero para gastar menos lo que tienes en pujas.")
    if bv.disponible < 0:
        st.warning("Tus pujas superan tu dinero para gastar: revisa importes.")

    st.markdown("### 📌 Pujas activas (dinero retenido)")
    st.caption("Edita la puja si la cambiaste; pulsa ✅ Comprado si te lo llevaste "
               "(entra en tu plantilla y se resta el dinero).")
    if active_bids:
        for pid, amount in active_bids.items():
            nm = players_by_id[pid].nickname if pid in players_by_id else f"#{pid}"
            st.markdown(f"**{nm}**")
            e0, e1, e2, e3 = st.columns([3, 2, 2, 1])
            nuevo = e0.number_input("Puja (€)", min_value=0, value=int(amount), step=100_000,
                                    format="%d", key=f"bidamt_{pid}", label_visibility="collapsed")
            if e1.button("✅ Comprado", key=f"buy_{pid}", use_container_width=True):
                c = db.connect()
                team_state.remove_bid(c, pid)
                team_state.buy_player(c, pid, nuevo)
                c.close(); st.rerun()
            if e2.button("💾 Guardar", key=f"savebid_{pid}", use_container_width=True):
                c = db.connect(); team_state.add_bid(c, pid, nuevo); c.close(); st.rerun()
            if e3.button("🗑️", key=f"delbid_{pid}", use_container_width=True):
                c = db.connect(); team_state.remove_bid(c, pid); c.close(); st.rerun()
            st.divider()
    else:
        st.caption("No tienes pujas anotadas. Anótalas desde la pestaña 🔎 Fichajes.")

    st.markdown("### 🏷️ Jugadores que tienes en venta")
    st.caption("Edita el precio si lo cambiaste; pulsa ✅ Vendido cuando aceptes una "
               "oferta (sale de tu plantilla y se suma el dinero).")
    if active_listings:
        for pid, ask in active_listings.items():
            s = score_por_id.get(pid)
            nm = players_by_id[pid].nickname if pid in players_by_id else f"#{pid}"
            minimo = advisor.sell_advice(s).min_accept if s else 0
            st.markdown(f"**{nm}** · mínimo a aceptar {fmt_eur(minimo)}")
            e0, e1, e2, e3 = st.columns([3, 2, 2, 1])
            nuevo = e0.number_input("Precio (€)", min_value=0, value=int(ask), step=100_000,
                                    format="%d", key=f"askamt_{pid}", label_visibility="collapsed")
            if e1.button("✅ Vendido", key=f"sold_{pid}", use_container_width=True):
                c = db.connect()
                team_state.remove_listing(c, pid)
                team_state.sell_player(c, pid, nuevo)
                c.close(); st.rerun()
            if e2.button("💾 Guardar", key=f"savelist_{pid}", use_container_width=True):
                c = db.connect(); team_state.add_listing(c, pid, nuevo); c.close(); st.rerun()
            if e3.button("🗑️", key=f"dellist_{pid}", use_container_width=True):
                c = db.connect(); team_state.remove_listing(c, pid); c.close(); st.rerun()
            st.divider()
    else:
        st.caption("No tienes jugadores en venta. Ponlos en venta desde la pestaña 🧮 Tu plantilla.")

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

    # ----- Comparador de jugadores -----
    st.markdown("---")
    st.markdown("### 🆚 Comparar jugadores")
    st.caption("Elige varios y los ves en paralelo, ordenados por score.")
    comp_sel = st.multiselect("Jugadores a comparar", list(opciones.keys()), key="cmp_sel")
    if comp_sel:
        comp = [score_por_id[opciones[k]] for k in comp_sel if opciones[k] in score_por_id]
        comp.sort(key=lambda s: s.score, reverse=True)
        mejor = compare.best_of(comp)
        filas = []
        for s in comp:
            adv = market.price_advice(s)
            fit, _ = advisor.team_fit(s, squad_scores)
            filas.append({
                "": "⭐" if mejor and s.player.id == mejor.player.id else "",
                "Jugador": s.player.nickname,
                "Pos": POS.get(s.player.position_id, "?"),
                "Equipo": team_name(teams, s.player.team_id),
                "Precio": fmt_eur(s.player.market_value),
                "Score": s.score,
                "Pts esp.": lineup.expected_points(s),
                "Comprar hasta": fmt_eur(adv.max_buy),
                "Vender por": fmt_eur(adv.sell_ask),
                "Encaje": fit,
                "Veredicto": s.signal,
            })
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

    # ----- Simulador de pujas múltiples -----
    st.markdown("---")
    st.markdown("### 🎰 Simulador: pujar por varios a la vez")
    st.caption("Marca a quién pujarías y con cuánto; te digo si te llega, a quién vender y si compensa.")
    fuera_opts = {k: v for k, v in opciones.items() if v not in squad_ids}
    multi_sel = st.multiselect("Objetivos", list(fuera_opts.keys()), key="multi_sel")
    if multi_sel:
        targets = []
        cols = st.columns(min(3, len(multi_sel)))
        for i, k in enumerate(multi_sel):
            s = score_por_id.get(fuera_opts[k])
            if not s:
                continue
            default = market.price_advice(s).max_buy
            bid = cols[i % len(cols)].number_input(
                f"Puja por {s.player.nickname}", min_value=0, value=int(default),
                step=100_000, format="%d", key=f"mbid_{s.player.id}")
            targets.append((s, int(bid)))
        if targets:
            plan = compare.multi_bid_plan(targets, disponible, squad_scores)
            a, b, c = st.columns(3)
            a.metric("Coste total", fmt_eur(plan.total_cost))
            b.metric("Disponible", fmt_eur(disponible))
            c.metric("Dinero después", fmt_eur(plan.cash_after))
            if plan.affordable:
                st.success("✅ Te llega con tu dinero, sin vender nada.")
            elif plan.feasible:
                nombres = ", ".join(f"{s.player.nickname} (~{fmt_eur(advisor.sell_advice(s).min_accept)})"
                                    for s in plan.sells)
                st.warning(f"Te faltan {fmt_eur(plan.shortfall)}. Para pujar por todos, "
                           f"vende: **{nombres}**.")
            else:
                st.error("❌ No te llega ni vendiendo. Reduce pujas o quita algún objetivo.")

            filas = []
            for te in plan.targets:
                filas.append({
                    "Jugador": te.ps.player.nickname,
                    "Pos": POS.get(te.ps.player.position_id, "?"),
                    "Tu puja": fmt_eur(te.bid),
                    "Máx recom.": fmt_eur(te.max_buy),
                    "Veredicto": te.verdict,
                    "Encaje": te.fit,
                    "¿Merece?": "✅" if te.worth else "🔴",
                })
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
            for n in plan.notes:
                st.caption(f"⚠️ {n}")

# --- Tu plantilla ---
with tab_plant:
    st.subheader("Tu plantilla")
    if not squad_scores:
        st.info("Guarda tu plantilla en la barra lateral para analizarla.")
    else:
        valor = sum(s.player.market_value for s in squad_scores)
        m1, m2, m3 = st.columns(3)
        m1.metric("Valor de tu plantilla", fmt_eur(valor))
        m2.metric("Disponible", fmt_eur(disponible))
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

        st.markdown("**Vender / poner en venta un jugador:**")
        vopts = {f"{s.player.nickname} ({POS.get(s.player.position_id,'?')})": s
                 for s in squad_scores}
        velegido = st.selectbox("Jugador", ["—"] + list(vopts.keys()))
        if velegido != "—":
            sv = vopts[velegido]
            sa = advisor.sell_advice(sv)
            g1, g2 = st.columns(2)
            g1.metric("💚 Buen precio de venta", fmt_eur(sa.good_price))
            g2.metric("🚫 Mínimo a aceptar", fmt_eur(sa.min_accept),
                      help="A ese precio te lo compra el sistema: no aceptes menos de un mánager.")
            precio_v = st.number_input("Precio", min_value=0, value=int(sa.good_price),
                                       step=100_000, format="%d")
            b1, b2 = st.columns(2)
            if b1.button("🏷️ Poner en venta", use_container_width=True):
                c = db.connect(); team_state.add_listing(c, sv.player.id, precio_v); c.close()
                st.success(f"{sv.player.nickname} puesto en venta por {fmt_eur(precio_v)}.")
                st.rerun()
            if b2.button("✅ Registrar venta hecha", type="primary", use_container_width=True):
                c = db.connect()
                team_state.remove_listing(c, sv.player.id)
                nuevo = team_state.sell_player(c, sv.player.id, precio_v)
                c.close()
                st.success(f"Vendido {sv.player.nickname}. Dinero: {fmt_eur(nuevo)}")
                st.rerun()
