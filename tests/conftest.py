"""Pruebas de seguridad SIN Docker: MongoDB -> mongomock, PostgreSQL -> SQLite (con traducción mínima de dialecto), S3 -> diccionario.
Ejecutar:  pip install pytest mongomock argon2-cffi fastapi httpx pyjwt msal boto3 psycopg2-binary pymongo cryptography ;  pytest -q tests"""
import os, sys, re, json, sqlite3, threading
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("shared", "services/auth", "services/chat", "services/survey", "services/games", "services/backup", "services/etl"): sys.path.insert(0, os.path.join(R, p))
os.environ.update(S3_URL="http://x", S3_KEY="a", S3_SECRET="b", MONGO_URL="mongodb://x", DATABASE_URL="postgresql://x", JWT_SECRET="t" * 40, PSEUDO_KEY="p" * 40,
                  BASE_URL="http://localhost:8000", EMAIL_DOMAIN="*", ARGON_M="1024", ARGON_T="1", ARGON_P="1", APP_ENV="development", DEBUG_AI="0",
                  BACKUP_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=", GEMINI_API_KEYS="", LLM_ORDER="gemini")
os.environ.setdefault("POW_BITS", "8"); os.environ.pop("SMTP_HOST", None)
import mongomock, pymongo
pymongo.MongoClient = mongomock.MongoClient

class FakeS3:
    def __init__(self): self.o = {}
    def put_object(self, Bucket, Key, Body): self.o[Key] = Body if isinstance(Body, bytes) else Body.encode()
    def get_object(self, Bucket, Key):
        import io; return {"Body": io.BytesIO(self.o[Key])}
    def delete_object(self, Bucket, Key): self.o.pop(Key, None)
    def copy_object(self, Bucket, Key, CopySource): self.o[Key] = self.o[CopySource["Key"]]
    def create_bucket(self, Bucket): pass
    def list_buckets(self): return {}
    def get_paginator(self, _):
        s3 = self
        class P:
            def paginate(self, Bucket, Prefix="", Delimiter=None):
                keys = sorted(k for k in s3.o if k.startswith(Prefix)); page = {}
                if Delimiter:
                    cp = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter for k in keys if Delimiter in k[len(Prefix):]})
                    page["CommonPrefixes"] = [{"Prefix": c} for c in cp]; keys = [k for k in keys if Delimiter not in k[len(Prefix):]]
                page["Contents"] = [{"Key": k} for k in keys]; yield page
        return P()

def _tr(q):
    q = q.strip()
    if q.upper().startswith("ALTER TABLE"): q = q.replace("IF NOT EXISTS ", "")
    q = q.replace("%s", "?").replace("gen_random_uuid()", "(lower(hex(randomblob(16))))").replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP").replace("now()", "CURRENT_TIMESTAMP")
    q = re.sub(r"\bSTRING\b", "TEXT", q); q = re.sub(r"\bUUID\b", "TEXT", q); q = re.sub(r"\bBOOL\b", "INTEGER", q)
    return q
class Cur:
    def __init__(self, db): self.db = db; self.c = db.cursor(); self.connection = self
    def execute(self, q, p=()):
        q2 = _tr(q)
        if "information_schema.tables" in q2: q2 = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1"
        try: self.c.execute(q2, tuple(p))
        except sqlite3.OperationalError as e:
            if q2.upper().startswith("ALTER TABLE") and "duplicate column" in str(e): return
            raise
        self.rowcount = self.c.rowcount; self.description = self.c.description
    def fetchone(self): return self.c.fetchone()
    def fetchall(self): return self.c.fetchall()
    def close(self): pass
class Conn:
    def __init__(self, db): self.db = db
    def cursor(self): return Cur(self.db)
    def close(self): pass
DB = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
import common
REAL_PG = os.environ.get("TEST_DATABASE_URL")   # con esta variable las pruebas corren contra un PostgreSQL REAL (en vez de SQLite):  TEST_DATABASE_URL=postgresql://usuario:clave@localhost/serenia pytest
if REAL_PG:
    import psycopg2
    def _real():
        c = psycopg2.connect(REAL_PG); c.autocommit = True; return c
    common.pg = _real
else: common.pg = lambda: Conn(DB)
common.s3 = FakeS3()
common.boot = lambda: None
common.init()

import pytest
@pytest.fixture(autouse=True)
def limpio():
    """Cada prueba empieza sin contadores, sin datos y sin caché de sesiones."""
    for col in common.mongo.list_collection_names(): common.mongo[col].delete_many({})
    if REAL_PG:
        c = common.pg(); cur = c.cursor(); cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'schema_meta'")
        for (t,) in cur.fetchall(): cur.execute(f'TRUNCATE "{t}"')
        c.close()
    else:
        cur = DB.cursor()
        for (t,) in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name <> 'schema_meta'").fetchall(): DB.execute(f"DELETE FROM {t}")
    common.s3.o.clear(); import security; security._cache.clear(); yield
