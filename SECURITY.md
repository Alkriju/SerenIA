# Seguridad y cumplimiento de SerenIA

> Esto es lo que el **código** hace. Los textos legales (`frontend/legal/`) son un **documento base**: antes de publicar deben ser revisados por un asesor legal. Nada aquí es una certificación (ISO 27001, WCAG, etc.): está **alineado con** esas normas.

## 1. Poner la app en internet (paso a paso)
1. Servidor con Docker y un dominio apuntando a su IP; puertos **80 y 443** abiertos (el resto cerrado).
2. `python tools/gen_secrets.py` → copia los valores a `.env` (`JWT_SECRET`, `PSEUDO_KEY`, `BACKUP_KEY`, `S3_SECRET`, `PG_PASS`, `MONGO_ROOT_PASS`). **Guarda `BACKUP_KEY` también fuera del servidor.**
3. En `.env`: `APP_ENV=production`, `BASE_URL=https://tu-dominio`, `DOMAIN=tu-dominio`, `ACME_EMAIL=tu@correo`, `EMAIL_DOMAIN=...`, `SMTP_*` (obligatorio: los códigos ya no salen por los logs), `ADMIN_EMAILS=...`, `DEV_AUTH=0`.
4. Completa `frontend/legal/legal.json` (empresa, NIT, dirección, correos, teléfono) y los textos pendientes; cuando un asesor legal los apruebe pon `"draft": false`. Verifica con `python tools/check_legal.py --prod`.
5. Antes de cada despliegue: `python tools/scan_secrets.py` y `pytest -q tests`.
6. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.

**En `APP_ENV=production` el backend NO arranca** si falta algo de esto (JWT/PSEUDO_KEY débiles, `DEV_AUTH=1`, `BASE_URL` sin https, `SMTP_HOST` vacío…): es a propósito.

### Contraseña de MongoDB (una sola vez)
Mongo solo crea el usuario al inicializar un volumen **vacío**. Con datos de desarrollo que no necesites: `docker compose down -v`, define `MONGO_ROOT_USER`/`MONGO_ROOT_PASS` y `MONGO_URL=mongodb://USUARIO:CLAVE@mongo:27017/?authSource=admin`, y vuelve a levantar. Si pones usuario sobre un volumen viejo, la app no podrá conectarse.

