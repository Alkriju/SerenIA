"""Modo Vercel: api/index.py (4 servicios en una función + tareas programadas), ETL por pasadas, copia de seguridad en la nube y restauración."""
import os, sys, io, json, time, datetime as dt, importlib.util
import pytest
from fastapi.testclient import TestClient
import conftest, common, security
from conftest import R, FakeS3
from test_flows import full_signup, auth_main
from test_services import user

SECRET = "s" * 40
os.environ["CRON_SECRET"] = SECRET
sp = importlib.util.spec_from_file_location("api_index", os.path.join(R, "api", "index.py")); api = importlib.util.module_from_spec(sp); sp.loader.exec_module(api)
AUTH = {"authorization": "Bearer " + SECRET}
@pytest.fixture()
def cl(): return TestClient(api.app, base_url="http://localhost:8000")

class BkS3(FakeS3):   # almacenamiento "externo" de prueba: guarda fecha de cada objeto y sabe subir archivos
    def __init__(self): super().__init__(); self.t = {}
    def put_object(self, Bucket, Key, Body): super().put_object(Bucket, Key, Body); self.t[Key] = dt.datetime.utcnow()
    def upload_file(self, path, Bucket, Key): self.put_object(Bucket, Key, open(path, "rb").read())
    def get_paginator(self, _):
        p = super().get_paginator(_); outer = self
        class P:
            def paginate(s, **kw):
                for pg in p.paginate(**kw): yield {"Contents": [{"Key": c["Key"], "LastModified": outer.t.get(c["Key"], dt.datetime.utcnow())} for c in pg.get("Contents", [])]}
        return P()

def test_rutas_de_los_servicios_y_salud(cl):
    assert cl.get("/api/health").json() == {"ok": True}
    assert cl.get("/api/chat/history").status_code == 401        # cada servicio responde bajo su prefijo y exige sesión
    assert cl.get("/api/games/catalog").status_code == 401 and cl.get("/api/survey/pending").status_code == 401
    assert cl.get("/api/auth/challenge").status_code == 200
    assert cl.get("/api/nada").status_code == 404

def test_cron_exige_secreto(cl):
    assert cl.get("/api/cron/etl").status_code == 401
    assert cl.get("/api/cron/etl", headers={"authorization": "Bearer otro"}).status_code == 401
    assert cl.get("/api/cron/backup").status_code == 401
    old = os.environ.pop("CRON_SECRET"); os.environ["CRON_SECRET"] = "corto"
    try: assert cl.get("/api/cron/etl", headers={"authorization": "Bearer corto"}).status_code == 401   # secreto débil = tareas apagadas
    finally: os.environ["CRON_SECRET"] = old

def test_etl_pasada_procesa_una_sola_vez(cl):
    common.raw("survey", "x@uni.edu", {"kind": "inicial", "mood": 3, "stress": 4, "sleep": 3, "dropout": 1})
    common.raw("chat", "x@uni.edu", {"role": "user", "text": "Tengo un parcial mañana y estoy muy nerviosa"})
    r = cl.get("/api/cron/etl", headers=AUTH).json(); assert r["ok"] and r["processed"] >= 2 and r["failed"] == 0 and r["seed"] > 0 and r["secs"] >= 0
    assert common.mongo.knowledge.count_documents({}) > 0                           # el conocimiento llegó a Mongo vía datalake
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM emotion_log WHERE email=%s", ("x@uni.edu",)); n = cur.fetchone()[0]; assert n >= 1
    assert any(k.startswith("processed/") for k in common.s3.o) and any(k.startswith("raw/") for k in common.s3.o)   # raw se conserva
    r2 = cl.get("/api/cron/etl", headers=AUTH).json(); assert r2["ok"] and r2["seed"] == 0 and r2["processed"] == 0                             # el conocimiento no se vuelve a cargar
    cur.execute("SELECT count(*) FROM emotion_log WHERE email=%s", ("x@uni.edu",)); assert cur.fetchone()[0] == n      # y nada se procesa dos veces

def test_cron_no_se_ejecuta_dos_veces_a_la_vez(cl):
    common.mongo.locks.replace_one({"_id": "etl"}, {"_id": "etl", "exp": dt.datetime.utcnow() + dt.timedelta(seconds=100)}, upsert=True)
    assert cl.get("/api/cron/etl", headers=AUTH).json().get("skipped")

def test_chat_en_vercel_guarda_decision_sin_hilos_y_resume_en_etl(monkeypatch, cl):
    chat = api.chat; monkeypatch.setattr(chat, "SERVERLESS", True); monkeypatch.setattr(chat.llm, "generate", lambda system, msgs, max_tokens=500: ("Aquí estoy.", "stub#1"))
    tok = user("a@uni.edu"); c = TestClient(api.app, base_url="http://localhost:8000"); c.cookies.set(security.COOKIE, tok)
    r = c.post("/api/chat/", json={"text": "me siento ansiosa por el examen", "mode": "text"}, headers={"origin": "http://localhost:8000"}); assert r.status_code == 200, r.text
    assert any(k.startswith("raw/decision/") for k in common.s3.o)       # se guardó ya, no en un hilo que Vercel congelaría
    g = c.post("/api/chat/games", json={"topics": ["ansiedad"]}, headers={"origin": "http://localhost:8000"}).json(); assert g["games"] and g["games"][0]["cat"] == "calma"   # sugerencia en el mismo proceso
    import memsum
    common.mongo.chat.insert_many([{"email": "a@uni.edu", "role": "user", "text": f"m{i}", "ts": time.time() + i} for i in range(15)])
    assert memsum.due_users() == ["a@uni.edu"]

