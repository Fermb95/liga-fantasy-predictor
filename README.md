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
2. **Con tu cuenta oficial**: inicia sesión en la barra lateral y se autocargan
   tu dinero, tu plantilla y **el mercado concreto de tu liga** (pestaña
   *🛒 Mercado de tu liga* → a quién pujar hoy). Dos métodos:
   - **Con email y contraseña**: rellena y pulsa *Iniciar sesión*.
   - **Pegar token** (cuentas con Google): captura el token de la app móvil (ver
     abajo) y pégalo. *Nota: el login con Google desde el navegador no es posible
     porque LaLiga solo lo permite en sus apps oficiales.*

### Capturar el token desde la app móvil (cuentas con Google)

El token es un texto largo que empieza por `eyJ…`. Se saca interceptando una
petición de la app oficial a `fantasy-api.llt-services.com` con una herramienta
gratuita. Caduca en ~1 h, así que se vuelve a pegar cuando expire.

**Android (con HTTP Toolkit, gratis):**
1. Instala **HTTP Toolkit** en tu PC (https://httptoolkit.com) y en el móvil.
2. Conéctalos (por WiFi o ADB, la app te guía) e intercepta la app *LALIGA FANTASY*.
3. Abre la app oficial y navega (entra a tu liga).
4. En HTTP Toolkit, busca una petición a `fantasy-api.llt-services.com` → pestaña
   *Headers* → copia el valor de `Authorization` (lo que va tras `Bearer `).
5. Pégalo en la app, método *Pegar token* → *Conectar*.

**iPhone (con un proxy tipo Proxyman/Charles):**
1. Instala Proxyman en el PC; configura el proxy WiFi del iPhone hacia el PC.
2. Instala y **confía** el certificado de Proxyman en el iPhone
   (Ajustes → General → Información → Ajustes de certificados de confianza).
3. Abre la app oficial y navega; en Proxyman busca `fantasy-api.llt-services.com`
   y copia la cabecera `Authorization: Bearer …`.

### Seguridad del login

- Tu contraseña (si la usas) se envía **solo** al servidor oficial de LaLiga por HTTPS.
- **No se guarda** contraseña ni token en disco: solo en la sesión de tu navegador.

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
