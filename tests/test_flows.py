import hashlib, json, time, re, pytest
from fastapi.testclient import TestClient
import common, security
import importlib.util, os
def load(svc):  # cada servicio se llama main.py: se carga por ruta para no mezclarlos
    sp = importlib.util.spec_from_file_location("main_" + svc, os.path.join(conftest_root, "services", svc, "main.py")); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
from conftest import R as conftest_root
auth_main = load("auth")
H = {"origin": "http://localhost:8000"}
def solve(ch):
    n = 0
    while True:
        d = hashlib.sha256(f"{ch['salt']}:{n}".encode()).digest()
        if security._lead_zero_bits(d) >= ch["bits"]: return {**{k: ch[k] for k in ("id", "salt", "bits", "exp", "sig")}, "nonce": str(n)}
        n += 1
@pytest.fixture()
def c(): return TestClient(auth_main.app, base_url="http://localhost:8000")
def pow_(c): return solve(c.get("/challenge").json())
def reg(c, email="ana@uni.edu", pw="Clave-Segura-77", ai=False, **x):
    body = dict(email=email, password=pw, pow=pow_(c), hp="", accept_terms=True, accept_sensitive=True, accept_ai=ai); body.update(x)
    return c.post("/register", json=body, headers=H)
def code_for(email):
    row = common.pg().cursor(); row.execute("SELECT code FROM credentials WHERE email=?".replace("?", "%s"), (email,)); return row.fetchone()[0]
def full_signup(c, email="ana@uni.edu", ai=False):
    sent = {}
    auth_main.send_code = lambda to, code: sent.update(code=code)
    assert reg(c, email, ai=ai).json() == {"ok": True}
    r = c.post("/verify", json={"email": email, "code": sent["code"]}, headers=H); assert r.status_code == 200, r.text
    return sent["code"]

def test_registro_exige_casillas_y_captcha(c):
    assert reg(c, accept_terms=False).status_code == 400
    assert reg(c, accept_sensitive=False).status_code == 400
    r = c.post("/register", json={"email": "a@uni.edu", "password": "Clave-Segura-77", "accept_terms": True, "accept_sensitive": True}, headers=H); assert r.status_code == 400 and r.json()["code"] == "captcha"
    bad = pow_(c); bad["nonce"] = "1"; bad["bits"] = 1
    assert c.post("/register", json={"email": "a@uni.edu", "password": "Clave-Segura-77", "pow": bad, "accept_terms": True, "accept_sensitive": True}, headers=H).status_code == 400
def test_captcha_un_solo_uso(c):
    p = pow_(c)
    body = dict(email="uno@uni.edu", password="Clave-Segura-77", pow=p, hp="", accept_terms=True, accept_sensitive=True)
    auth_main.send_code = lambda *a: None
    assert c.post("/register", json=body, headers=H).status_code == 200
    r = c.post("/register", json=body, headers=H); assert r.status_code == 400 and r.json()["code"] == "captcha"
def test_honeypot_no_hace_nada(c):
    assert reg(c, "bot@uni.edu", hp="soy un bot").json() == {"ok": True}
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM credentials WHERE email=%s", ("bot@uni.edu",)); assert cur.fetchone()[0] == 0
def test_contrasenas_debiles_y_correos(c):
    assert reg(c, pw="corta").status_code == 400
    assert reg(c, pw="12345678").status_code == 400
    assert reg(c, email="no-es-correo").status_code == 400
    assert reg(c, email="x" * 300 + "@uni.edu").status_code == 400
def test_flujo_completo_y_argon2(c):
    full_signup(c, "luis@uni.edu", ai=True)
    cur = common.pg().cursor(); cur.execute("SELECT pw_hash, code, consent FROM credentials WHERE email=%s", ("luis@uni.edu",)); h, code, cons = cur.fetchone()
    assert h.startswith("$argon2id$") and code == "" and cons is None      # contraseña con Argon2id; el código no queda guardado
    assert c.get("/me").json() == {"email": "luis@uni.edu", "consent_ok": True, "terms_version": security.TERMS_VERSION, "ai_improve": True}
    cur.execute("SELECT doc, accepted, email, ip_h FROM consent_log WHERE eh=%s ORDER BY doc", (security.eh("luis@uni.edu"),)); rows = cur.fetchall()
    assert {r[0]: r[1] for r in rows} == {"datos_sensibles_y_proveedores_ia": 1, "mejora_ia": 1, "terminos_y_privacidad": 1} and all(r[2] == "luis@uni.edu" and r[3] for r in rows)