def test_init_es_idempotente_y_versionado():
    common.init(force=True); common.init(force=True); common._ready = False; common.init()
    cur = common.pg().cursor(); cur.execute("SELECT v FROM schema_meta WHERE k='v'"); assert cur.fetchone()[0] == common.SCHEMA_V

def test_copia_en_la_nube_cifrada_verificada_y_restaurable(tmp_path, monkeypatch):
    import backup, restore, purge, bk
    ext = BkS3(); monkeypatch.setattr(backup, "ext_store", lambda: (ext, "externo")); monkeypatch.setattr(purge, "offsite", lambda: (ext, "externo")); monkeypatch.setattr(restore, "offsite", lambda: (ext, "externo"))
    monkeypatch.setattr(bk, "tables", lambda cur: ["credentials", "account_state", "tombstones", "surveys", "consent_log", "users", "emotion_log", "game_plays"])
    user("keep@uni.edu"); user("gone@uni.edu")
    common.mongo.chat.insert_many([{"email": "keep@uni.edu", "role": "user", "text": "conservar", "ts": 1}, {"email": "gone@uni.edu", "role": "user", "text": "se va a borrar", "ts": 1}])
    st = backup.cloud_backup(); assert st["ok"] and st["where"] == "externo"
    enc = [k for k in ext.o if k.endswith(".enc")]; assert len(enc) == 1 and enc[0] + ".sha256" in ext.o
    assert b"conservar" not in ext.o[enc[0]] and b"keep@uni.edu" not in ext.o[enc[0]]      # cifrada de verdad
    assert "meta/backup_status.json" in common.s3.o
    purge.delete_account("gone@uni.edu")                                                    # borrado DESPUÉS de la copia
    assert any(k.startswith("tombstones/") for k in ext.o)                                  # la marca queda fuera del datalake
    f = tmp_path / "b.enc"; f.write_bytes(ext.o[enc[0]]); monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    restore.main(str(f)); restore.main(str(f))                                              # restaurar dos veces no duplica ni rompe
    assert common.mongo.chat.count_documents({"email": "keep@uni.edu"}) == 1
    assert common.mongo.chat.count_documents({"email": "gone@uni.edu"}) == 0               # la cuenta borrada NO resucita
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM credentials WHERE email=%s", ("gone@uni.edu",)); assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM credentials WHERE email=%s", ("keep@uni.edu",)); assert cur.fetchone()[0] == 1

def test_copia_en_la_nube_retencion_y_mismo_bucket(monkeypatch):
    import backup, bk
    monkeypatch.setattr(backup, "ext_store", lambda: None)
    monkeypatch.setattr(bk, "tables", lambda cur: ["credentials"])
    common.s3.o["backups/serenia-20200101T000000Z.tar.gz.enc"] = b"viejo"
    class Old(FakeS3): pass
    orig = common.s3.get_paginator
    def pag(_):
        p = orig(_)
        class P:
            def paginate(s, **kw):
                for pg in p.paginate(**kw): yield {"Contents": [{"Key": c["Key"], "LastModified": dt.datetime(2020, 1, 1) if "2020" in c["Key"] else dt.datetime.utcnow()} for c in pg.get("Contents", [])]}
        return P()
    monkeypatch.setattr(common.s3, "get_paginator", pag, raising=False); common.s3.upload_file = lambda path, b, k: common.s3.put_object(b, k, open(path, "rb").read())
    st = backup.cloud_backup(); assert st["where"] == "mismo bucket" and st["deleted_old"] == 1
    assert "backups/serenia-20200101T000000Z.tar.gz.enc" not in common.s3.o and any(k.startswith("backups/serenia-2026") or k.startswith("backups/serenia-") for k in common.s3.o)

def test_en_vercel_encuestas_y_juegos_se_ven_al_instante(monkeypatch):
    monkeypatch.setattr(common, "SERVERLESS", True)
    common.raw("game", "q@uni.edu", {"game": "respira", "name": "Respira", "cat": "calma", "completed": True, "secs": 60})
    cur = common.pg().cursor(); cur.execute("SELECT count(*) FROM game_plays WHERE email=%s", ("q@uni.edu",)); assert cur.fetchone()[0] == 1   # ya está en PostgreSQL, sin esperar al cron
    assert any(k.startswith("processed/game/") for k in common.s3.o)
    import etl
    assert etl.process(cur, etl.marks()) == (0, 0)   # nada pendiente
    cur.execute("SELECT count(*) FROM game_plays WHERE email=%s", ("q@uni.edu",)); assert cur.fetchone()[0] == 1   # y la pasada programada no lo repite
