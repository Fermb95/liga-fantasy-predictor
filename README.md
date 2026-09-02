# ⚽ Predictor LaLiga Fantasy Oficial

App que te dice **qué comprar, qué vender y qué ignorar** en LaLiga Fantasy
Oficial, según tu dinero, los precios del juego y las estadísticas oficiales de
cada jornada. Pensada para el móvil y **gratis** de principio a fin.

Datos oficiales de la API de LaLiga Fantasy (Relevo). Python + Streamlit +
SQLite. Se actualiza con un botón tras cada jornada.

## Ejecutar en local

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

La primera vez, pulsa **🔄 Actualizar datos** para descargar los datos oficiales.

Actualizar la base de datos por línea de comandos (opcional):

```bash
python -m src.ingest
```

## Cómo se usa

1. **Sin cuenta**: mete tu dinero disponible y marca tu plantilla en la barra
   lateral. La app te da COMPRAR / VENDER / IGNORAR.
2. **Con tu cuenta oficial** (recomendado): inicia sesión en la barra lateral y
   se autocargan tu dinero, tu plantilla y **el mercado concreto de tu liga**
   (pestaña *🛒 Mercado de tu liga* → a quién pujar hoy).

### Seguridad del login

- Tu contraseña se envía **solo** al servidor oficial de LaLiga por HTTPS.
- **No se guarda** en disco ni en logs: solo se conservan los tokens en la sesión.
- Si entras a LaLiga **con Google**, el login por contraseña no funciona: usa el
  desplegable *"¿Entras con Google? Pega tu token"* (token Bearer desde el
  navegador: F12 → Network).

### Verificar el login con tu cuenta (opcional)

Los tests que tocan tu cuenta están desactivados salvo que definas tus
credenciales por variable de entorno (así nadie más las ve):

```powershell
$env:LFP_EMAIL = "tu@email.com"
$env:LFP_PASSWORD = "tu_contraseña"
python -m pytest -m live -k "real" -s
```

## Tests

```bash
python -m pytest          # todo (los 'live' de cuenta se saltan sin credenciales)
python -m pytest -m "not live"   # solo lógica, sin red
```

## Desplegar gratis (Streamlit Community Cloud)

1. Sube esta carpeta a un repositorio de GitHub.
2. Entra en https://share.streamlit.io con tu cuenta de GitHub.
3. **New app** → elige el repo, rama `main`, fichero `app.py`.
4. Deploy. En unos minutos tendrás una URL pública para abrir desde el móvil.

> La base de datos SQLite es **efímera** en la nube (se reinicia al redeplegar),
> pero da igual: el botón **🔄 Actualizar datos** vuelve a bajar todo de la API
> oficial en segundos. No necesitas base de datos externa.

Alternativa: [Render](https://render.com) (plan free) con
`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.

## Estructura

```
app.py              UI Streamlit (capa fina)
src/api_client.py   Cliente de la API pública (jugadores, calendario)
src/db.py           SQLite: esquema, upserts y lecturas
src/ingest.py       Descarga API -> SQLite (botón 🔄)
src/engine.py       Motor de valoración (score 0-100 por jugador)
src/recommender.py  COMPRAR / VENDER / IGNORAR según tu dinero y plantilla
src/auth.py         Login oficial (Azure B2C, ROPC)
src/account.py      Cliente autenticado (dinero, plantilla, mercado de tu liga)
tests/              Tests (incluye reales contra la API)
```
