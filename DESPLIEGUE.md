# Despliegue gratuito: GitHub → Vercel + Neon + MongoDB Atlas + Cloudflare R2

```
 GitHub (código) ──push──▶ Vercel (frontend + API en 1 función Python)
                              ├─▶ Neon        (PostgreSQL)
                              ├─▶ MongoDB Atlas (M0)
                              └─▶ Cloudflare R2 (datalake S3 + copias)
 GitHub Actions ──cada 30 min──▶ /api/cron/etl      Vercel Cron ──1 vez/día──▶ /api/cron/backup
```
Cada `git push` a `main` redespliega solo. Las ramas y *pull requests* generan una URL de vista previa.

> **Importante antes de empezar**
> - **Vercel Hobby es solo para uso personal/no comercial** (términos de Vercel). Sirve para el proyecto académico; si la app la opera una empresa, necesitas el plan Pro.
> - El cuerpo de cada petición a Vercel está limitado a **4,5 MB**: por eso el audio de voz se limita a ~3,5 MB (`MAX_AUDIO_BYTES`).
> - En el plan gratis, Vercel solo permite **1 tarea programada al día**. La copia de seguridad (cada 24 h) usa esa; el ETL lo dispara GitHub Actions.
> - Esta configuración está probada con pruebas automáticas (PostgreSQL real, Mongo simulado, S3 simulado) pero **no se pudo probar desde aquí en Vercel/Neon/Atlas/R2 reales**. Haz el chequeo del paso 9.

## 1. GitHub
1. Crea un repositorio y sube el proyecto (el `.gitignore` ya excluye `.env*`). Primero ejecuta `python tools/scan_secrets.py`.
   - **Privado** recomendado para el código; Actions da 2.000 min/mes gratis (el ETL cada 30 min gasta ~1.440). **Público**: ilimitado; puedes cambiar a `*/5` en `.github/workflows/etl.yml`.
2. La rama de producción es `main`.

## 2. Neon (PostgreSQL)
1. neon.com → proyecto nuevo (región cercana a Vercel; en Vercel el proyecto se puede fijar a `iad1`).
2. *Connect* → activa **Connection pooling** → copia la cadena (el host termina en `-pooler`). Es tu `DATABASE_URL` (con `sslmode=require`).
3. Las tablas se crean solas en la primera petición (`init()` versionado).

## 3. MongoDB Atlas (M0 gratis)
1. Crea un cluster **M0**. *Database Access*: usuario con clave larga y rol *readWrite* sobre la base `psico`.
2. *Network Access*: Vercel no tiene IP fija en el plan gratis, por lo que hay que permitir `0.0.0.0/0`. **Es el punto más débil de esta arquitectura**: lo compensan la clave larga, TLS obligatorio y que solo la API conoce la cadena. (Con plan Pro de Vercel existe IP estática.)
3. *Connect → Drivers → Python*: copia la cadena `mongodb+srv://…` como `MONGO_URL`.

## 4. Cloudflare R2 (datalake)
1. Panel de Cloudflare → R2 (pide un método de pago para activarlo; el nivel gratis son 10 GB y no cobra mientras no lo superes).
2. Crea el bucket (p. ej. `serenia-lake`, **privado**: no actives acceso público).
3. *Manage API tokens* → permisos **Object Read & Write** limitados a ese bucket → copia Access Key y Secret.
4. `S3_URL=https://<ID_DE_CUENTA>.r2.cloudflarestorage.com`, `S3_REGION=auto`.
5. **Copias fuera del datalake (recomendado):** crea otro bucket gratis en otro proveedor (p. ej. Backblaze B2) y rellena `BACKUP_S3_*`. Si no, las copias se guardan en `backups/` del mismo bucket.

## 5. Vercel
1. vercel.com → *Add New → Project* → importa el repositorio de GitHub.
2. *Framework Preset*: **Other**. No pongas comando de build. El `vercel.json` ya define: carpeta estática `frontend/`, la función `api/index.py`, las rutas `/api/*`, las cabeceras de seguridad (CSP, HSTS…) y los cron.
3. *Settings → Environment Variables*: copia todas las de **`.env.vercel.example`** (producción). Genera los secretos con `python tools/gen_secrets.py`. Para `BASE_URL` usa la URL final (si usas dominio propio, ese dominio).
4. *Deploy*. Si el primer despliegue falla por una variable mala, la app **se niega a arrancar en producción con configuración insegura** y el motivo sale en *Logs* (`[SEGURIDAD][ERROR]`).
5. Opcional: *Settings → Security → Firewall* → regla de límite de peticiones para `/api/auth/*` (el plan gratis permite pocas reglas; la app ya limita por su cuenta).

