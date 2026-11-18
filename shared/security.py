"""Seguridad común a TODOS los microservicios de SerenIA.
 - Sesión (JWT en cookie HttpOnly) con caducidad y revocación; permisos revisados en CADA petición (no solo al iniciar sesión)
 - Aceptación de términos exigida por el servidor en cada petición
 - Límites de intentos / de uso (contador atómico en MongoDB con TTL)
 - Captcha propio de prueba de trabajo (sin servicios de terceros ni rastreo)
 - Contraseñas con Argon2id (y migración automática de los hashes antiguos PBKDF2)
 - Errores genéricos hacia el cliente (el detalle queda solo en los logs), cabeceras seguras, comprobación de origen (CSRF)
Este módulo NO importa common al cargar (evita ciclos): lo hace de forma perezosa."""
import os, re, time, hmac, hashlib, secrets, json, logging, uuid, datetime as dt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import Request, HTTPException, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

E = os.environ
log = logging.getLogger("serenia")
PROD = E.get("APP_ENV", "development").lower() == "production"
SECURE = PROD or E.get("COOKIE_SECURE", "0") == "1"
COOKIE = "__Host-t" if SECURE else "t"            # prefijo __Host-: solo HTTPS, sin Domain, path=/ (evita que otro subdominio la sobrescriba)
SESSION_HOURS = int(E.get("SESSION_HOURS", "168"))  # 7 días; la política de cookies publicada dice lo mismo
TERMS_VERSION = E.get("TERMS_VERSION", "2026-11-16")  # debe coincidir con frontend/legal/legal.json (tools/check_legal.py lo verifica)
GENERIC = "Ocurrió un error. Intenta de nuevo en un momento."

def _secret() -> str: return E.get("JWT_SECRET", "")
def _pseudo() -> str: return E.get("PSEUDO_KEY") or _secret()
def eh(email: str) -> str:
    """Identificador seudonimizado de un correo (HMAC-SHA256): sirve para acreditar consentimientos y marcar cuentas borradas SIN guardar el correo."""
    return hmac.new(_pseudo().encode(), email.strip().lower().encode(), hashlib.sha256).hexdigest()
def h_ip(ip: str) -> str: return hmac.new(_pseudo().encode(), ("ip:" + ip).encode(), hashlib.sha256).hexdigest()[:32]

def startup_checks():
    """En producción NO arranca con configuración insegura; en desarrollo solo avisa."""
    probs = []
    s = _secret()
    if len(s) < 32 or s in ("cambia-este-secreto-largo",): probs.append("JWT_SECRET debe tener 32+ caracteres aleatorios (openssl rand -hex 32)")
    if E.get("DEV_AUTH") == "1": probs.append("DEV_AUTH=1 abre una puerta de entrada sin contraseña: debe ser 0")
    if PROD:
        if E.get("COOKIE_SECURE", "1") != "1": probs.append("COOKIE_SECURE debe ser 1")
        if not E.get("BASE_URL", "").startswith("https://"): probs.append("BASE_URL debe empezar por https://")
        if not E.get("PSEUDO_KEY") or len(E.get("PSEUDO_KEY", "")) < 32: probs.append("PSEUDO_KEY (32+ caracteres) es obligatoria en producción")
        if E.get("EMAIL_DOMAIN", "*") == "*" and E.get("ALLOW_ANY_EMAIL", "0") != "1": probs.append("EMAIL_DOMAIN=* acepta cualquier correo; pon tu dominio o ALLOW_ANY_EMAIL=1 si es a propósito")
        if not E.get("SMTP_HOST"): probs.append("SMTP_HOST vacío: en producción los códigos de verificación no pueden salir por los logs")
    for p in probs:
        print(("[SEGURIDAD][ERROR] " if PROD else "[SEGURIDAD][AVISO] ") + p, flush=True)
    if PROD and probs: raise SystemExit("Configuración insegura para producción: " + "; ".join(probs))

# ───────────────────────── respuestas de error ─────────────────────────
class ApiError(HTTPException):
    def __init__(self, status, detail, code=None, headers=None):
        super().__init__(status, detail, headers); self.code = code
def _body(detail, code=None, **x):
    d = {"detail": detail}
    if code: d["code"] = code
    d.update(x); return d

# ───────────────────────── Mongo / PostgreSQL (perezoso) ─────────────────────────
def _m():
    import common; return common.mongo
def _pg():
    import common; return common.pg()