## 2. Tus requisitos, uno por uno
| # | Requisito | Qué se hizo | Estado |
|---|---|---|---|
| 1 | HTTPS en todas las páginas | Caddy con Let's Encrypt automático, redirección http→https, HSTS, cookie `Secure` y prefijo `__Host-` | ✅ en producción (en local es http://localhost) |
| 2 | Ninguna clave en el código | Todo por variables de entorno; `tools/scan_secrets.py` lo comprueba; `.env*` en `.gitignore` | ✅ |
| 3 | Copia automática cada 24 h | Servicio `backup`: PostgreSQL + MongoDB + datalake, **cifrada AES-256-GCM**, se relee para verificarla, retención 14 días, subida opcional a otro S3. Borrados se re-aplican al restaurar (`restore.py`) | ✅ — ⚠️ prueba una restauración antes de lanzar; la copia en el mismo servidor no te protege si el servidor se pierde: configura `BACKUP_S3_*` |
| 4 | Formularios protegidos contra bots | Captcha propio de prueba de trabajo (sin terceros ni rastreo) + honeypot + límites por IP y por correo + límites en nginx | ✅ — un bot dedicado puede resolverlo con cómputo; si hay ataques reales se puede añadir Cloudflare Turnstile |
| 5 | Límite de intentos al iniciar sesión | 5 fallos → bloqueo 15 min (30, 60… si sigue); límite por IP más alto (campus comparten IP); mensaje idéntico exista o no el correo; igualación de tiempos | ✅ |
| 6 | Cada usuario ve solo lo suyo | Todas las consultas filtran por el correo de la sesión; probado con dos usuarios (`tests/test_services.py::test_boveda…`); la IA recibe solo el contexto de esa persona | ✅ |
| 7 | Errores que no enseñan nada | Manejadores globales con mensaje genérico (el detalle solo en logs internos, con id), `/docs` y `/openapi.json` apagados, `/status` `/diagnose` `/context` solo para administradores, `server_tokens off` | ✅ |
| 8 | Llaves en variables de entorno | `.env`, `.env.chat`, `.env.etl` separados por servicio | ✅ |
| 9 | Validar todo en el servidor | Tipos, longitudes, listas permitidas y tamaños máximos en cada ruta; el cliente nunca decide permisos; errores 422 sin repetir lo escrito | ✅ |
| 10 | Consultas parametrizadas | Todo `%s`; solo nombres de tabla constantes. Mongo: valores validados como texto (no se aceptan operadores `$…`) | ✅ |
| 11 | Contraseñas cifradas | **Argon2id**; los hashes antiguos PBKDF2 se convierten solos en el siguiente ingreso; el código de verificación se guarda con HMAC | ✅ |
| 12 | Permisos en cada petición | Cada petición de cada servicio revisa firma, caducidad, versión de sesión y aceptación de términos (≤5 s de retraso al revocar) | ✅ |
| 13 | Cookies de sesión | HttpOnly, Secure (prod), SameSite=Lax, `__Host-`, caducidad 7 días, comprobación de `Origin` contra CSRF | ✅ |
| 14 | Dependencias con vulnerabilidades | Versiones fijas; `pip-audit`: *No known vulnerabilities found* (2026-11-17); contenedor sin root, sin privilegios | ✅ — repetir cada mes. ⚠️ MinIO ya no se mantiene (ver §4) |
| 15–16 | Política de privacidad y Términos | `frontend/legal/privacidad.html` y `terminos.html` (Ley 1581/2012, Decreto 1377/2013, GDPR) | ⚠️ documento base: revisión legal |
| 17 | Banner de cookies | Banner con "Solo necesarias / Aceptar todas / Personalizar" y enlace permanente para cambiar la elección | ✅ |
| 18 | Teclado | Skip-link, foco visible, diálogos con foco atrapado y Esc, todo lo clicable accesible con Enter/Espacio; probado con Playwright | ✅ (sin probar con lector de pantalla real) |
| 19 | Sin logos de terceros | Auditoría: no hay logos, imágenes de terceros ni marcas | ✅ |
| 20 | Licencias de imágenes, fuentes y código | `THIRD_PARTY_LICENSES.md` | ✅ — ✅ (sin componentes propietarios) |
| 21 | Casilla sin marcar con enlace a los términos | 3 casillas sin marcar: (1) 18+, Términos y Privacidad; (2) datos sensibles y proveedores de IA; (3) mejora de la IA (opcional). Botón bloqueado hasta marcar (1) y (2) y el **servidor** lo exige | ✅ |
| 22 | Eliminar cuenta tan fácil como crearla | Personalizar → "Eliminar mi cuenta" → una confirmación. Borra PostgreSQL, MongoDB, datalake e invalida la sesión | ✅ |
| 23 | Registrar quién aceptó y cuándo | Tabla `consent_log`: correo, documento, versión, aceptado, fecha del servidor, huella (HMAC) de IP y navegador. Tras borrar la cuenta queda solo la prueba seudonimizada | ✅ |
| 24 | Cumplir licencias de código abierto | `THIRD_PARTY_LICENSES.md`, `OFL.txt`, avisos LGPL/MPL | ✅ |
| 25 | Canal de reclamos de derechos de autor | `derechos-autor.html` con procedimiento de aviso y retiro | ⚠️ falta tu correo en `legal.json` |
| 26 | No entrenar con datos sin permiso; si acepta, activarlo | El ETL copia a `improve_corpus` solo lo de quienes marcaron la casilla (seudonimizado y sin correos/teléfonos/enlaces); al retirarla se borra lo aportado | ✅ — ⚠️ ver §4: los proveedores de IA tienen sus propias políticas |
| 27 | Auditar SDKs, analítica y rastreo | Ver §3 | ✅ |
| 28 | Bloquear rastreadores hasta aceptar | `window.Consent.onAllow(...)`: cualquier script opcional futuro solo carga tras el consentimiento. Hoy no existe ninguno | ✅ |
| 29 | Publicar proveedores que procesan datos | Tabla en Términos y Privacidad desde `legal.json` (solo los `active`) | ⚠️ mantenla al día si cambias de proveedor |
| 30 | Datos de contacto de la empresa | Campos en `legal.json` | ⚠️ **faltan tus datos** (`tools/check_legal.py` los lista) |
| 31 | Normas internacionales | Alineado con Ley 1581/2012, GDPR (consentimiento, acceso/portabilidad `/export`, supresión, transferencias internacionales) y buenas prácticas OWASP/ISO 27001 | ℹ️ sin certificación |