## 6. GitHub Actions (ETL cada 30 min)
*Repo → Settings → Secrets and variables → Actions* → crea `SITE_URL` (`https://tu-app.vercel.app`, sin barra final) y `CRON_SECRET` (el mismo valor que en Vercel). Prueba con *Actions → ETL programado → Run workflow*.

Qué hace el ETL en la nube: las **encuestas y los juegos** se transforman al instante (el estudiante los ve de inmediato); lo demás (clasificación de emociones del chat con IA, resúmenes de memoria, carga del conocimiento) se procesa en cada pasada.

## 7. Copias de seguridad
Vercel Cron llama a `/api/cron/backup` cada día (hora aproximada, ±1 h): PostgreSQL + MongoDB + datalake → cifrado AES-256-GCM → relectura de verificación → subida al bucket → borrado de copias de más de `BACKUP_KEEP_DAYS` días. **Guarda `BACKUP_KEY` también en un gestor de contraseñas: sin ella no se puede restaurar.**
Restaurar: descarga el `.enc` del bucket y, en tu equipo con las mismas variables de entorno: `python services/backup/restore.py archivo.enc` (re-aplica los borrados de cuentas hechos después de la copia).

## 8. Seguridad en la nube
- Ninguna clave va en el código: todo está en variables de entorno de Vercel. *Vercel guarda un único conjunto de variables por proyecto*, así que las claves de IA del chat y del ETL quedan en el mismo sitio (en Docker estaban separadas).
- Las rutas `/api/cron/*` rechazan cualquier petición sin `Authorization: Bearer <CRON_SECRET>` (y quedan apagadas si el secreto tiene menos de 24 caracteres).
- Vercel ya sirve todo con HTTPS; el `vercel.json` añade HSTS. Las cookies de sesión son `__Host-`, `Secure`, `HttpOnly`.
- Cambia periódicamente la clave de Atlas/Neon/R2 y los `*_SECRET`. Cambiar `JWT_SECRET` cierra todas las sesiones.

## 9. Chequeo después del primer despliegue
1. `https://tu-app.vercel.app/api/health` → `{"ok":true}`.
2. Registra una cuenta (llega el código por correo) → entra → escribe en el chat → completa una encuesta.
3. *Actions → ETL programado → Run workflow* → debe terminar en verde y el log muestra `{"ok":true,"processed":…}`.
4. Panel de Neon (*Tables*): `credentials`, `surveys`, `account_state`… Atlas: colección `chat`. R2: carpetas `raw/` y `processed/`.
5. Prueba la copia: en Vercel *Settings → Cron Jobs → Run* sobre `/api/cron/backup`; debe aparecer un `serenia-*.tar.gz.enc` en el bucket.
6. Elimina la cuenta de prueba desde *Personalizar → Eliminar mi cuenta*.

## Límites del plan gratis a vigilar
| Servicio | Límite | Qué pasa si se supera |
|---|---|---|
| Vercel Hobby | 1 M invocaciones/mes, 4 h de CPU activa/mes, 100 despliegues/día, logs de 1 h | La función se pausa hasta el siguiente mes |
| Neon Free | almacenamiento y horas de cómputo limitados; la base se *duerme* tras unos minutos sin uso (la primera petición tarda ~1 s más) | — |
| Atlas M0 | 512 MB | Escrituras rechazadas |
| R2 | 10 GB y operaciones mensuales gratis | Cobro por exceso |

## Desarrollo local con Docker (opcional)
`cp .env.example .env` (+ `.env.chat`, `.env.etl`) y `docker compose up -d --build` → http://localhost:8000. Usa PostgreSQL 16 y **SeaweedFS** (Apache-2.0, sustituye a MinIO) en contenedores. Pruebas: `pip install -r requirements.txt pytest mongomock && python -m pytest tests`; contra PostgreSQL real: `TEST_DATABASE_URL=postgresql://… python -m pytest tests`.

## Si algo falla
- *500 en todo*: *Vercel → Logs*; busca `[SEGURIDAD][ERROR]` (variable mal puesta) o errores de conexión (cadena de Neon/Atlas).
- *`/api/...` da 404*: revisa que en *Project Settings* el *Root Directory* sea la raíz del repo y que `vercel.json` esté ahí.
- *Función demasiado grande/lenta al arrancar*: normal en la primera petición tras un rato (arranque en frío).
- *Atlas "timed out"*: falta permitir `0.0.0.0/0` en *Network Access*.
- *R2 `AccessDenied`*: el token no cubre ese bucket o `S3_BUCKET` no coincide.
