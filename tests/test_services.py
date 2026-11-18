import json, time, os, tarfile, tempfile
import pytest
from fastapi.testclient import TestClient
import common, security
from test_flows import load, auth_main, full_signup, H, pow_, reg
chat = load("chat"); games = load("games"); survey = load("survey")
def client(app, tok=None):
    c = TestClient(app, base_url="http://localhost:8000", raise_server_exceptions=False)
    if tok: c.cookies.set(security.COOKIE, tok)
    return c
def user(email):
    a = TestClient(auth_main.app, base_url="http://localhost:8000"); full_signup(a, email); return a.cookies.get(security.COOKIE)
@pytest.fixture(autouse=True)
def stub(monkeypatch):
    monkeypatch.setattr(chat.llm, "generate", lambda system, msgs, max_tokens=500: ("Aquí estoy contigo.", "stub#1"))
    monkeypatch.setattr(chat, "summarize", lambda u: None)

def test_sin_sesion_todo_401():
    for app, paths in ((chat, ["/history", "/prefs"]), (games, ["/catalog"]), (survey, ["/pending"])):
        for p in paths: assert client(app.app).get(p).status_code == 401, p
    assert client(chat.app).post("/", json={"text": "hola"}, headers=H).status_code == 401
def test_sin_aceptar_terminos_403_en_todos_los_servicios():
    cur = common.pg().cursor(); cur.execute("INSERT INTO credentials(email,salt,pw_hash,verified,code,code_exp,tries) VALUES(%s,'',%s,true,'',0,0)", ("sin@uni.edu", security.pw_hash("Clave-Segura-77")))
    a = TestClient(auth_main.app, base_url="http://localhost:8000"); a.post("/signin", json={"email": "sin@uni.edu", "password": "Clave-Segura-77", "pow": pow_(a), "hp": ""}, headers=H); tok = a.cookies.get(security.COOKIE)
    for app, p in ((chat, "/history"), (games, "/catalog"), (survey, "/pending")):
        r = client(app.app, tok).get(p); assert r.status_code == 403 and r.json()["code"] == "consent_required", p
def test_permisos_en_cada_peticion_al_borrar_cuenta():
    tok = user("tmp@uni.edu"); c = client(chat.app, tok); assert c.get("/history").status_code == 200
    a = TestClient(auth_main.app, base_url="http://localhost:8000"); a.cookies.set(security.COOKIE, tok); assert a.post("/account/delete", json={"confirm": True}, headers=H).status_code == 200
    security._cache.clear(); assert c.get("/history").status_code == 401           # el token viejo (aún sin vencer) ya no abre nada
def test_boveda_cada_usuario_solo_ve_lo_suyo():
    t1, t2 = user("uno@uni.edu"), user("dos@uni.edu"); c1, c2 = client(chat.app, t1), client(chat.app, t2)
    assert c1.post("/", json={"text": "mi secreto numero uno"}, headers=H).status_code == 200
    assert c2.post("/", json={"text": "otro mensaje distinto"}, headers=H).status_code == 200
    h1 = json.dumps(c1.get("/history").json()); h2 = json.dumps(c2.get("/history").json())
    assert "secreto numero uno" in h1 and "secreto numero uno" not in h2 and "otro mensaje" in h2 and "otro mensaje" not in h1
def test_diagnosticos_solo_admin(monkeypatch):
    tok = user("norm@uni.edu"); c = client(chat.app, tok)
    for p in ("/status", "/diagnose", "/context"): assert c.get(p).status_code == 404, p
    for app in (chat, games, survey):
        for p in ("/docs", "/openapi.json", "/redoc"): assert client(app.app, tok).get(p).status_code == 404
    monkeypatch.setenv("ADMIN_EMAILS", "norm@uni.edu"); assert c.get("/context").status_code == 200
def test_validacion_de_entradas():
    tok = user("val@uni.edu"); c = client(chat.app, tok)
    assert c.post("/", json=["no", "objeto"], headers=H).status_code in (400, 422)
    assert c.post("/", json={"text": {"$ne": 1}}, headers=H).status_code == 400            # intento de inyección de operador NoSQL
    r = c.post("/", json={"text": "a" * 50000}, headers=H); assert r.status_code == 200
    assert max(len(d["text"]) for d in common.mongo.chat.find({"email": "val@uni.edu"})) <= 4000
    assert c.post("/prefs", json={"voice": {"$gt": ""}, "tone": "amigo"}, headers=H).status_code in (200, 400, 422)
    g = client(games.app, tok)
    r = g.post("/play", json={"game": {"x": 1}, "secs": "abc", "responses": "no"}, headers=H); assert r.status_code == 200 and r.json() == {"ok": False}
    assert g.post("/play", json={"game": "respira", "secs": "abc", "responses": [5, {"text": {"$x": 1}}, {"text": "bien"}]}, headers=H).status_code == 200
    assert g.post("/suggest", json={"topics": "ansiedad", "stress": "mucho"}, headers=H).status_code == 200
    s = client(survey.app, tok); assert s.post("/", json={"kind": "inicial", "answers": "no"}, headers=H).status_code in (400, 422)
    big = client(chat.app, tok).post("/", content=b"x" * 7_000_000, headers={**H, "content-type": "application/json"}); assert big.status_code == 413
def test_limite_de_uso_del_chat(monkeypatch):
    tok = user("lim@uni.edu"); c = client(chat.app, tok); codes = [c.post("/", json={"text": f"hola numero {i}"}, headers=H).status_code for i in range(25)]
    assert codes.count(429) >= 1 and codes[0] == 200
