"""App Streamlit del predictor de LaLiga Fantasy Oficial.

Capa de presentación sobre módulos ya testeados:
  datos (db/ingest) → motor (engine) → recomendador (recommender)
  → estado del equipo (team_state) → alineación (lineup) → mercado (market).

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import streamlit as st
from streamlit_local_storage import LocalStorage

from src import (account, advisor, auth, compare, db, engine, ingest, lineup,
                 market, mymarket, picks, recommender, team_state, trends, users)

SESSION_LS_KEY = "session_token"

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

# ---- Turso (persistencia en la nube) desde los secrets de Streamlit ------
try:
    for _k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        if not os.environ.get(_k) and _k in st.secrets:
            os.environ[_k] = st.secrets[_k]
except Exception:
    pass


# ---- Login / registro ----------------------------------------------------
localS = LocalStorage()


def _iniciar_sesion(uid_: int, username: str, recordar: bool):
    st.session_state["user_id"] = uid_
    st.session_state["username"] = (username or "").strip().lower()
    if recordar:
        c = db.connect()
        # El token se escribe en el navegador tras el gate (no aquí, para que
        # el componente de localStorage no se corte con el st.rerun()).
        st.session_state["session_token"] = users.create_session(c, uid_)
        c.close()
    st.rerun()


def _login_gate():
    # Auto-login si hay una sesión recordada en el navegador.
    if not st.session_state.get("user_id"):
        tok = localS.getItem(SESSION_LS_KEY)
        if tok:
            c = db.connect()
            uid_ = users.validate_session(c, tok)
            uname = users.get_username(c, uid_) if uid_ else None
            c.close()
            if uid_:
                st.session_state["user_id"] = uid_
                st.session_state["username"] = uname
                st.session_state["session_token"] = tok

    if st.session_state.get("user_id"):
        return

    st.title("⚽ Predictor LaLiga Fantasy")
    st.caption("Entra con tu usuario para ver y gestionar tu equipo.")
    if not db.using_turso():
        st.warning("⚠️ Turso no está configurado: las cuentas no se guardarán entre "
                   "reinicios. Añade los secrets TURSO_DATABASE_URL y TURSO_AUTH_TOKEN.")
    tab_in, tab_up, tab_fg = st.tabs(["Entrar", "Crear cuenta", "¿Olvidaste la contraseña?"])

    with tab_in:
        with st.form("login_form"):
            u = st.text_input("Usuario")
            p = st.text_input("Contraseña", type="password")
            recordar = st.checkbox("Mantener sesión iniciada", value=True)
            if st.form_submit_button("Entrar", type="primary", use_container_width=True):
                c = db.connect()
                uid_ = users.authenticate(c, u, p)
                c.close()
                if uid_:
                    _iniciar_sesion(uid_, u, recordar)
                else:
                    st.error("Usuario o contraseña incorrectos.")

    with tab_up:
        with st.form("signup_form"):
            u2 = st.text_input("Usuario nuevo (3-20 letras/números)", key="su_u")
            p2 = st.text_input("Contraseña (mín. 4)", type="password", key="su_p")
            st.caption("Pregunta de recuperación (por si olvidas la contraseña):")
            rq = st.text_input("Pregunta (p. ej. ¿tu primer equipo?)", key="su_rq")
            ra = st.text_input("Respuesta", key="su_ra")
            recordar2 = st.checkbox("Mantener sesión iniciada", value=True, key="su_rem")
            if st.form_submit_button("Crear cuenta", use_container_width=True):
                if not rq.strip() or not ra.strip():
                    st.error("Pon una pregunta y una respuesta de recuperación.")
                else:
                    try:
                        c = db.connect()
                        uid_ = users.create_user(c, u2, p2, recovery_question=rq,
                                                 recovery_answer=ra)
                        c.close()
                        _iniciar_sesion(uid_, u2, recordar2)
                    except users.UserError as e:
                        st.error(str(e))

    with tab_fg:
        fu = st.text_input("Tu usuario", key="fg_u")
        if st.button("Ver mi pregunta"):
            c = db.connect()
            q = users.get_recovery_question(c, fu)
            c.close()
            st.session_state["fg_q"] = q or ""
            st.session_state["fg_user"] = (fu or "").strip().lower()
        if st.session_state.get("fg_q"):
            st.caption(f"Pregunta: **{st.session_state['fg_q']}**")
            with st.form("forgot_form"):
                ans = st.text_input("Respuesta")
                np1 = st.text_input("Nueva contraseña (mín. 4)", type="password")
                if st.form_submit_button("Restablecer contraseña"):
                    try:
                        c = db.connect()
                        ok = users.reset_password(c, st.session_state["fg_user"], ans, np1)
                        c.close()
                        if ok:
                            st.success("✅ Contraseña cambiada. Ya puedes entrar con la nueva.")
                            st.session_state.pop("fg_q", None)
                        else:
                            st.error("Respuesta incorrecta.")
                    except users.UserError as e:
                        st.error(str(e))
        elif "fg_q" in st.session_state:
            st.info("Ese usuario no tiene pregunta de recuperación, o no existe.")
    st.stop()


_login_gate()
uid = st.session_state["user_id"]

# Escribe el token en el navegador durante el render normal (sin rerun que lo
# corte), para que la sesión se recuerde al recargar.
if st.session_state.get("session_token") and not st.session_state.get("_token_saved"):
    try:
        localS.setItem(SESSION_LS_KEY, st.session_state["session_token"], key="ls_sess_set")
        st.session_state["_token_saved"] = True
    except Exception:
        pass


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
def cargar_tendencias(version: str):
    conn = db.connect()
    try:
        return trends.get_trends(conn)
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def cargar_valor_historico(version: str, player_id: int):
    conn = db.connect()
    try:
        return db.get_value_history(conn, player_id)
    finally:
        conn.close()


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


def _trend_txt(trend_map, pid) -> str:
    t = trend_map.get(pid) if trend_map else None
    if not t or t.direction == "new":
        return ""
    signo = "+" if t.change > 0 else ""
    return f"{t.emoji} {signo}{t.pct:.1f}%"


def scores_to_df(scores, teams, en_plantilla: set[int], trend_map=None) -> pd.DataFrame:
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
            "Tendencia": _trend_txt(trend_map, p.id),
            "Score": s.score,
            "Pts esp.": lineup.expected_points(s),
            "Comprar hasta": adv.max_buy,
            "Vender por": adv.sell_ask,
            "Forma": s.forma,
            "Estado": p.status_es,
            "En tu equipo": "✅" if tuyo else "",
        })
    return pd.DataFrame(filas)


@st.cache_data(show_spinner=False)
def tabla_explorar(version: str, pesos: tuple, squad_key: tuple):
    """Tabla de Explorar cacheada: solo se recalcula si cambian datos, pesos o
    tu plantilla (no en cada interacción)."""
    sc = calcular_scores(version, pesos)
    _, _, teams_, _ = cargar_datos(version)
    return scores_to_df(sc, teams_, set(squad_key), cargar_tendencias(version))


@st.cache_data(show_spinner=False)
def _recomendaciones(version: str, pesos: tuple, disponible: int, squad_key: tuple):
    sc = calcular_scores(version, pesos)
    return recommender.recommend(sc, budget=disponible, squad_ids=set(squad_key))


# ---- Carga de datos + cabecera ------------------------------------------
version = version_token()
players, fixtures, teams, last_ingest = cargar_datos(version)

# Arranque en frío en la nube: la BD de jugadores es efímera, así que si está
# vacía la descargamos sola (sin que tengas que pulsar 🔄).
if not players:
    try:
        with st.spinner("Cargando datos oficiales de LaLiga por primera vez…"):
            ingest.run_ingest()
        st.cache_data.clear()
        version = version_token()
        players, fixtures, teams, last_ingest = cargar_datos(version)
    except Exception:
        pass

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
roster_ids = team_state.get_roster_ids(conn, uid)
budget_saved = team_state.get_budget(conn, uid)
active_bids = team_state.get_bids(conn, uid)
active_listings = team_state.get_listings(conn, uid)
market_ids = team_state.get_market_players(conn, uid)
conn.close()
mv_by_id = {p.id: p.market_value for p in players}

# ---- Barra lateral: usuario ----------------------------------------------
st.sidebar.markdown(f"👤 **{st.session_state.get('username', '')}**")
if st.sidebar.button("Cerrar sesión", use_container_width=True):
    tok = st.session_state.get("session_token")
    if tok:
        c = db.connect()
        users.delete_session(c, tok)
        c.close()
    localS.deleteItem(SESSION_LS_KEY, key="ls_sess_del")
    for k in ("user_id", "username", "session_token"):
        st.session_state.pop(k, None)
    st.rerun()
st.sidebar.divider()

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
        team_state.set_roster(c, uid, sel_ids, prices={pid: mv_by_id.get(pid, 0) for pid in sel_ids})
        team_state.set_budget(c, uid, budget)
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
            team_state.set_roster(c, uid, {opciones[s] for s in sel},
                                  prices={opciones[s]: mv_by_id.get(opciones[s], 0) for s in sel})
            team_state.set_budget(c, uid, nb)
            c.close()
            st.rerun()
        if st.button("🗑️ Reiniciar todo", use_container_width=True):
            c = db.connect()
            team_state.set_roster(c, uid, [])
            team_state.set_budget(c, uid, 0)
            for pid in list(team_state.get_bids(c, uid)):
                team_state.remove_bid(c, uid, pid)
            for pid in list(team_state.get_listings(c, uid)):
                team_state.remove_listing(c, uid, pid)
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
                    team_state.set_roster(c, uid, set(team.player_ids))
                    team_state.set_budget(c, uid, team.money or lg.money)
                    c.close()
                    st.success(f"Cargado de '{lg.name}' ✅")
                    st.rerun()
            except (auth.AuthError, account.AccountError) as e:
                st.error(str(e))

scores = calcular_scores(version, pesos)
score_por_id = {s.player.id: s for s in scores}
squad_scores = [score_por_id[i] for i in squad_ids if i in score_por_id]
tendencias = cargar_tendencias(version)


def next_opp_txt(team_id: int) -> str:
    op = engine.next_opponents(team_id, fixtures, n=1)
    if not op:
        return ""
    rid, es_local, _ = op[0]
    loc = "🏠 vs" if es_local else "✈️ @"
    return f"{loc} {team_name(teams, rid)}"


def proximos_txt(team_id: int, n: int = 3) -> str:
    op = engine.next_opponents(team_id, fixtures, n=n)
    partes = [("🏠" if es_local else "✈️") + team_name(teams, rid)[:10] for rid, es_local, _ in op]
    return " · ".join(partes)


def trend_line(pid: int) -> str:
    t = tendencias.get(pid)
    if not t or t.direction == "new":
        return ""
    signo = "+" if t.change > 0 else ""
    return f"{t.emoji} valor {t.label} ({signo}{t.pct:.1f}%)"

# Mi mercado ahora considera pujas + ventas (rank_market con `listings`).
# Modelo de dinero (idéntico a LaLiga): para_gastar - pujas = disponible.
valor_plantilla = sum(mv_by_id.get(pid, 0) for pid in squad_ids)
bv = team_state.budget_view(budget, active_bids, valor_plantilla)
disponible = bv.disponible

rec = _recomendaciones(version, pesos, disponible, tuple(sorted(squad_ids)))


# ---- Tarjeta -------------------------------------------------------------
def tarjeta(s):
    p = s.player
    adv = market.price_advice(s)
    tl = trend_line(p.id)
    opp = next_opp_txt(p.team_id)
    st.markdown(
        f"**{p.nickname}** · {POS.get(p.position_id,'?')} · {team_name(teams, p.team_id)}  \n"
        f"💰 {fmt_eur(p.market_value)} · ⭐ **{s.score}** · 📈 forma {s.forma} · {p.status_es}  \n"
        f"🛒 comprar hasta **{fmt_eur(adv.max_buy)}** · 🏷️ vender por **{fmt_eur(adv.sell_ask)}**"
        + (f"  \n{tl}" if tl else "")
        + (f"  \n📅 Próximo: {opp}" if opp else ""))


# ---- Navegación (recuerda la sección; no salta al registrar acciones) ----
PAGINAS = ["🎯 Recomendaciones", "🛒 Mi mercado", "🔥 Chollos", "🧢 Alineación",
           "📋 Explorar", "🧮 Tu plantilla", "🔍 Jugador"]
if hasattr(st, "segmented_control"):
    page = st.segmented_control("Sección", PAGINAS, key="nav",
                                label_visibility="collapsed", default=PAGINAS[0]) or PAGINAS[0]
else:
    page = st.radio("Sección", PAGINAS, key="nav", horizontal=True,
                    label_visibility="collapsed")

if page == "🛒 Mi mercado":
    st.subheader("🛒 Mi mercado")
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("💰 Para gastar", fmt_eur(bv.para_gastar))
    b2.metric("📌 En pujas", ("− " + fmt_eur(bv.en_pujas)) if bv.en_pujas else "0 €")
    b3.metric("✅ Disponible", fmt_eur(bv.disponible))
    b4.metric("💼 Valor plantilla", fmt_eur(bv.valor_plantilla))
    if bv.disponible < 0:
        st.warning("Tus pujas superan tu dinero para gastar: revisa importes.")

    modo = st.segmented_control(
        "modo", ["🟢 Comprar", "🔴 Vender", "⏳ En curso"], key="mm_modo",
        label_visibility="collapsed", default="🟢 Comprar") or "🟢 Comprar"
    st.divider()

    # ===================== COMPRAR =====================
    if modo == "🟢 Comprar":
        st.caption("Añade los jugadores que te salen ahora (escribe y selecciona; quítalos "
                   "con la ✕). Te digo a quién pujar y con cuánto.")
        opciones_mm = {f"{p.nickname} · {team_name(teams, p.team_id)} ({POS.get(p.position_id,'?')})": p.id
                       for p in sorted(players, key=lambda x: x.nickname)}
        id_a_label_mm = {v: k for k, v in opciones_mm.items()}
        default_mm = [id_a_label_mm[i] for i in market_ids if i in id_a_label_mm]
        sel_mm = st.multiselect("Tu mercado ahora", list(opciones_mm.keys()),
                                default=default_mm, key="mm_sel", label_visibility="collapsed")
        sel_mm_ids = {opciones_mm[s] for s in sel_mm}
        if sel_mm_ids != market_ids:
            c = db.connect(); team_state.set_market_players(c, uid, sel_mm_ids); c.close()
            market_ids = sel_mm_ids

        if squad_scores:
            _ref = advisor.refuerzos_sugeridos(squad_scores)
            if _ref:
                st.caption("🎯 Dónde te conviene reforzar: **"
                           + ", ".join(advisor.POS_NOMBRE[p] for p in _ref) + "**")

        # Analiza tu mercado + los jugadores por los que YA pujas (para comparar).
        analisis_ids = set(sel_mm_ids) | set(active_bids)
        if not analisis_ids:
            st.info("Aún no has añadido nada. Escribe arriba los jugadores de tu mercado.")
        else:
            bids_dict = {pid: (score_por_id[pid], amt) for pid, amt in active_bids.items()
                         if pid in score_por_id}
            listings_dict = {pid: (score_por_id[pid], ask)
                             for pid, ask in active_listings.items() if pid in score_por_id}
            market_scores = [score_por_id[i] for i in analisis_ids if i in score_por_id]
            ranking = mymarket.rank_market(market_scores, squad_scores, disponible,
                                           tendencias, bids_dict, listings_dict)

            if listings_dict:
                _liquidez = sum(ask for _s, ask in listings_dict.values())
                st.caption(f"💧 Si vendes lo que tienes en venta liberas **{fmt_eur(_liquidez)}** "
                           f"→ tendrías **{fmt_eur(disponible + _liquidez)}** para pujar.")
            fichar = [r for r in ranking if r.verdict == "🟢 Fichar"]
            if fichar:
                st.success("**Compra primero (te llega ya):** " + ", ".join(
                    f"{r.ps.player.nickname} (hasta {fmt_eur(r.max_buy)})" for r in fichar[:3]))

            st.markdown("**Ranking de preferencia** — según análisis del jugador, calendario, "
                        "tu plantilla, tu dinero y tus pujas activas:")
            filas = []
            for r in ranking:
                p = r.ps.player
                afford_txt = {"te_llega": "✅ te llega", "vendiendo": "↔️ vendiendo",
                              "no_te_llega": "⛔ no llega"}[r.afford]
                filas.append({
                    "Prioridad": r.priority,
                    "Estado": r.verdict + (f" ({fmt_eur(r.bid_amount)})" if r.already_bidding else ""),
                    "Jugador": p.nickname,
                    "Pos": POS.get(p.position_id, "?"),
                    "Precio": fmt_eur(p.market_value),
                    "Puja máx": fmt_eur(r.max_buy),
                    "¿Te llega?": afford_txt,
                    "Score": r.ps.score,
                    "Pts esp.": r.expected,
                    "Encaje": r.fit,
                    "Tend.": _trend_txt(tendencias, p.id),
                    "Próximos": proximos_txt(p.team_id),
                    "Aviso": r.note,
                })
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True,
                         column_config={"Prioridad": st.column_config.ProgressColumn(
                             "Prioridad", min_value=0, max_value=100, format="%.0f")})
            st.caption("Estado: 📌 pujando · 🟢 fichar (te llega) · 🟠 sí, pero vende · "
                       "🟡 espera / mejor quédate el tuyo / dudoso · 🔴 pasa · ⛔ no te llega. "
                       "**Espera** = ya pujas por uno mejor en esa posición.")

            # ---- ¿Merece la pena vender lo que tienes listado? ----
            if listings_dict:
                revs = mymarket.review_listings(listings_dict, market_scores, disponible)
                st.markdown("**🏷️ Lo que tienes a la venta** — ¿vender o quedártelo?")
                for rv in revs:
                    p = rv.ps.player
                    st.markdown(
                        f"**{rv.verdict} · {p.nickname}** ({POS.get(p.position_id,'?')}, "
                        f"score {rv.ps.score}) · en venta por {fmt_eur(rv.ask_price)}  \n"
                        f"↳ {rv.note}")
                st.caption("🔁 = en tu mercado hay algo mejor que puedes pagar al venderlo · "
                           "🔒 = nada del mercado lo mejora por ese precio.")
                st.divider()

            st.markdown("**Acción rápida** (pujar / marcar comprado):")
            for r in ranking:
                p = r.ps.player
                extra = ""
                if r.note:
                    extra = f" · ⚠️ {r.note}"
                elif r.afford == "vendiendo":
                    plan = advisor.bid_plan(r.ps, r.max_buy, disponible, squad_scores)
                    vende = [x.player.nickname for x in (
                        ([plan.substitute_out] if plan.sell_substitute and plan.substitute_out else [])
                        + plan.extra_sells)]
                    if vende:
                        extra = " · ↔️ para ficharlo vende: " + ", ".join(vende)
                st.markdown(f"**{r.verdict} · {p.nickname}** ({POS.get(p.position_id,'?')}) · "
                            f"puja máx {fmt_eur(r.max_buy)}{extra}")
                a, b, cc = st.columns([2, 1, 1])
                bid = a.number_input("Tu puja", min_value=0,
                                     value=int(r.bid_amount or r.max_buy), step=100_000,
                                     format="%d", key=f"mmbid_{p.id}", label_visibility="collapsed")
                if b.button("📌 Pujar", key=f"mmpuja_{p.id}", use_container_width=True):
                    c = db.connect(); team_state.add_bid(c, uid, p.id, bid); c.close(); st.rerun()
                if cc.button("✅ Comprado", key=f"mmcomp_{p.id}", use_container_width=True):
                    c = db.connect()
                    team_state.remove_bid(c, uid, p.id)
                    team_state.buy_player(c, uid, p.id, bid)
                    team_state.remove_market_player(c, uid, p.id)
                    c.close(); st.rerun()
                st.divider()

    # ===================== VENDER =====================
    elif modo == "🔴 Vender":
        if not squad_scores:
            st.info("Guarda tu plantilla en la barra lateral para gestionarla.")
        else:
            if rec.vender:
                st.warning("🔴 **Te recomiendo poner en venta** (rinden poco y no son "
                           "imprescindibles): " + ", ".join(s.player.nickname for s in rec.vender))
            if rec.imprescindibles:
                nombres = ", ".join(s.player.nickname for s in squad_scores
                                    if s.player.id in rec.imprescindibles)
                st.info(f"🔒 No vendas a **{nombres}**: te dejarían sin poder formar el once.")
            for s in sorted(squad_scores, key=lambda x: x.score):
                p = s.player
                sa = advisor.sell_advice(s)
                if p.id in rec.imprescindibles:
                    consejo = "🔒 no vender"
                elif s in rec.vender:
                    consejo = "🔴 vender"
                else:
                    consejo = "🟢 mantener"
                marca = " · 🏷️ EN VENTA" if p.id in active_listings else ""
                _t = _trend_txt(tendencias, p.id)
                st.markdown(
                    f"**{p.nickname}** · {POS.get(p.position_id,'?')} · {team_name(teams, p.team_id)} · "
                    f"{fmt_eur(p.market_value)} · {consejo}{marca}  \n"
                    f"Buen precio **{fmt_eur(sa.good_price)}** · mínimo a aceptar {fmt_eur(sa.min_accept)}"
                    + (f" · {_t}" if _t else ""))
                a, b, cc = st.columns([2, 1, 1])
                precio = a.number_input("Precio venta", min_value=0, value=int(sa.good_price),
                                        step=100_000, format="%d", key=f"mmsell_{p.id}",
                                        label_visibility="collapsed")
                if b.button("🏷️ En venta", key=f"mmlist_{p.id}", use_container_width=True):
                    c = db.connect(); team_state.add_listing(c, uid, p.id, precio); c.close(); st.rerun()
                if cc.button("✅ Vendido", key=f"mmsold_{p.id}", use_container_width=True):
                    c = db.connect()
                    team_state.remove_listing(c, uid, p.id)
                    team_state.sell_player(c, uid, p.id, precio)
                    c.close(); st.rerun()
                st.divider()

    # ===================== EN CURSO =====================
    else:
        st.markdown("### 📌 Pujas activas (dinero retenido)")
        if active_bids:
            for pid, amount in active_bids.items():
                nm = players_by_id[pid].nickname if pid in players_by_id else f"#{pid}"
                st.markdown(f"**{nm}**")
                e0, e1, e2, e3 = st.columns([3, 2, 2, 1])
                nuevo = e0.number_input("Puja (€)", min_value=0, value=int(amount), step=100_000,
                                        format="%d", key=f"encbid_{pid}", label_visibility="collapsed")
                if e1.button("✅ Comprado", key=f"encbuy_{pid}", use_container_width=True):
                    c = db.connect(); team_state.remove_bid(c, uid, pid)
                    team_state.buy_player(c, uid, pid, nuevo); c.close(); st.rerun()
                if e2.button("💾 Guardar", key=f"encsavebid_{pid}", use_container_width=True):
                    c = db.connect(); team_state.add_bid(c, uid, pid, nuevo); c.close(); st.rerun()
                if e3.button("🗑️", key=f"encdelbid_{pid}", use_container_width=True):
                    c = db.connect(); team_state.remove_bid(c, uid, pid); c.close(); st.rerun()
                st.divider()
        else:
            st.caption("No tienes pujas anotadas. Anótalas en 🟢 Comprar.")

        st.markdown("### 🏷️ Jugadores que tienes en venta")
        if active_listings:
            for pid, ask in active_listings.items():
                s = score_por_id.get(pid)
                nm = players_by_id[pid].nickname if pid in players_by_id else f"#{pid}"
                minimo = advisor.sell_advice(s).min_accept if s else 0
                st.markdown(f"**{nm}** · mínimo a aceptar {fmt_eur(minimo)}")
                e0, e1, e2, e3 = st.columns([3, 2, 2, 1])
                nuevo = e0.number_input("Precio (€)", min_value=0, value=int(ask), step=100_000,
                                        format="%d", key=f"enclist_{pid}", label_visibility="collapsed")
                if e1.button("✅ Vendido", key=f"encsold_{pid}", use_container_width=True):
                    c = db.connect(); team_state.remove_listing(c, uid, pid)
                    team_state.sell_player(c, uid, pid, nuevo); c.close(); st.rerun()
                if e2.button("💾 Guardar", key=f"encsavelist_{pid}", use_container_width=True):
                    c = db.connect(); team_state.add_listing(c, uid, pid, nuevo); c.close(); st.rerun()
                if e3.button("🗑️", key=f"encdellist_{pid}", use_container_width=True):
                    c = db.connect(); team_state.remove_listing(c, uid, pid); c.close(); st.rerun()
                st.divider()
        else:
            st.caption("No tienes jugadores en venta. Ponlos en venta en 🔴 Vender.")

if page == "🔥 Chollos":
    st.subheader("🔥 Chollos de la jornada")
    st.caption("Los que más puntos esperados dan por cada millón de euros, para "
               "reforzar barato de cara a la próxima jornada.")
    cc1, cc2 = st.columns(2)
    precio_ch = cc1.slider("Precio máximo (M€)", 1, 50, 10, key="chollo_precio")
    pos_ch = cc2.selectbox("Posición", ["Todas", "POR", "DEF", "MED", "DEL"], key="chollo_pos")
    pos_id = {"POR": 1, "DEF": 2, "MED": 3, "DEL": 4}.get(pos_ch)
    lista = picks.chollos_jornada(scores, max_price=precio_ch * 1_000_000,
                                  position_id=pos_id, n=15)
    if not lista:
        st.write("_No hay chollos con esos filtros._")
    filas = []
    for s in lista:
        p = s.player
        filas.append({
            "Jugador": p.nickname,
            "Pos": POS.get(p.position_id, "?"),
            "Equipo": team_name(teams, p.team_id),
            "Precio": fmt_eur(p.market_value),
            "Pts esp.": lineup.expected_points(s),
            "Pts/M€": round(picks.value_per_million(s), 2),
            "Tendencia": _trend_txt(tendencias, p.id),
            "Próximo rival": next_opp_txt(p.team_id),
        })
    if filas:
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

# --- Recomendaciones ---
if page == "🎯 Recomendaciones":
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
if page == "🧢 Alineación":
    _no_jugadas = [f.week for f in fixtures if f.match_state != engine.MATCH_FINISHED]
    proxima_j = min(_no_jugadas) if _no_jugadas else "?"
    st.subheader(f"Tu mejor alineación para la jornada {proxima_j}")
    st.caption("Calculada por puntos esperados de cada jugador: forma reciente × "
               "dificultad del rival de esta jornada × disponibilidad.")
    if not squad_scores:
        st.info("Guarda tu plantilla en la barra lateral para calcular tu once.")
    else:
        res = lineup.optimal_lineup(squad_scores)
        cap = lineup.best_captain(squad_scores)
        coach = lineup.best_coach(squad_scores)
        cc1, cc2 = st.columns(2)
        if cap:
            cc1.success(f"🧢 **Capitán: {cap.player.nickname}**\n\n"
                        f"{POS.get(cap.player.position_id,'?')} · "
                        f"{lineup.expected_points(cap)} pts esp. (¡doblan!)")
        if coach:
            cc2.info(f"👔 **Entrenador: {coach.player.nickname}**\n\n"
                     f"{lineup.expected_points(coach)} pts esperados")
        if res is None:
            st.warning("No hay jugadores suficientes (¿falta portero?) para un once completo. "
                       "Aun así tienes arriba tu capitán y entrenador recomendados.")
        else:
            d, m, f = res.formation
            st.caption(f"Formación óptima **{d}-{m}-{f}** · "
                       f"{res.total_expected} pts esperados (capitán y entrenador incluidos)")

            def fila_xi(s):
                es_cap = res.captain and s.player.id == res.captain.player.id
                return {
                    "": "🧢" if es_cap else "",
                    "Jugador": s.player.nickname,
                    "Pos": POS.get(s.player.position_id, "?"),
                    "Equipo": team_name(teams, s.player.team_id),
                    "Pts esp.": lineup.expected_points(s),
                    "Próximo rival": next_opp_txt(s.player.team_id),
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

# --- Explorar ---
if page == "📋 Explorar":
    st.subheader("Explorar todos los jugadores")
    f1, f2, f3, f4 = st.columns(4)
    pos_sel = f1.multiselect("Posición", list(POS.values()))
    precio_max = f2.slider("Precio máximo (M€)", 0, 150, 150)
    solo_ok = f3.checkbox("Solo disponibles", value=True)
    buscar = f4.text_input("Buscar jugador")

    df = tabla_explorar(version, pesos, tuple(sorted(squad_ids)))
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
if page == "🧮 Tu plantilla":
    st.subheader("Tu plantilla")
    if not squad_scores:
        st.info("Guarda tu plantilla en la barra lateral para analizarla.")
    else:
        valor = sum(s.player.market_value for s in squad_scores)
        m1, m2, m3 = st.columns(3)
        m1.metric("Valor de tu plantilla", fmt_eur(valor))
        m2.metric("Disponible", fmt_eur(disponible))
        m3.metric("A vender (aviso)", len(rec.vender))

        st.markdown("**Tu equipo por posición** (dónde vas fuerte y dónde reforzar)")
        resumen = advisor.position_summary(squad_scores)
        st.dataframe(pd.DataFrame([{
            "Posición": advisor.POS_NOMBRE[p.position_id],
            "Tienes": p.count,
            "Titulares": p.need,
            "Nivel (media titulares)": f"{p.level} ({p.avg_starters})",
        } for p in resumen]), use_container_width=True, hide_index=True)

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
                "Tendencia": _trend_txt(tendencias, s.player.id),
                "Próximo rival": next_opp_txt(s.player.team_id),
                "Estado": s.player.status_es,
                "Consejo": ("🔒 No vender (imprescindible)" if s.player.id in rec.imprescindibles
                            else "🔴 VENDER" if s in rec.vender else "🟢 Mantener"),
            })
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        if rec.imprescindibles:
            nombres = ", ".join(sc.player.nickname for sc in squad_scores
                                if sc.player.id in rec.imprescindibles)
            st.info(f"🔒 No te recomiendo vender a **{nombres}**: te dejaría sin poder "
                    "formar un once completo. Ficha un recambio en su posición antes de venderlo.")

        # Aviso de valor a la baja (buen momento para vender antes de que caiga más).
        bajando = [s for s in squad_scores
                   if (tendencias.get(s.player.id) and tendencias[s.player.id].direction == "down")]
        if bajando:
            nombres = ", ".join(s.player.nickname for s in
                                sorted(bajando, key=lambda s: tendencias[s.player.id].pct)[:5])
            st.warning(f"📉 Bajando de valor (plantéate vender antes de que caiga más): **{nombres}**")

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
                c = db.connect(); team_state.add_listing(c, uid, sv.player.id, precio_v); c.close()
                st.success(f"{sv.player.nickname} puesto en venta por {fmt_eur(precio_v)}.")
                st.rerun()
            if b2.button("✅ Registrar venta hecha", type="primary", use_container_width=True):
                c = db.connect()
                team_state.remove_listing(c, uid, sv.player.id)
                nuevo = team_state.sell_player(c, uid, sv.player.id, precio_v)
                c.close()
                st.success(f"Vendido {sv.player.nickname}. Dinero: {fmt_eur(nuevo)}")
                st.rerun()


# --- Detalle de jugador ---
if page == "🔍 Jugador":
    st.subheader("🔍 Detalle de jugador")
    dopts = {f"{p.nickname} · {team_name(teams, p.team_id)} ({POS.get(p.position_id,'?')})": p.id
             for p in sorted(players, key=lambda x: x.nickname)}
    dsel = st.selectbox("Elige un jugador", ["—"] + list(dopts.keys()), key="detalle_sel")
    if dsel != "—":
        pid = dopts[dsel]
        s = score_por_id.get(pid)
        p = s.player if s else players_by_id.get(pid)
        adv = market.price_advice(s) if s else None
        t = tendencias.get(pid)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Valor", fmt_eur(p.market_value))
        c2.metric("Score", s.score if s else "—")
        c3.metric("Pts esperados", lineup.expected_points(s) if s else "—")
        c4.metric("Puntos totales", p.points)
        c1b, c2b, c3b, c4b = st.columns(4)
        c1b.metric("Forma (últimas)", s.forma if s else "—")
        c2b.metric("Titularidad", f"{round(s.titularidad*100)}%" if s else "—")
        c3b.metric("Media/jornada", round(p.average_points, 1))
        c4b.metric("Estado", p.status_es)

        if adv:
            st.markdown(f"🛒 Comprar hasta **{fmt_eur(adv.max_buy)}** · 🏷️ Vender por "
                        f"**{fmt_eur(adv.sell_ask)}** · 🛡️ Cláusula sugerida **{fmt_eur(adv.suggested_clause)}**")
        if t and t.direction != "new":
            signo = "+" if t.change > 0 else ""
            st.markdown(f"{t.emoji} Valor **{t.label}** ({signo}{t.pct:.1f}% desde la última actualización)")

        # Puntos por jornada (gráfico de barras).
        if p.week_points:
            st.markdown("**Puntos por jornada**")
            wp = dict(sorted(p.week_points.items()))
            st.bar_chart(pd.DataFrame({"Puntos": list(wp.values())},
                                      index=[f"J{k}" for k in wp.keys()]))

        # Evolución del valor de mercado.
        hist = cargar_valor_historico(version, pid)
        if len(hist) >= 2:
            st.markdown("**Evolución del valor de mercado**")
            dfh = pd.DataFrame({"Valor (€)": [v for _, v in hist]},
                               index=[d for d, _ in hist])
            st.line_chart(dfh)
        else:
            st.caption("El gráfico de valor aparecerá cuando haya al menos 2 actualizaciones "
                       "en días distintos.")

        # Próximos partidos.
        st.markdown("**Próximos partidos**")
        prox = engine.next_opponents(p.team_id, fixtures, n=5)
        if prox:
            filas = []
            for rid, es_local, week in prox:
                filas.append({
                    "Jornada": f"J{week}",
                    "Rival": ("🏠 vs " if es_local else "✈️ @ ") + team_name(teams, rid),
                })
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        else:
            st.caption("Sin próximos partidos en el calendario.")