def test_codigo_se_guarda_hasheado_y_bloquea_a_los_5_intentos(c):
    sent = {}; auth_main.send_code = lambda to, code: sent.update(code=code)
    reg(c, "pablo@uni.edu"); assert code_for("pablo@uni.edu") != sent["code"]
    for _ in range(5): assert c.post("/verify", json={"email": "pablo@uni.edu", "code": "000000"}, headers=H).status_code == 400
    assert c.post("/verify", json={"email": "pablo@uni.edu", "code": sent["code"]}, headers=H).status_code == 400    # ya bloqueado
def test_correo_existente_no_se_revela(c):
    full_signup(c, "ya@uni.edu"); sent = {}; auth_main.send_code = lambda to, code: sent.update(code=code)
    assert reg(c, "ya@uni.edu").json() == {"ok": True} and not sent                    # misma respuesta, no se envía nada
def test_limite_de_intentos_y_bloqueo(c):
    full_signup(c, "eva@uni.edu"); c2 = TestClient(auth_main.app, base_url="http://localhost:8000")
    def si(pw): return c2.post("/signin", json={"email": "eva@uni.edu", "password": pw, "pow": pow_(c2), "hp": ""}, headers=H)
    for _ in range(5): assert si("mala-clave-1").status_code == 401
    r = si("Clave-Segura-77"); assert r.status_code == 429 and "Retry-After" in r.headers and r.json()["code"] == "locked"   # incluso con la clave correcta
    common.mongo.lockouts.delete_many({}); assert si("Clave-Segura-77").status_code == 200
def test_signin_mensaje_generico(c):
    r = c.post("/signin", json={"email": "nadie@uni.edu", "password": "xxxxxxxxxx", "pow": pow_(c), "hp": ""}, headers=H)
    assert r.status_code == 401 and r.json()["detail"] == "Correo o contraseña incorrectos"
def test_migracion_pbkdf2_a_argon2(c):
    salt = "ab" * 16; old = security._legacy("Clave-Antigua-99", salt); cur = common.pg().cursor()
    cur.execute("INSERT INTO credentials(email,salt,pw_hash,verified,code,code_exp,tries) VALUES(%s,%s,%s,true,'',0,0)", ("vieja@uni.edu", salt, old))
    assert c.post("/signin", json={"email": "vieja@uni.edu", "password": "Clave-Antigua-99", "pow": pow_(c), "hp": ""}, headers=H).status_code == 200
    cur.execute("SELECT pw_hash FROM credentials WHERE email=%s", ("vieja@uni.edu",)); assert cur.fetchone()[0].startswith("$argon2id$")
    assert c.get("/me").json()["consent_ok"] is False        # usuario anterior a los términos: debe aceptarlos
def test_cookie_segura_y_caduca(c):
    full_signup(c, "coo@uni.edu"); r = c.post("/signin", json={"email": "coo@uni.edu", "password": "Clave-Segura-77", "pow": pow_(c), "hp": ""}, headers=H)
    sc = r.headers["set-cookie"].lower(); assert "httponly" in sc and "samesite=lax" in sc and "max-age=" in sc and "path=/" in sc
    tok = r.cookies.get(security.COOKIE) or c.cookies.get(security.COOKIE); import jwt; d = jwt.decode(tok, options={"verify_signature": False}); assert d["exp"] - d["iat"] == security.SESSION_HOURS * 3600 and "jti" in d
def test_sesion_falsa_o_vencida(c):
    import jwt
    assert c.get("/me").status_code == 401
    c.cookies.set(security.COOKIE, jwt.encode({"e": "x@uni.edu", "sv": 0, "exp": int(time.time()) - 10}, "t" * 40, "HS256")); assert c.get("/me").status_code == 401
    c.cookies.set(security.COOKIE, jwt.encode({"e": "x@uni.edu", "sv": 0, "exp": int(time.time()) + 999}, "otra-clave-distinta-de-32-chars-o-mas", "HS256")); assert c.get("/me").status_code == 401
    c.cookies.set(security.COOKIE, jwt.encode({"e": "x@uni.edu", "sv": 0}, "t" * 40, "HS256")); assert c.get("/me").status_code == 401    # sin exp
def test_origen_cruzado_bloqueado(c):
    r = c.post("/logout", json={}, headers={"origin": "https://malo.example"}); assert r.status_code == 403
    r = c.post("/logout", content="a=1", headers={**H, "content-type": "application/x-www-form-urlencoded"}); assert r.status_code == 415
def test_sin_documentacion_publica(c):
    for p in ("/docs", "/redoc", "/openapi.json"): assert c.get(p).status_code == 404
def test_errores_no_filtran_internos(c, monkeypatch):
    monkeypatch.setattr(auth_main, "sql", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("password=SECRETO host=10.0.0.5 traceback")))
    r = TestClient(auth_main.app, base_url="http://localhost:8000", raise_server_exceptions=False).post("/signin", json={"email": "a@uni.edu", "password": "xxxxxxxxxx", "pow": pow_(c), "hp": ""}, headers=H)
    assert r.status_code == 500 and "SECRETO" not in r.text and "10.0.0.5" not in r.text and r.json()["detail"] == security.GENERIC
    r = c.post("/register", json={"email": ["x"], "password": 5}, headers=H); assert r.status_code in (400, 422) and "x" not in json.dumps(r.json()).replace("detail", "")