def test_sql_con_comillas_no_rompe_nada():
    tok = user("o'brien@uni.edu") if False else user("sql@uni.edu"); c = client(chat.app, tok)
    assert c.post("/", json={"text": "'; DROP TABLE surveys; --"}, headers=H).status_code == 200
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM credentials"); assert cur.fetchone()[0] >= 1
def test_error_interno_no_muestra_nada(monkeypatch):
    tok = user("err@uni.edu"); monkeypatch.setattr(chat, "get_prefs", lambda u: (_ for _ in ()).throw(RuntimeError("mongodb://root:CLAVE@mongo host=db")))
    r = client(chat.app, tok).get("/prefs"); assert r.status_code == 500 and "CLAVE" not in r.text and "mongodb" not in r.text

# ───────── copias de seguridad ─────────
def test_backup_cifrado_y_restauracion_reaplica_borrados(tmp_path, monkeypatch):
    import bk, backup, restore, purge
    monkeypatch.setattr(bk, "tables", lambda cur: [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'") or cur.fetchall()] if False else ["credentials", "account_state", "tombstones", "surveys"])
    monkeypatch.setattr(backup, "DIR", str(tmp_path)); k = bk.key()
    tok = user("keep@uni.edu"); user("gone@uni.edu")
    common.mongo.chat.insert_many([{"email": "keep@uni.edu", "role": "user", "text": "conservar", "ts": 1}, {"email": "gone@uni.edu", "role": "user", "text": "se va a borrar", "ts": 1}])
    common.raw("chat", "keep@uni.edu", {"text": "x"})
    backup.run_once(k); f = [x for x in os.listdir(tmp_path) if x.endswith(".enc")]; assert len(f) == 1 and os.path.exists(tmp_path / (f[0] + ".sha256"))
    raw = open(tmp_path / f[0], "rb").read(); assert b"conservar" not in raw and b"keep@uni.edu" not in raw and raw.startswith(bk.MAGIC)      # cifrado de verdad
    bad = tmp_path / "mala.enc"; bad.write_bytes(raw[:-5]); 
    with pytest.raises(Exception): bk.verify(str(bad), k)                                                                                  # truncada = detectada
    flip = bytearray(raw); flip[len(bk.MAGIC) + 20] ^= 1; (tmp_path / "flip.enc").write_bytes(bytes(flip))
    with pytest.raises(Exception): bk.verify(str(tmp_path / "flip.enc"), k)                                                                # alterada = detectada
    os.environ["BACKUP_KEY"] = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="
    with pytest.raises(Exception): bk.verify(str(tmp_path / f[0]), bk.key())                                                               # llave equivocada
    os.environ["BACKUP_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    purge.delete_account("gone@uni.edu"); backup.sync_tombstones()                  # el usuario se borra DESPUÉS de la copia
    for col in common.mongo.list_collection_names(): common.mongo[col].delete_many({})
    DBc = common.pg().cursor()
    for t in ("credentials", "account_state", "surveys", "tombstones", "consent_log"): DBc.execute(f"DELETE FROM {t}")
    common.s3.o.clear(); monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    restore.main(str(tmp_path / f[0]))
    assert common.mongo.chat.count_documents({"email": "keep@uni.edu"}) == 1 and common.mongo.chat.count_documents({"email": "gone@uni.edu"}) == 0    # no resucita
    DBc.execute("SELECT email FROM credentials ORDER BY 1"); assert [r[0] for r in DBc.fetchall()] == ["keep@uni.edu"]
    assert any(k.startswith("raw/chat/") for k in common.s3.o)
def test_backup_retencion(tmp_path, monkeypatch):
    import backup; monkeypatch.setattr(backup, "DIR", str(tmp_path)); monkeypatch.setattr(backup, "KEEP", 1)
    old = tmp_path / "serenia-19990101T000000Z.tar.gz.enc"; old.write_bytes(b"x"); os.utime(old, (1, 1))
    import bk; monkeypatch.setattr(bk, "tables", lambda cur: ["credentials"]); backup.run_once(bk.key()); assert not old.exists()

# ───────── mejora de la IA: solo con permiso ─────────
def test_etl_solo_aporta_al_corpus_con_permiso():
    import importlib.util
    sp = importlib.util.spec_from_file_location("etl_mod", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "etl", "etl.py")); etl = importlib.util.module_from_spec(sp); sp.loader.exec_module(etl)
    cur = common.pg().cursor(); c = {"emotion": "ansiedad", "problems": ["estudio"]}
    txt = "Estoy muy estresada, escríbeme a ana@uni.edu o al 3001234567 https://x.co/abc por favor"
    user("si@uni.edu"); user("no@uni.edu"); cur.execute("UPDATE account_state SET ai=true WHERE eh=%s", (security.eh("si@uni.edu"),)); etl._ai.clear()
    etl.improve("si@uni.edu", cur, "chat", txt, c); etl.improve("no@uni.edu", cur, "chat", txt, c); etl.improve("si@uni.edu", cur, "chat", "corto", c)
    docs = list(common.mongo.improve_corpus.find({})); assert len(docs) == 1 and docs[0]["uid"] == security.eh("si@uni.edu")
    t = docs[0]["text"]; assert "ana@uni.edu" not in t and "3001234567" not in t and "x.co" not in t and "[correo]" in t and "email" not in docs[0]   # seudonimizado
