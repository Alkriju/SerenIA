# Microservicio AUTH: registro/ingreso con correo + contraseña (Argon2id) + código por correo, Microsoft Entra ID opcional,
# consentimientos (con registro de quién y cuándo), exportar y borrar la cuenta. Toda entrada se valida aquí, en el servidor.
import msal, time, secrets, smtplib, ssl, json, threading
from email.message import EmailMessage
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from common import *
import purge
app = new_app(max_body=16384); boot()
SMTP_LOCK = threading.Semaphore(4)
IP_FAILS = int(E.get("LOGIN_IP_MAX_FAILS", "40"))   # por IP es más alto: en un campus muchos estudiantes comparten la misma IP pública
def body(b) -> dict: return need_json_obj(b)

# ───────── ayudas ─────────
def RU(): return E["BASE_URL"].rstrip("/") + "/api/auth/callback"
def ms(): return msal.ConfidentialClientApplication(E["MS_CLIENT_ID"], authority=f"https://login.microsoftonline.com/{E['MS_TENANT']}", client_credential=E["MS_SECRET"])
def ua(req): return security.text(req.headers.get("user-agent", ""), 200)
def sql(q, p=(), one=False, many=False):
    c = pg(); cur = c.cursor()
    try:
        cur.execute(q, p)
        return cur.fetchone() if one else (cur.fetchall() if many else None)
    finally: c.close()