## 3. Auditoría de SDKs, analítica y rastreo (2026-11-17)
- **Navegador:** cero peticiones a terceros (probado con Playwright). Se eliminó Google Fonts (enviaba la IP a Google); no hay Google Analytics, píxeles, chat externo, reCAPTCHA ni mapas.
- **Almacenamiento:** una cookie necesaria (`t`/`__Host-t`) y `localStorage` (`last`, `mute`, `vol`, `cc`).
- **Servidor → terceros** (solo con datos del servicio): Google (Gemini + voz), OpenAI, Groq, Alibaba Qwen (Singapur), DeepSeek (China), correo SMTP, Let's Encrypt. Están listados en los Términos.
- **Sin SDKs:** las IA se llaman por REST con `httpx`; no hay SDKs de analítica.

## 4. Lo que tienes que decidir o hacer (no se puede resolver solo con código)
1. **Datos de la empresa y revisión legal** (puntos 15, 16, 25, 30).
2. **PostgreSQL:** ya no hay licencia propietaria (se migró desde CockroachDB). En Docker no publiques el puerto 5432; en la nube usa siempre `sslmode=require`.
3. **Datalake:** MinIO se sustituyó por SeaweedFS (Apache-2.0) en local y por un bucket S3 gestionado (Cloudflare R2) en la nube; el código solo usa la API S3.
4. **Proveedores de IA y entrenamiento:** los planes **gratuitos** de algunos proveedores (p. ej. Gemini API gratis) pueden usar los datos enviados para mejorar sus productos, y DeepSeek/Qwen procesan en China/Singapur. Si de verdad no se debe entrenar con datos sin permiso, usa planes de pago con "sin entrenamiento" o desactiva esos proveedores (`"active": false` en `legal.json` y quítalos de `LLM_ORDER`/`ETL_LLM_ORDER`). Datos de salud mental son **datos sensibles** (Ley 1581 art. 5): considera si el ETL debe enviarlos a proveedores fuera de Colombia.
5. **Registro de bases de datos** ante la SIC (RNBD), si tu empresa está obligada.
6. **Vercel:** ver `DESPLIEGUE.md` §Seguridad en la nube (IP de Atlas, secretos en variables de entorno de Vercel, protección de las tareas programadas con `CRON_SECRET`).
7. **Probar la restauración** de una copia (`docker compose run --rm backup python restore.py /backups/<archivo>.enc`) antes de confiar en ella.

## 5. Archivos nuevos importantes
`shared/security.py` (núcleo) · `shared/purge.py` (borrar/exportar) · `services/backup/` · `tests/` (30 pruebas + e2e) · `tools/` · `Caddyfile` · `docker-compose.prod.yml` · `nginx.conf` + `nginx/` · `requirements.txt` · `THIRD_PARTY_LICENSES.md`.