def test_exportar_y_borrar_cuenta(c):
    full_signup(c, "del@uni.edu", ai=True); u = "del@uni.edu"
    common.mongo.chat.insert_one({"email": u, "role": "user", "text": "hola secreto", "ts": 1}); common.mongo.profiles.insert_one({"email": u, "x": 1}); common.mongo.improve_corpus.insert_one({"uid": security.eh(u), "text": "t"})
    common.mongo.chat.insert_one({"email": "otro@uni.edu", "role": "user", "text": "ajeno", "ts": 1})
    common.raw("chat", u, {"text": "x"}); common.raw("chat", "otro@uni.edu", {"text": "y"}); k = [k for k in common.s3.o if json.loads(common.s3.o[k]).get("user") == u][0]; common.s3.o["processed/" + k[4:]] = common.s3.o[k]
    cur = common.pg().cursor(); cur.execute("INSERT INTO surveys(email,kind,mood) VALUES(%s,%s,%s)", (u, "inicial", 3))
    ex = c.get("/export"); assert ex.status_code == 200 and "attachment" in ex.headers["content-disposition"] and "hola secreto" in ex.text and "ajeno" not in ex.text
    assert c.post("/account/delete", json={}, headers=H).status_code == 400
    assert c.post("/account/delete", json={"confirm": True}, headers=H).status_code == 200
    assert common.mongo.chat.count_documents({"email": u}) == 0 and common.mongo.profiles.count_documents({"email": u}) == 0 and common.mongo.improve_corpus.count_documents({}) == 0
    assert common.mongo.chat.count_documents({"email": "otro@uni.edu"}) == 1                                  # lo de otras personas NO se toca
    assert not [k for k, v in common.s3.o.items() if json.loads(v).get("user") == u] and any(json.loads(v).get("user") == "otro@uni.edu" for v in common.s3.o.values() if v.startswith(b"{") and b'"kind"' in v)
    for t in ("surveys", "credentials", "users"): cur.execute(f"SELECT count(*) FROM {t} WHERE email=%s", (u,)); assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM tombstones WHERE eh=%s", (security.eh(u),)); assert cur.fetchone()[0] == 1
    cur.execute("SELECT email FROM consent_log WHERE eh=%s", (security.eh(u),)); rows = cur.fetchall(); assert rows and all(r[0] is None for r in rows)   # se conserva la prueba, sin el correo
    security.forget(u); assert c.get("/me").status_code == 401                                                 # la sesión vieja ya no sirve
    assert c.cookies.get(security.COOKIE) in (None, "")
def test_consentimiento_obligatorio_en_otros_servicios(c):
    import jwt
    cur = common.pg().cursor(); cur.execute("INSERT INTO credentials(email,salt,pw_hash,verified,code,code_exp,tries) VALUES(%s,'',%s,true,'',0,0)", ("nuevo@uni.edu", security.pw_hash("Clave-Segura-77")))
    r = c.post("/signin", json={"email": "nuevo@uni.edu", "password": "Clave-Segura-77", "pow": pow_(c), "hp": ""}, headers=H); assert r.status_code == 200
    class Q:  # simula la dependencia me() de cualquier otro servicio
        def __init__(s, ck): s.cookies = ck
    tok = c.cookies.get(security.COOKIE)
    with pytest.raises(security.ApiError) as ei: security.me(Q({security.COOKIE: tok}))
    assert ei.value.status_code == 403 and ei.value.code == "consent_required"
    assert c.post("/consent", json={"accept_terms": True}, headers=H).status_code == 400
    assert c.post("/consent", json={"accept_terms": True, "accept_sensitive": True, "ai_improve": False}, headers=H).status_code == 200
    security.forget("nuevo@uni.edu"); assert security.me(Q({security.COOKIE: tok})) == "nuevo@uni.edu"
def test_retirar_mejora_ia_borra_lo_aportado(c):
    full_signup(c, "ia@uni.edu", ai=True); common.mongo.improve_corpus.insert_one({"uid": security.eh("ia@uni.edu"), "text": "x"})
    assert c.post("/consent/ai", json={"ai_improve": False}, headers=H).json()["ai_improve"] is False
    assert common.mongo.improve_corpus.count_documents({}) == 0 and c.get("/me").json()["ai_improve"] is False
def test_rate_limit_registro_por_correo(c):
    auth_main.send_code = lambda *a: None
    for i in range(3): assert reg(c, "spam@uni.edu").status_code == 200
    assert reg(c, "spam@uni.edu").status_code == 429