def log_consent(email, docs, req, via):
    """Registra QUIÉN aceptó (correo + hash), QUÉ documento/versión, CUÁNDO (hora del servidor), y huella de IP y navegador."""
    k, ip = eh(email), security.h_ip(client_ip(req)); c = pg(); cur = c.cursor()
    for doc, ok in docs:
        cur.execute("INSERT INTO consent_log(eh,email,doc,version,accepted,ip_h,ua,via) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (k, email, doc, TERMS_VERSION, bool(ok), ip, ua(req), via))
    c.close()
def grant(email, ai, req, via):
    """Terms aceptados: queda en el registro y en el estado de la cuenta que revisan TODOS los servicios en cada petición."""
    log_consent(email, [("terminos_y_privacidad", True), ("datos_sensibles_y_proveedores_ia", True), ("mejora_ia", ai)], req, via)
    sql("INSERT INTO account_state(eh, sv, terms, ai, ts) VALUES (%s, 0, %s, %s, now()) ON CONFLICT (eh) DO UPDATE SET terms = EXCLUDED.terms, ai = EXCLUDED.ai, ts = now()", (eh(email), TERMS_VERSION, bool(ai)))   # conserva sv (versión de sesión)
    forget(email)
def session_response(email, payload=None, redirect=None):
    raw("user", email, {})
    r = RedirectResponse(redirect, 303) if redirect else JSONResponse(payload or {"ok": True})
    return security.set_cookie(r, email)
def send_code(to, code):
    if not E.get("SMTP_HOST"):
        print(f"[CODIGO] {to}: {code}", flush=True); return   # solo desarrollo (en producción SMTP_HOST es obligatorio: ver security.startup_checks)
    m = EmailMessage(); m["Subject"] = "Tu código de verificación de SerenIA"; m["From"] = E["SMTP_USER"]; m["To"] = to
    m.set_content(f"Tu código de verificación es {code}. Vence en 10 minutos.\n\nSi no fuiste tú, ignora este correo: nadie puede entrar sin el código.")
    with SMTP_LOCK, smtplib.SMTP(E["SMTP_HOST"], int(E.get("SMTP_PORT", "587")), timeout=15) as s:
        s.starttls(context=ssl.create_default_context()); s.login(E["SMTP_USER"], E["SMTP_PASS"]); s.send_message(m)

# ───────── Microsoft Entra ID (opcional) ─────────
@app.get("/login")
def login(req: Request):
    if E.get("DEV_AUTH") == "1" and not security.PROD: return session_response("dev@" + E.get("EMAIL_DOMAIN", "dev.local").lstrip("*."), redirect="/")
    if not E.get("MS_CLIENT_ID"): raise ApiError(404, "No disponible")
    return RedirectResponse(ms().get_authorization_request_url(["User.Read"], redirect_uri=RU()))
@app.get("/callback")
def cb(code: str, req: Request):
    rate(f"cb:{client_ip(req)}", 30, 600)
    c = ms().acquire_token_by_authorization_code(security.text(code, 4000), ["User.Read"], redirect_uri=RU()).get("id_token_claims")
    if not c: raise ApiError(401, "No se pudo iniciar sesión")
    e = (c.get("preferred_username") or "").lower()
    if not domain_ok(e): raise ApiError(403, "Usa tu correo institucional")
    if "mfa" not in c.get("amr", []): raise ApiError(403, "Se requiere verificación con Authenticator")
    return session_response(clean_email(e), redirect="/")

# ───────── Registro e ingreso ─────────
@app.get("/challenge")
def challenge(req: Request):
    rate(f"chal:{client_ip(req)}", 60, 600)
    return security.pow_challenge()
def human(b, req):
    """Honeypot + prueba de trabajo (captcha propio) + límite por IP. Devuelve False si el honeypot delata a un bot."""
    if security.text(b.get("hp", ""), 50): return False
    pw = b.get("pow")
    if not isinstance(pw, dict): raise ApiError(400, "No pudimos comprobar que eres una persona. Recarga la página e inténtalo de nuevo.", "captcha")
    security.pow_verify(pw); return True
@app.post("/register")
def register(b: dict, req: Request):
    b = body(b); ip = client_ip(req); rate(f"reg:ip:{ip}", 10, 3600)
    ok = {"ok": True}
    if not human(b, req): return ok                                   # bot: respuesta idéntica, no se hace nada
    e = clean_email(b.get("email")); pw = b.get("password")
    if not domain_ok(e): raise ApiError(400, f"Usa tu correo institucional (@{E.get('EMAIL_DOMAIN')})", "bad_domain")
    security.pw_policy(pw, e)
    if b.get("accept_terms") is not True or b.get("accept_sensitive") is not True:
        raise ApiError(400, "Para crear la cuenta debes aceptar los Términos, la Política de Privacidad y el tratamiento de datos sensibles.", "consent_required")
    rate(f"reg:mail:{eh(e)}", 3, 3600, "Ya enviamos varios códigos a este correo. Espera una hora o usa el último que recibiste.")
    r = sql("SELECT verified FROM credentials WHERE email=%s", (e,), one=True)
    if r and r[0]: return ok                                          # no revela si el correo ya existe (anti-enumeración)
    code = f"{secrets.randbelow(10**6):06d}"
    consent = json.dumps({"ai": b.get("accept_ai") is True, "ts": time.time()})
    sql("INSERT INTO credentials(email,salt,pw_hash,verified,code,code_exp,tries,consent) VALUES(%s,%s,%s,false,%s,%s,0,%s) ON CONFLICT (email) DO UPDATE SET salt=EXCLUDED.salt, pw_hash=EXCLUDED.pw_hash, verified=false, code=EXCLUDED.code, code_exp=EXCLUDED.code_exp, tries=0, consent=EXCLUDED.consent", (e, "", security.pw_hash(pw), security.code_hash(e, code), time.time() + 600, consent))
    send_code(e, code); return ok
@app.post("/verify")
def verify(b: dict, req: Request):
    b = body(b); rate(f"ver:ip:{client_ip(req)}", 20, 600); e = clean_email(b.get("email")); code = security.text(b.get("code"), 12)
    r = sql("SELECT code,code_exp,tries,consent FROM credentials WHERE email=%s AND verified=false", (e,), one=True)
    if not r or r[2] >= 5 or time.time() > r[1]: raise ApiError(400, "Código vencido o bloqueado: regístrate de nuevo", "bad_code")
    if not secrets.compare_digest(security.code_hash(e, code), r[0] or ""):
        sql("UPDATE credentials SET tries=tries+1 WHERE email=%s", (e,)); raise ApiError(400, "Código incorrecto", "bad_code")
    sql("UPDATE credentials SET verified=true, code='', code_exp=0, consent=NULL WHERE email=%s", (e,))
    try: ai = bool(json.loads(r[3] or "{}").get("ai"))
    except Exception: ai = False
    grant(e, ai, req, "registro"); return session_response(e)
@app.post("/signin")
def signin(b: dict, req: Request):
    b = body(b); ip = client_ip(req); rate(f"sig:ip:{ip}", 30, 600)
    if not human(b, req): raise ApiError(401, "Correo o contraseña incorrectos", "bad_credentials")
    e = clean_email(b.get("email")); pw = b.get("password")
    if not isinstance(pw, str) or not 1 <= len(pw) <= 128: raise ApiError(401, "Correo o contraseña incorrectos", "bad_credentials")
    k = f"acct:{eh(e)}"; security.lock_check(k); security.lock_check(f"ip:{ip}")
    r = sql("SELECT salt,pw_hash,verified FROM credentials WHERE email=%s", (e,), one=True)
    ok, new = security.pw_check(pw, r[1] if r else None, r[0] if r else None)    # gasta el mismo tiempo exista o no el correo
    if not ok:
        security.lock_fail(k); security.lock_fail(f"ip:{ip}", IP_FAILS); raise ApiError(401, "Correo o contraseña incorrectos", "bad_credentials")
    if not r[2]: raise ApiError(403, "Falta verificar tu correo: regístrate de nuevo para recibir otro código", "unverified")
    if new: sql("UPDATE credentials SET pw_hash=%s, salt='' WHERE email=%s", (new, e))   # migra hashes antiguos (PBKDF2) a Argon2id
    security.lock_clear(k); return session_response(e)
@app.post("/logout")
def logout(): return security.clear_cookie(JSONResponse({"ok": True}))

# ───────── Sesión y consentimientos ─────────
@app.get("/me")
def whoami(u=Depends(me_nc)):
    sv, terms, ai = security.state(u, True)
    return {"email": u, "consent_ok": terms == TERMS_VERSION, "terms_version": TERMS_VERSION, "ai_improve": bool(ai) and terms == TERMS_VERSION}
@app.post("/consent")
def consent(b: dict, req: Request, u=Depends(me_nc)):
    b = body(b); rate(f"cons:{eh(u)}", 20, 600)
    if b.get("accept_terms") is not True or b.get("accept_sensitive") is not True:
        raise ApiError(400, "Debes aceptar los Términos, la Política de Privacidad y el tratamiento de datos sensibles para usar SerenIA.", "consent_required")
    grant(u, b.get("ai_improve") is True, req, "aceptacion")
    return {"ok": True, "ai_improve": b.get("ai_improve") is True}
@app.post("/consent/ai")
def consent_ai(b: dict, req: Request, u=Depends(me)):
    """Activar/retirar el uso de mis datos (seudonimizados) para mejorar la IA. Al retirarlo se borra lo que ya estaba en ese conjunto."""
    b = body(b); rate(f"cons:{eh(u)}", 20, 600)
    if not isinstance(b.get("ai_improve"), bool): raise ApiError(400, "Solicitud no válida", "bad_input")
    ai = b["ai_improve"]; log_consent(u, [("mejora_ia", ai)], req, "ajustes")
    sql("UPDATE account_state SET ai=%s, ts=now() WHERE eh=%s", (ai, eh(u))); forget(u)
    if not ai: mongo.improve_corpus.delete_many({"uid": eh(u)})
    return {"ok": True, "ai_improve": ai}

# ───────── Derechos del titular: exportar y borrar ─────────
@app.get("/export")
def export(u=Depends(me_nc)):
    rate(f"exp:{eh(u)}", 5, 3600)
    return JSONResponse(purge.export_account(u), headers={"Content-Disposition": 'attachment; filename="mis-datos-serenia.json"'})
@app.post("/account/delete")
def delete(b: dict, u=Depends(me_nc)):
    """Tan fácil como crearla: una confirmación. Borra todo en todos los almacenes y cierra la sesión."""
    if body(b).get("confirm") is not True: raise ApiError(400, "Falta la confirmación", "bad_input")
    rate(f"del:{eh(u)}", 5, 3600)
    res = purge.delete_account(u); print(f"[CUENTA BORRADA] {eh(u)[:10]}… {res}", flush=True)   # el log solo lleva el hash, nunca el correo
    return security.clear_cookie(JSONResponse({"ok": True}))