# ───────────────────────── Límites de uso ─────────────────────────
def rate(key: str, limit: int, window: int, msg="Demasiados intentos. Espera un momento e inténtalo de nuevo."):
    """Contador atómico por ventana fija. Lanza 429 con Retry-After al pasar el límite."""
    now = time.time(); b = int(now // window)
    try:
        d = _m().rl.find_one_and_update({"_id": f"{key}:{b}"}, {"$inc": {"n": 1}, "$setOnInsert": {"exp": dt.datetime.utcnow() + dt.timedelta(seconds=window * 2)}}, upsert=True, return_document=True)
    except Exception as ex:
        log.error("rate-limit store caído: %s", type(ex).__name__)
        if PROD: raise ApiError(503, GENERIC, "unavailable")   # sin contador no se arriesga: falla cerrado
        return
    if d["n"] > limit:
        wait = int((b + 1) * window - now) + 1
        raise ApiError(429, msg, "rate_limited", {"Retry-After": str(wait)})
def client_ip(req: Request) -> str:
    if E.get("VERCEL"):   # en Vercel esta cabecera la pone la plataforma y reemplaza la que mande el cliente (en otros servidores NO se confía en ella)
        v = req.headers.get("x-vercel-forwarded-for")
        if v: return v.split(",")[0].strip()[:64]
    return (req.headers.get("x-real-ip") or (req.client.host if req.client else "") or "?")[:64]   # lo fija nginx/Caddy; los servicios no están expuestos directamente

# bloqueo por cuenta tras fallos de inicio de sesión
LOCK_FAILS, LOCK_WINDOW, LOCK_SECS = int(E.get("LOGIN_MAX_FAILS", "5")), 900, int(E.get("LOGIN_LOCK_SECS", "900"))
def lock_check(k):
    d = _m().lockouts.find_one({"_id": k})
    if d and d.get("until", 0) > time.time():
        raise ApiError(429, "Demasiados intentos fallidos. Por seguridad esta cuenta está bloqueada unos minutos; inténtalo más tarde.", "locked", {"Retry-After": str(int(d["until"] - time.time()) + 1)})
def lock_fail(k, fails=None):
    fails = fails or LOCK_FAILS
    now = time.time(); d = _m().lockouts.find_one({"_id": k}) or {}
    n = (d.get("n", 0) + 1) if now - d.get("t", 0) < LOCK_WINDOW else 1
    upd = {"n": n, "t": now, "exp": dt.datetime.utcnow() + dt.timedelta(hours=2)}
    if n >= fails: upd["until"] = now + LOCK_SECS * min(4, 2 ** max(0, n - fails))   # 15, 30, 60 min…
    _m().lockouts.update_one({"_id": k}, {"$set": upd}, upsert=True)
def lock_clear(k): _m().lockouts.delete_one({"_id": k})

# ───────────────────────── Captcha propio (prueba de trabajo) ─────────────────────────
POW_BITS = int(E.get("POW_BITS", "16"))
def _sig(i, salt, bits, exp): return hmac.new(_secret().encode(), f"pow|{i}|{salt}|{bits}|{exp}".encode(), hashlib.sha256).hexdigest()
def pow_challenge():
    i, salt, exp = secrets.token_hex(8), secrets.token_hex(8), int(time.time()) + 300
    return {"id": i, "salt": salt, "bits": POW_BITS, "exp": exp, "sig": _sig(i, salt, POW_BITS, exp)}
def _lead_zero_bits(d: bytes) -> int:
    n = 0
    for b in d:
        if b == 0: n += 8; continue
        return n + (8 - b.bit_length())
    return n
def pow_verify(p):
    """Comprueba firma, caducidad, UN solo uso y que el trabajo se hizo. Lanza 400 si no."""
    bad = ApiError(400, "No pudimos comprobar que eres una persona. Recarga la página e inténtalo de nuevo.", "captcha")
    try:
        i, salt, bits, exp, sig, nonce = str(p["id"]), str(p["salt"]), int(p["bits"]), int(p["exp"]), str(p["sig"]), str(p["nonce"])
    except Exception: raise bad
    if bits < POW_BITS or exp < time.time() or not re.fullmatch(r"[0-9]{1,20}", nonce) or not hmac.compare_digest(sig, _sig(i, salt, bits, exp)): raise bad
    if _lead_zero_bits(hashlib.sha256(f"{salt}:{nonce}".encode()).digest()) < bits: raise bad
    try: _m().pow_used.insert_one({"_id": i, "exp": dt.datetime.utcnow() + dt.timedelta(minutes=15)})
    except Exception: raise bad     # id repetido = reutilización

# ───────────────────────── Contraseñas ─────────────────────────
_ph = PasswordHasher(time_cost=int(E.get("ARGON_T", "3")), memory_cost=int(E.get("ARGON_M", "32768")), parallelism=int(E.get("ARGON_P", "2")))
_DUMMY = _ph.hash("contraseña-falsa-para-igualar-tiempos")
COMMON_PW = set("12345678 123456789 1234567890 11111111 00000000 password password1 password123 contrasena contrasena1 contrasena123 qwertyui qwerty123 qwertyuiop abcd1234 abc12345 admin123 iloveyou colombia colombia1 bogota123 universidad uniminuto 87654321 12341234 asdfghjk asdf1234 123qwe123 zaq12wsx minuto123".split())
def pw_hash(pw: str) -> str: return _ph.hash(pw)
def pw_policy(pw: str, email: str = ""):
    if not isinstance(pw, str) or len(pw) < 8: raise ApiError(400, "La contraseña debe tener mínimo 8 caracteres", "weak_password")
    if len(pw) > 128: raise ApiError(400, "La contraseña es demasiado larga (máximo 128 caracteres)", "weak_password")
    low = pw.lower().replace("ñ", "n")
    if low in COMMON_PW or (email and low == email.split("@")[0].lower()) or len(set(pw)) < 3:
        raise ApiError(400, "Esa contraseña es demasiado común. Elige otra más difícil de adivinar.", "weak_password")
def _legacy(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
def pw_check(pw: str, stored, salt=None):
    """-> (ok, nuevo_hash_si_hay_que_migrar). stored/salt None = usuario inexistente (gasta el mismo tiempo)."""
    if not stored:
        try: _ph.verify(_DUMMY, pw[:128])
        except Exception: pass
        return False, None
    if stored.startswith("$argon2"):
        try: _ph.verify(stored, pw[:128])
        except (VerifyMismatchError, InvalidHashError, VerificationError): return False, None
        return True, (pw_hash(pw) if _ph.check_needs_rehash(stored) else None)
    try: ok = hmac.compare_digest(_legacy(pw[:128], salt or ""), stored)   # hash antiguo PBKDF2: se acepta una vez y se convierte a Argon2id
    except Exception: ok = False
    return ok, (pw_hash(pw) if ok else None)
def code_hash(email: str, code: str) -> str: return hmac.new(_secret().encode(), f"code|{email}|{code}".encode(), hashlib.sha256).hexdigest()

# ───────────────────────── Sesión y permisos ─────────────────────────
_cache = {}   # eh -> (hasta, (sv, terms, ai))
def state(email: str, fresh=False):
    k = eh(email); now = time.time(); c = _cache.get(k)
    if c and c[0] > now and not fresh: return c[1]
    cur = _pg().cursor()
    try:
        cur.execute("SELECT sv, terms, ai FROM account_state WHERE eh=%s", (k,)); r = cur.fetchone()
    finally:
        try: cur.connection.close()
        except Exception: pass
    s = (r[0], r[1], bool(r[2])) if r else (0, None, False)
    _cache[k] = (now + 5, s); return s    # 5 s: un cambio (borrado, retirada de permisos) rige en todos los servicios en segundos
def forget(email): _cache.pop(eh(email), None)
def make_token(email: str, sv: int) -> str:
    now = int(time.time())
    return jwt.encode({"e": email, "sv": sv, "iat": now, "exp": now + SESSION_HOURS * 3600, "jti": uuid.uuid4().hex}, _secret(), "HS256")
def set_cookie(resp, email: str):
    resp.set_cookie(COOKIE, make_token(email, state(email, True)[0]), max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax", secure=SECURE, path="/"); return resp
def clear_cookie(resp):
    resp.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=SECURE); return resp
def _session(req: Request):
    try: c = jwt.decode(req.cookies.get(COOKIE, ""), _secret(), ["HS256"], options={"require": ["e", "exp", "sv"]})
    except Exception: raise ApiError(401, "Tu sesión terminó. Inicia sesión de nuevo.", "unauthorized")
    email = str(c["e"]).lower()
    try: sv, terms, ai = state(email)
    except ApiError: raise
    except Exception as ex:
        log.error("no se pudo verificar la sesión: %s", type(ex).__name__); raise ApiError(503, GENERIC, "unavailable")
    if sv != c["sv"]: raise ApiError(401, "Tu sesión terminó. Inicia sesión de nuevo.", "unauthorized")   # cuenta borrada / sesiones revocadas
    return email, terms
def me_nc(req: Request) -> str:
    """Usuario autenticado (sin exigir términos): para /me, /consent, /export, /account/delete, /logout."""
    return _session(req)[0]
def me(req: Request) -> str:
    """Usuario autenticado Y con los términos vigentes aceptados. Se evalúa en CADA petición de CADA servicio."""
    email, terms = _session(req)
    if terms != TERMS_VERSION: raise ApiError(403, "Debes aceptar los Términos y la Política de Privacidad vigentes para continuar.", "consent_required")
    return email
def admin(u) -> bool: return u in {x.strip().lower() for x in E.get("ADMIN_EMAILS", "").split(",") if x.strip()}
def dbg(req: Request) -> str:
    """Endpoints de diagnóstico: solo administradores (o desarrollo con DEBUG_AI=1). Para los demás, ni existen."""
    u = me(req)
    if admin(u) or (not PROD and E.get("DEBUG_AI", "0") == "1"): return u
    raise ApiError(404, "No encontrado", "not_found")

# ───────────────────────── Validación de entradas ─────────────────────────
EMAIL_RX = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.[a-z]{2,24}$")
def clean_email(v) -> str:
    e = v.strip().lower() if isinstance(v, str) else ""
    if len(e) > 254 or not EMAIL_RX.match(e): raise ApiError(400, "Escribe un correo válido", "bad_email")
    return e
def domain_ok(e: str) -> bool:
    d = E.get("EMAIL_DOMAIN", "*"); return d == "*" or e.endswith("@" + d.lower())
def text(v, n, name="texto") -> str:
    """Texto del usuario: cadena, sin caracteres de control, recortada a n."""
    if v is None: return ""
    if not isinstance(v, str): raise ApiError(400, f"{name} no válido", "bad_input")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v).strip()[:n]
def need_json_obj(b) -> dict:
    if not isinstance(b, dict): raise ApiError(400, "Solicitud no válida", "bad_input")
    return b

# ───────────────────────── Protección de la app ─────────────────────────
def _origin_ok(origin: str) -> bool:
    from urllib.parse import urlparse
    o = urlparse(origin); base = urlparse(E.get("BASE_URL", "http://localhost:8000"))
    extra = {x.strip().rstrip("/") for x in E.get("ALLOWED_ORIGINS", "").split(",") if x.strip()}
    for v in ("VERCEL_URL", "VERCEL_BRANCH_URL"):   # la dirección propia de ESTE despliegue (las vistas previas tienen otra); la pone Vercel, el navegador no puede falsearla
        if E.get("VERCEL") and E.get(v): extra.add("https://" + E[v])
    if f"{o.scheme}://{o.netloc}" == f"{base.scheme}://{base.netloc}" or origin.rstrip("/") in extra: return True
    return (not PROD) and o.hostname in ("localhost", "127.0.0.1")
def harden(app: FastAPI, max_body: int = 262144):
    """Cabeceras seguras, límite de tamaño, comprobación de origen (anti-CSRF) y errores genéricos."""
    @app.middleware("http")
    async def _guard(req: Request, call_next):
        rid = uuid.uuid4().hex[:10]; req.state.rid = rid
        if req.method in ("POST", "PUT", "PATCH", "DELETE"):
            o = req.headers.get("origin")
            if (o and not _origin_ok(o)) or (not o and req.headers.get("sec-fetch-site") == "cross-site"):
                return JSONResponse(_body("Solicitud no permitida", "forbidden"), 403)
            try: n = int(req.headers.get("content-length") or 0)
            except ValueError: n = 0
            if n > max_body: return JSONResponse(_body("El contenido es demasiado grande", "too_large"), 413)
            ct = req.headers.get("content-type", "")
            if n and not ct.lower().startswith("application/json"): return JSONResponse(_body("Solicitud no válida", "bad_input"), 415)
        resp = await call_next(req)
        resp.headers["Cache-Control"] = "no-store"; resp.headers["X-Content-Type-Options"] = "nosniff"; resp.headers["Referrer-Policy"] = "no-referrer"
        return resp
    @app.exception_handler(HTTPException)
    async def _http(req: Request, ex: HTTPException):
        d = ex.detail
        if ex.status_code >= 500: log.error("[%s] %s %s -> %s", getattr(req.state, "rid", "-"), req.method, req.url.path, d); d = GENERIC
        code = getattr(ex, "code", None)
        if isinstance(d, dict): code = d.get("code", code); d = d.get("detail", GENERIC)
        if not isinstance(d, str): d = GENERIC
        return JSONResponse(_body(d, code), ex.status_code, headers=dict(ex.headers or {}))
    @app.exception_handler(RequestValidationError)
    async def _val(req: Request, ex: RequestValidationError):
        return JSONResponse(_body("Los datos enviados no son válidos", "bad_input"), 422)   # no se repite lo que escribió el usuario
    @app.exception_handler(Exception)
    async def _any(req: Request, ex: Exception):
        rid = getattr(req.state, "rid", "-")
        log.exception("[%s] error no controlado en %s %s", rid, req.method, req.url.path)
        return JSONResponse(_body(GENERIC, "internal", id=rid), 500)
    return app
def new_app(max_body: int = 262144) -> FastAPI:
    """FastAPI sin /docs, /redoc ni /openapi.json (no se publica el mapa interno de la API) y con todas las protecciones."""
    return harden(FastAPI(docs_url=None, redoc_url=None, openapi_url=None), max_body)
